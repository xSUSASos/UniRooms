import { useMemo, useState, type DragEvent } from 'react'
import { api } from '../api'
import { DAY_SHORT, shortName, useApp, useLookups, type SolveMode } from '../context'
import type { Cell, GridEval, Lesson, Week } from '../types'
import { SearchBox } from '../components/ui'
import { BlockRoomDialog } from '../components/BlockRoomDialog'

type View = 'rooms' | 'groups' | 'teachers'

interface Row {
  key: number | 'none'
  title: string
  sub: string
  tags?: string[]
  lessons: (pair: number) => Lesson[]
  blocked?: (pair: number) => string | null
  accepts: (l: Lesson) => boolean
}

const KIND_ICON: Record<string, string> = { lecture: '🎓', practice: '✏️', lab: '🧪', computer: '💻', shared: '🏟' }

export function SchedulePage() {
  const { data, conflicts, reload, toast, confirm, openLesson, editLesson, runSolve } = useApp()
  const L = useLookups()
  const [day, setDay] = useState(0)
  const [view, setView] = useState<View>('rooms')
  const [building, setBuilding] = useState('')
  const [faculty, setFaculty] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [week, setWeek] = useState<Week>('all')
  const [q, setQ] = useState('')
  const [drag, setDrag] = useState<{ id: number; ev: GridEval | null } | null>(null)
  const [over, setOver] = useState<string | null>(null)
  const [blockOpen, setBlockOpen] = useState(false)

  const pairs = data.settings.pairs
  const days = Array.from({ length: data.settings.days }, (_, i) => i)
  const errorIds = useMemo(
    () => new Set(conflicts.filter((c) => c.severity === 'error').flatMap((c) => c.lesson_ids)),
    [conflicts],
  )

  const query = q.trim().toLowerCase()
  const matches = (l: Lesson) =>
    !query ||
    [l.subject, L.groupNames(l), L.teachers.get(l.teacher_id ?? -1)?.name ?? '', L.rooms.get(l.room_id ?? -1)?.name ?? '']
      .join(' ')
      .toLowerCase()
      .includes(query)
  const dayLessons = useMemo(
    () => data.lessons.filter((l) => l.day === day && (week === 'all' || l.week === 'all' || l.week === week)),
    [data.lessons, day, week],
  )
  // lessons by (room | group | teacher, pair) — thousands of rows must not rescan all lessons per cell
  const index = useMemo(() => {
    const byRoom = new Map<string, Lesson[]>()
    const byGroup = new Map<string, Lesson[]>()
    const byTeacher = new Map<string, Lesson[]>()
    const push = (m: Map<string, Lesson[]>, k: string, l: Lesson) => {
      const list = m.get(k)
      if (list) list.push(l)
      else m.set(k, [l])
    }
    for (const l of dayLessons) {
      if (!l.online) push(byRoom, `${l.room_id ?? 'none'}:${l.pair}`, l)
      for (const g of l.group_ids) push(byGroup, `${g}:${l.pair}`, l)
      if (l.teacher_id !== null) push(byTeacher, `${l.teacher_id}:${l.pair}`, l)
    }
    return { byRoom, byGroup, byTeacher }
  }, [dayLessons])
  const cellOf = (m: Map<string, Lesson[]>, key: number | string) => (p: number) => m.get(`${key}:${p}`) ?? []

  const blockReason = (roomId: number, p: number) => {
    const b = data.blocks.find(
      (b) => b.room_id === roomId && (b.day === null || b.day === day) && (b.pair === null || b.pair === p),
    )
    return b ? b.reason || 'закрыта' : null
  }

  let rows: Row[] = []
  if (view === 'rooms') {
    const unassigned = dayLessons.filter((l) => l.room_id === null && !l.online)
    if (unassigned.length) {
      rows.push({
        key: 'none',
        title: 'Без аудитории',
        sub: `${unassigned.length} занятий`,
        lessons: cellOf(index.byRoom, 'none'),
        accepts: () => true,
      })
    }
    rows.push(
      ...data.rooms
        .filter((r) => !building || r.building === building)
        .map<Row>((r) => ({
          key: r.id,
          title: `${KIND_ICON[r.kind] ?? ''} ${r.name}`,
          sub: `${r.capacity} мест${r.computers ? ` · ${r.computers} ПК` : ''}${r.active ? '' : ' · выкл.'}`,
          tags: r.equipment.map((e) => L.eq.get(e) ?? e),
          lessons: cellOf(index.byRoom, r.id),
          blocked: (p) => blockReason(r.id, p) ?? (r.active ? null : 'выключена'),
          accepts: () => true,
        })),
    )
  } else if (view === 'groups') {
    rows = data.groups
      .filter((g) => (!building || g.home_building === building) && (!faculty || g.faculty === faculty))
      .map((g) => ({
        key: g.id,
        title: g.name,
        sub: `${g.size} чел. · ${g.course} курс${g.faculty ? ` · ${g.faculty}` : ''}`,
        lessons: cellOf(index.byGroup, g.id),
        accepts: (l) => l.group_ids.includes(g.id),
      }))
  } else {
    rows = data.teachers.map((t) => ({
      key: t.id,
      title: t.name,
      sub: t.department,
      lessons: cellOf(index.byTeacher, t.id),
      accepts: (l) => l.teacher_id === t.id,
    }))
  }
  if (query) {
    rows = rows.filter(
      (r) => r.title.toLowerCase().includes(query) || pairs.some((p) => r.lessons(p.n).some(matches)),
    )
  }

  if (view !== 'rooms') rows = rows.filter((r) => query || pairs.some((p) => r.lessons(p.n).length))
  const totalRows = rows.length
  const ROW_LIMIT = 150
  if (!showAll && !query) rows = rows.slice(0, ROW_LIMIT)

  const dragged = drag ? data.lessons.find((l) => l.id === drag.id) : undefined

  function cellStatus(row: Row, pair: number): Cell | undefined {
    if (!drag || !dragged || !drag.ev) return undefined
    if (!row.accepts(dragged)) return undefined
    if (view === 'rooms' && row.key !== 'none') return drag.ev.cells[row.key as number]?.[pair]
    return drag.ev.pairs[pair]
  }

  function startDrag(e: DragEvent, l: Lesson) {
    e.dataTransfer.setData('text/plain', String(l.id))
    e.dataTransfer.effectAllowed = 'move'
    setDrag({ id: l.id, ev: null })
    api
      .get<GridEval>(`/api/lessons/${l.id}/evaluate?day=${day}`)
      .then((ev) => setDrag((d) => (d && d.id === l.id ? { ...d, ev } : d)))
      .catch(() => undefined)
  }

  async function move(l: Lesson, body: Record<string, unknown>, status?: Cell) {
    if (status?.s === 'bad') {
      const ok = await confirm(`Здесь есть нарушения:\n• ${status.r.join('\n• ')}\n\nВсё равно переместить?`, 'Переместить')
      if (!ok) return
    }
    try {
      await api.post(`/api/lessons/${l.id}/move`, body)
      await reload()
      toast(`«${l.subject}» перемещено`)
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }

  async function dropOnCell(row: Row, pair: number) {
    const l = dragged
    const status = cellStatus(row, pair)
    setDrag(null)
    setOver(null)
    if (!l || !row.accepts(l)) return
    const body: Record<string, unknown> = { day, pair }
    if (view === 'rooms') {
      if (row.key === 'none') body.clear_room = true
      else body.room_id = row.key
    }
    await move(l, body, status)
  }

  async function dropOnDay(d: number) {
    const l = dragged
    setDrag(null)
    if (!l || d === l.day) return
    const ev = await api.get<GridEval>(`/api/lessons/${l.id}/evaluate?day=${d}`)
    const status = l.room_id !== null ? ev.cells[l.room_id]?.[l.pair] : ev.pairs[l.pair]
    await move(l, { day: d }, status)
  }

  const total = dayLessons.length
  const noRoom = dayLessons.filter((l) => l.room_id === null).length

  return (
    <div className="page schedule">
      <div className="toolbar">
        <div className="tabs days">
          {days.map((d) => (
            <button
              key={d}
              className={`tab ${d === day ? 'active' : ''} ${drag ? 'droppable' : ''}`}
              onClick={() => setDay(d)}
              onDragOver={(e) => drag && e.preventDefault()}
              onDrop={() => dropOnDay(d)}
              title={drag ? 'Перенести на этот день (та же пара)' : data.dicts.days[d]}
            >
              {DAY_SHORT[d]}
              <small>{data.lessons.filter((l) => l.day === d).length}</small>
            </button>
          ))}
        </div>
        <div className="tabs">
          {(['rooms', 'groups', 'teachers'] as View[]).map((v) => (
            <button key={v} className={`tab ${v === view ? 'active' : ''}`} onClick={() => setView(v)}>
              {{ rooms: 'Аудитории', groups: 'Группы', teachers: 'Преподаватели' }[v]}
            </button>
          ))}
        </div>
        {view === 'groups' && L.faculties.length > 0 && (
          <select value={faculty} onChange={(e) => setFaculty(e.target.value)} title="Факультет">
            <option value="">Все факультеты</option>
            {L.faculties.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        )}
        {view === 'rooms' && (
          <select value={building} onChange={(e) => setBuilding(e.target.value)} title="Корпус">
            <option value="">Все корпуса</option>
            {L.buildings.map((b) => (
              <option key={b} value={b}>
                Корпус {b}
              </option>
            ))}
          </select>
        )}
        <select value={week} onChange={(e) => setWeek(e.target.value as Week)} title="Неделя">
          <option value="all">Обе недели</option>
          <option value="odd">Числитель</option>
          <option value="even">Знаменатель</option>
        </select>
        <SearchBox value={q} onChange={setQ} placeholder="Поиск: предмет, группа, ФИО…" />
      </div>

      <div className="toolbar actions">
        <button className="primary" onClick={() => runSolve('full')} title="Подобрать аудитории всем незакреплённым занятиям заново">
          ⚡ Распределить всё
        </button>
        <button onClick={() => runSolve('repair')} title="Исправить только проблемные занятия, остальное не трогать">
          🛠 Исправить
        </button>
        <TimeMenu onPick={runSolve} faculties={L.faculties} />
        <button onClick={() => setBlockOpen(true)}>🚧 Закрыть аудиторию</button>
        <button onClick={() => editLesson({ day, pair: pairs[0]?.n ?? 1 })}>＋ Занятие</button>
        <a className="button" href="/api/export/schedule.xlsx" download>
          ⬇ Excel
        </a>
        <span className="stats">
          {total} занятий · {noRoom ? <b className="text-warn">{noRoom} без аудитории</b> : 'все с аудиториями'}
        </span>
      </div>

      {drag && (
        <div className="legend">
          <span className="lg ok" /> подходит <span className="lg warn" /> с компромиссами <span className="lg bad" /> нельзя
          (наведите — причина) · перетащите на вкладку дня, чтобы сменить день
          {!drag.ev && <em> · оцениваю варианты…</em>}
        </div>
      )}

      <div className="grid-wrap">
        <table className="grid">
          <thead>
            <tr>
              <th className="corner">{{ rooms: 'Аудитория', groups: 'Группа', teachers: 'Преподаватель' }[view]}</th>
              {pairs.map((p) => (
                <th key={p.n}>
                  {p.n} пара
                  <small>
                    {p.start}–{p.end}
                  </small>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className={row.key === 'none' ? 'unassigned-row' : ''}>
                <th className="rowhead">
                  <b>{row.title}</b>
                  <small>{row.sub}</small>
                  {row.tags && row.tags.length > 0 && <small className="tags">{row.tags.join(' · ')}</small>}
                </th>
                {pairs.map((p) => {
                  const st = cellStatus(row, p.n)
                  const blocked = row.blocked?.(p.n)
                  const id = `${row.key}:${p.n}`
                  const items = row.lessons(p.n)
                  return (
                    <td
                      key={p.n}
                      className={[
                        'cell',
                        st ? `st-${st.s}` : '',
                        blocked ? 'blocked' : '',
                        over === id ? 'over' : '',
                      ].join(' ')}
                      title={st ? st.r.join('\n') || 'Подходит' : blocked ? `Закрыта: ${blocked}` : undefined}
                      onDragOver={(e) => {
                        if (drag && dragged && row.accepts(dragged)) {
                          e.preventDefault()
                          if (over !== id) setOver(id)
                        }
                      }}
                      onDragLeave={() => over === id && setOver(null)}
                      onDrop={() => dropOnCell(row, p.n)}
                      onDoubleClick={() =>
                        !items.length &&
                        editLesson({
                          day,
                          pair: p.n,
                          room_id: view === 'rooms' && row.key !== 'none' ? (row.key as number) : null,
                          group_ids: view === 'groups' ? [row.key as number] : [],
                          teacher_id: view === 'teachers' ? (row.key as number) : null,
                        })
                      }
                    >
                      {blocked && !items.length && <span className="blocked-label">🚧 {blocked}</span>}
                      {items.map((l) => (
                        <LessonCard
                          key={l.id}
                          l={l}
                          view={view}
                          dim={!!query && !matches(l)}
                          error={errorIds.has(l.id)}
                          dragging={drag?.id === l.id}
                          onDragStart={(e) => startDrag(e, l)}
                          onDragEnd={() => {
                            setDrag(null)
                            setOver(null)
                          }}
                          onClick={() => openLesson(l.id)}
                        />
                      ))}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <div className="empty">Ничего не найдено</div>}
        {rows.length < totalRows && (
          <div className="empty">
            Показано {rows.length} из {totalRows}. Сузьте выбор фильтром или поиском, или{' '}
            <button className="link" onClick={() => setShowAll(true)}>
              покажите все
            </button>{' '}
            (может работать медленно).
          </div>
        )}
      </div>
      {blockOpen && <BlockRoomDialog day={day} onClose={() => setBlockOpen(false)} />}
    </div>
  )
}

function TimeMenu({ onPick, faculties }: { onPick: (m: SolveMode, faculty?: string) => void; faculties: string[] }) {
  const [open, setOpen] = useState(false)
  const [faculty, setFaculty] = useState('')
  const pick = (m: 'time-repair' | 'time-full') => {
    setOpen(false)
    onPick(m, m === 'time-full' ? faculty : undefined)
  }
  return (
    <span className="menu-wrap">
      <button onClick={() => setOpen(!open)} title="Автоматический подбор дня и пары">
        🕒 Время ▾
      </button>
      {open && (
        <div className="menu" onMouseLeave={() => setOpen(false)}>
          <button onClick={() => pick('time-repair')}>
            <b>Убрать накладки</b>
            <small>переносит минимум пар, чтобы у групп и преподавателей не было накладок</small>
          </button>
          <button onClick={() => pick('time-full')}>
            <b>Составить заново</b>
            <small>все незакреплённые пары: без окон, без перегрузки дней, с учётом пожеланий</small>
          </button>
          {faculties.length > 0 && (
            <label className="menu-field">
              для факультета:
              <select value={faculty} onChange={(e) => setFaculty(e.target.value)}>
                <option value="">все (долго для большого вуза)</option>
                {faculties.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}
    </span>
  )
}

function LessonCard(props: {
  l: Lesson
  view: View
  dim: boolean
  error: boolean
  dragging: boolean
  onDragStart: (e: DragEvent) => void
  onDragEnd: () => void
  onClick: () => void
}) {
  const { data } = useApp()
  const L = useLookups()
  const { l, view } = props
  const teacher = L.teachers.get(l.teacher_id ?? -1)
  const room = L.rooms.get(l.room_id ?? -1)
  const parts =
    view === 'rooms'
      ? [L.groupNames(l), teacher && shortName(teacher.name)]
      : view === 'groups'
        ? [l.online ? 'онлайн' : room?.name ?? 'нет ауд.', teacher && shortName(teacher.name)]
        : [l.online ? 'онлайн' : room?.name ?? 'нет ауд.', L.groupNames(l)]
  return (
    <div
      className={[
        'card',
        `k-${l.kind}`,
        props.error ? 'err' : '',
        l.locked ? 'locked' : '',
        props.dim ? 'dim' : '',
        props.dragging ? 'dragging' : '',
        !l.room_id ? 'noroom' : '',
      ].join(' ')}
      draggable={!l.locked}
      onDragStart={props.onDragStart}
      onDragEnd={props.onDragEnd}
      onClick={(e) => {
        e.stopPropagation()
        props.onClick()
      }}
      title={`${l.subject} — ${data.dicts.lesson_kinds[l.kind]}${l.locked ? '\n🔒 закреплено (снимите замок, чтобы двигать)' : ''}`}
    >
      <div className="card-top">
        <b>{l.subject}</b>
        {l.week !== 'all' && <span className="wk">{l.week === 'odd' ? 'Ч' : 'З'}</span>}
        {l.online && <span title="онлайн">💻</span>}
        {l.locked ? <span>🔒</span> : l.fixed_time && <span title="время закреплено">📌</span>}
      </div>
      <div className="card-sub">{parts.filter(Boolean).join(' · ')}</div>
    </div>
  )
}
