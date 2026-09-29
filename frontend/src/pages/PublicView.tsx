import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { Pair } from '../types'

type Kind = 'group' | 'teacher' | 'room'

interface Meta {
  days: string[]
  pairs: Pair[]
  groups: { id: number; name: string; course: number; faculty: string }[]
  teachers: { id: number; name: string }[]
  rooms: { id: number; name: string; building: string }[]
  version: number
}

interface PubLesson {
  id: number
  day: number
  pair: number
  week: 'all' | 'odd' | 'even'
  subject: string
  kind: string
  teacher: string
  groups: string
  room: string
  building: string
  online: boolean
}

const KIND_TITLE: Record<Kind, string> = { group: 'Группа', teacher: 'Преподаватель', room: 'Аудитория' }
const WEEK_MARK = { all: '', odd: 'числитель', even: 'знаменатель' }

function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key)
    return v ? (JSON.parse(v) as T) : fallback
  } catch {
    return fallback
  }
}

function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* storage unavailable */
  }
}

/** Read-only schedule for teachers and students: /view */
export function PublicView() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [kind, setKind] = useState<Kind>(() => load('ur.view.kind', 'group'))
  const [id, setId] = useState<number | null>(() => load('ur.view.id', null))
  const [week, setWeek] = useState<'both' | 'odd' | 'even'>('both')
  const [lessons, setLessons] = useState<PubLesson[]>([])
  const [q, setQ] = useState('')

  useEffect(() => {
    document.title = 'Расписание — UniRooms'
    api
      .get<Meta>('/api/public/meta')
      .then(setMeta)
      .catch((e) => setError((e as Error).message))
  }, [])

  const options = useMemo(() => {
    if (!meta) return []
    const list =
      kind === 'group'
        ? meta.groups.map((g) => ({ id: g.id, label: g.name, sub: `${g.faculty ? g.faculty + ', ' : ''}${g.course} курс` }))
        : kind === 'teacher'
          ? meta.teachers.map((t) => ({ id: t.id, label: t.name, sub: '' }))
          : meta.rooms.map((r) => ({ id: r.id, label: r.name, sub: `корпус ${r.building}` }))
    return list.filter((o) => !q || o.label.toLowerCase().includes(q.toLowerCase()))
  }, [meta, kind, q])

  useEffect(() => {
    save('ur.view.kind', kind)
    save('ur.view.id', id)
    if (id === null) return
    let version = -1
    const fetchIt = () =>
      api
        .get<{ lessons: PubLesson[]; version: number }>(`/api/public/schedule?kind=${kind}&id=${id}`)
        .then((r) => {
          if (r.version !== version) {
            version = r.version
            setLessons(r.lessons)
          }
        })
        .catch(() => undefined)
    fetchIt()
    const t = setInterval(fetchIt, 30000)
    return () => clearInterval(t)
  }, [kind, id])

  if (error) return <div className="loading">Не удалось загрузить расписание: {error}</div>
  if (!meta) return <div className="loading">Загрузка…</div>

  const selected = options.find((o) => o.id === id) ?? null
  const shown = lessons.filter((l) => week === 'both' || l.week === 'all' || l.week === week)
  const cell = (d: number, p: number) => shown.filter((l) => l.day === d && l.pair === p)
  const usedPairs = meta.pairs.filter((p) => shown.some((l) => l.pair === p.n))
  const detail = (l: PubLesson) =>
    [kind !== 'room' && (l.online ? 'онлайн' : l.room && `ауд. ${l.room}`), kind !== 'teacher' && l.teacher,
      kind !== 'group' && l.groups]
      .filter(Boolean)
      .join(' · ')

  return (
    <div className="public">
      <header className="public-head">
        <div className="brand">
          <span className="logo">UR</span>
          <div>
            <b>Расписание занятий</b>
            <small>обновляется автоматически</small>
          </div>
        </div>
        <div className="tabs">
          {(Object.keys(KIND_TITLE) as Kind[]).map((k) => (
            <button
              key={k}
              className={`tab ${k === kind ? 'active' : ''}`}
              onClick={() => {
                setKind(k)
                setId(null)
                setLessons([])
              }}
            >
              {KIND_TITLE[k]}
            </button>
          ))}
        </div>
        <input
          className="search"
          type="search"
          placeholder={`Найти: ${KIND_TITLE[kind].toLowerCase()}…`}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select value={id ?? ''} onChange={(e) => setId(e.target.value ? Number(e.target.value) : null)}>
          <option value="">— выберите —</option>
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
              {o.sub ? ` (${o.sub})` : ''}
            </option>
          ))}
        </select>
        <select value={week} onChange={(e) => setWeek(e.target.value as typeof week)}>
          <option value="both">Обе недели</option>
          <option value="odd">Числитель</option>
          <option value="even">Знаменатель</option>
        </select>
      </header>

      {!selected && <div className="empty">Выберите {KIND_TITLE[kind].toLowerCase()}, чтобы увидеть расписание</div>}
      {selected && !shown.length && <div className="empty">Занятий нет</div>}

      {selected && shown.length > 0 && (
        <>
          <h2 className="public-title">
            {KIND_TITLE[kind]}: {selected.label}
          </h2>
          {/* wide screens: week table */}
          <div className="table-wrap public-table">
            <table className="table">
              <thead>
                <tr>
                  <th>Пара</th>
                  {meta.days.map((d) => (
                    <th key={d}>{d}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {usedPairs.map((p) => (
                  <tr key={p.n}>
                    <td className="pair-cell">
                      <b>{p.n}</b>
                      <small>
                        {p.start}–{p.end}
                      </small>
                    </td>
                    {meta.days.map((_, d) => (
                      <td key={d}>
                        {cell(d, p.n).map((l) => (
                          <div key={l.id} className="pub-lesson">
                            <b>{l.subject}</b>
                            <small>
                              {l.kind}
                              {l.week !== 'all' && ` · ${WEEK_MARK[l.week]}`}
                            </small>
                            <small>{detail(l)}</small>
                          </div>
                        ))}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* phones: list by day */}
          <div className="public-days">
            {meta.days.map((d, di) => {
              const items = shown.filter((l) => l.day === di)
              if (!items.length) return null
              return (
                <section key={d} className="box">
                  <h3>{d}</h3>
                  {items.map((l) => {
                    const p = meta.pairs.find((x) => x.n === l.pair)
                    return (
                      <div key={l.id} className="pub-row">
                        <div className="pub-time">
                          <b>{l.pair}</b>
                          <small>{p && `${p.start}–${p.end}`}</small>
                        </div>
                        <div>
                          <b>{l.subject}</b>
                          <small>
                            {l.kind}
                            {l.week !== 'all' && ` · ${WEEK_MARK[l.week]}`}
                          </small>
                          <small>{detail(l)}</small>
                        </div>
                      </div>
                    )
                  })}
                </section>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
