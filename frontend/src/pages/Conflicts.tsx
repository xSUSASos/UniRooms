import { useApp } from '../context'
import { Empty } from '../components/ui'

const KIND_TITLE: Record<string, string> = {
  room: 'Две пары в одной аудитории',
  teacher: 'Преподаватель',
  group: 'Группа в двух местах',
  room_unfit: 'Аудитория не подходит',
  unassigned: 'Без аудитории',
  slot: 'Неверное время',
  data: 'Неполные данные',
  overload: 'Перегруженные дни',
}

export function ConflictsPage() {
  const { conflicts, openLesson, runSolve } = useApp()
  const groups = new Map<string, typeof conflicts>()
  for (const c of conflicts) groups.set(c.kind, [...(groups.get(c.kind) ?? []), c])
  const fixable = conflicts.some((c) => ['room', 'room_unfit', 'unassigned'].includes(c.kind))
  const timeFixable = conflicts.some((c) => ['teacher', 'group', 'overload'].includes(c.kind))

  return (
    <div className="page">
      <div className="page-head">
        <h1>Конфликты</h1>
        {fixable && (
          <button className="primary" onClick={() => runSolve('repair')}>
            🛠 Исправить аудитории автоматически
          </button>
        )}
        {timeFixable && (
          <button className="primary" onClick={() => runSolve('time-repair')}>
            🕒 Убрать накладки по времени
          </button>
        )}
      </div>
      <p className="muted">
        Проблемы с аудиториями исправляет «Исправить». Накладки преподавателей и групп по времени и перегруженные дни —
        «Убрать накладки»: система перенесёт минимум пар. Можно и вручную — перетащите карточку в сетке.
      </p>
      {!conflicts.length && <Empty>✅ Конфликтов нет</Empty>}
      {[...groups.entries()].map(([kind, items]) => (
        <section key={kind}>
          <h3>
            {KIND_TITLE[kind] ?? kind} <span className="muted">({items.length})</span>
          </h3>
          {items.map((c, i) => (
            <div key={i} className={`issue ${c.severity} clickable`} onClick={() => openLesson(c.lesson_ids[0])}>
              {c.severity === 'error' ? '⛔' : '⚠'} {c.message}
            </div>
          ))}
        </section>
      ))}
    </div>
  )
}
