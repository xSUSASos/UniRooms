import { useEffect, useState } from 'react'
import { api } from '../api'
import { DAY_SHORT, useApp, useLookups } from '../context'
import type { Suggestion } from '../types'

export function LessonPanel({ id, onClose }: { id: number; onClose: () => void }) {
  const { data, conflicts, reload, toast, editLesson, confirm } = useApp()
  const L = useLookups()
  const l = data.lessons.find((x) => x.id === id)
  const [sugg, setSugg] = useState<Suggestion[] | null>(null)
  const [showBad, setShowBad] = useState(false)

  useEffect(() => {
    if (!l) return
    setSugg(null)
    api
      .get<Suggestion[]>(`/api/lessons/${id}/suggest`)
      .then(setSugg)
      .catch(() => setSugg([]))
  }, [id, data])

  useEffect(() => {
    if (!l) onClose()
  }, [l, onClose])
  if (!l) return null

  const teacher = L.teachers.get(l.teacher_id ?? -1)
  const room = L.rooms.get(l.room_id ?? -1)
  const pair = data.settings.pairs.find((p) => p.n === l.pair)
  const mine = conflicts.filter((c) => c.lesson_ids.includes(l.id))

  async function act(fn: () => Promise<unknown>, msg: string) {
    try {
      await fn()
      await reload()
      toast(msg)
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }

  async function place(s: Suggestion) {
    if (s.status === 'bad' && !(await confirm(`${s.room}: ${s.issues.join('; ')}\n\nВсё равно поставить?`, 'Поставить'))) return
    act(() => api.post(`/api/lessons/${l!.id}/move`, { room_id: s.room_id }), `Поставлено в ${s.room}`)
  }

  const good = sugg?.filter((s) => s.status !== 'bad') ?? []
  const bad = sugg?.filter((s) => s.status === 'bad') ?? []

  return (
    <aside className="panel">
      <header>
        <div>
          <h2>{l.subject}</h2>
          <small>
            {data.dicts.lesson_kinds[l.kind]} · {DAY_SHORT[l.day]}, {l.pair} пара
            {pair && ` (${pair.start}–${pair.end})`} · {data.dicts.weeks[l.week].toLowerCase()}
          </small>
        </div>
        <button className="icon" onClick={onClose} aria-label="Закрыть">
          ✕
        </button>
      </header>

      <dl className="facts">
        <dt>Аудитория</dt>
        <dd>{room ? `${room.name} (корп. ${room.building}, ${room.capacity} мест)` : <b className="text-warn">не назначена</b>}</dd>
        <dt>Преподаватель</dt>
        <dd>{teacher?.name ?? '—'}</dd>
        <dt>Группы</dt>
        <dd>
          {L.groupNames(l) || '—'} <span className="muted">({L.lessonSize(l)} чел.)</span>
        </dd>
        <dt>Нужно</dt>
        <dd>
          {[...l.required_equipment.map((e) => L.eq.get(e) ?? e), l.min_computers ? `${l.min_computers} ПК` : '']
            .filter(Boolean)
            .join(', ') || '—'}
        </dd>
      </dl>

      <div className="row gap">
        <button
          onClick={() =>
            act(() => api.post(`/api/lessons/${l.id}/lock`, { locked: !l.locked }), l.locked ? 'Замок снят' : 'Закреплено')
          }
          title="Закреплённое занятие автораспределение не двигает"
        >
          {l.locked ? '🔓 Открепить' : '🔒 Закрепить'}
        </button>
        <button onClick={() => editLesson(l)}>✎ Изменить</button>
        {room && (
          <button onClick={() => act(() => api.post(`/api/lessons/${l.id}/move`, { clear_room: true }), 'Аудитория снята')}>
            Снять аудиторию
          </button>
        )}
      </div>

      {mine.length > 0 && (
        <section>
          <h3>Проблемы</h3>
          {mine.map((c, i) => (
            <div key={i} className={`issue ${c.severity}`}>
              {c.message}
            </div>
          ))}
        </section>
      )}

      <section>
        <h3>Подобрать аудиторию</h3>
        {!sugg && <p className="muted">Оцениваю…</p>}
        {sugg && !good.length && <p className="text-warn">Свободных подходящих аудиторий в это время нет.</p>}
        {good.map((s) => (
          <SuggestionRow key={s.room_id} s={s} current={s.room_id === l.room_id} onPlace={() => place(s)} />
        ))}
        {bad.length > 0 && (
          <button className="link" onClick={() => setShowBad(!showBad)}>
            {showBad ? 'Скрыть' : 'Показать'} неподходящие ({bad.length})
          </button>
        )}
        {showBad && bad.map((s) => <SuggestionRow key={s.room_id} s={s} current={s.room_id === l.room_id} onPlace={() => place(s)} />)}
      </section>
    </aside>
  )
}

function SuggestionRow({ s, current, onPlace }: { s: Suggestion; current: boolean; onPlace: () => void }) {
  return (
    <div className={`sugg ${s.status}`}>
      <div className="sugg-head">
        <span className={`dot ${s.status}`} />
        <b>{s.room}</b>
        <span className="muted">корп. {s.building}</span>
        {current ? <span className="pill">текущая</span> : <button className="small" onClick={onPlace}>Поставить</button>}
      </div>
      <ul>
        {s.issues.map((t) => (
          <li key={t} className="bad">✗ {t}</li>
        ))}
        {s.cons.map((t) => (
          <li key={t} className="warn">⚠ {t}</li>
        ))}
        {s.pros.map((t) => (
          <li key={t} className="ok">✓ {t}</li>
        ))}
      </ul>
    </div>
  )
}
