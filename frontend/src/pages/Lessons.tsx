import { useState } from 'react'
import { DAY_SHORT, useApp, useLookups } from '../context'
import { DataTable } from '../components/DataTable'
import { SearchBox } from '../components/ui'
import { Plus } from 'lucide-react'
import { Lock, TriangleAlert } from 'lucide-react'

export function LessonsPage() {
  const { data, editLesson, conflicts } = useApp()
  const L = useLookups()
  const [q, setQ] = useState('')
  const [group, setGroup] = useState('')
  const [teacher, setTeacher] = useState('')
  const [onlyProblems, setOnlyProblems] = useState(false)
  const problems = new Set(conflicts.flatMap((c) => c.lesson_ids))

  const rows = data.lessons.filter(
    (l) =>
      (!group || l.group_ids.includes(Number(group))) &&
      (!teacher || l.teacher_id === Number(teacher)) &&
      (!onlyProblems || problems.has(l.id)) &&
      `${l.subject} ${L.groupNames(l)} ${L.teachers.get(l.teacher_id ?? -1)?.name ?? ''}`.toLowerCase().includes(q.toLowerCase()),
  )

  return (
    <div className="page">
      <div className="page-head">
        <h1>Занятия</h1>
        <SearchBox value={q} onChange={setQ} />
        <select value={group} onChange={(e) => setGroup(e.target.value)}>
          <option value="">Все группы</option>
          {data.groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
        <select value={teacher} onChange={(e) => setTeacher(e.target.value)}>
          <option value="">Все преподаватели</option>
          {data.teachers.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
        <label className="switch">
          <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} /> только с проблемами
        </label>
        <button className="primary" onClick={() => editLesson({})}>
          <Plus size={15} />
          Занятие
        </button>
      </div>
      <p className="muted">Показано: {rows.length} из {data.lessons.length}</p>
      <DataTable
        rows={rows}
        onRowClick={editLesson}
        empty="Занятий нет"
        columns={[
          { title: 'Когда', render: (l) => `${DAY_SHORT[l.day]} ${l.pair}`, sort: (l) => l.day * 100 + l.pair },
          { title: 'Неделя', render: (l) => (l.week === 'all' ? '' : data.dicts.weeks[l.week]), sort: (l) => l.week },
          { title: 'Дисциплина', render: (l) => <b>{l.subject}</b>, sort: (l) => l.subject },
          { title: 'Тип', render: (l) => data.dicts.lesson_kinds[l.kind], sort: (l) => l.kind },
          { title: 'Преподаватель', render: (l) => L.teachers.get(l.teacher_id ?? -1)?.name ?? '—', sort: (l) => L.teachers.get(l.teacher_id ?? -1)?.name ?? '' },
          { title: 'Группы', render: (l) => `${L.groupNames(l)} (${L.lessonSize(l)})` },
          {
            title: 'Аудитория',
            render: (l) => (
              <>
                {L.rooms.get(l.room_id ?? -1)?.name ?? <span className="text-warn">—</span>} {l.locked && <Lock size={13} className="muted" />}{' '}
                {problems.has(l.id) && <TriangleAlert size={14} className="text-warn" aria-label="Есть проблемы" />}
              </>
            ),
            sort: (l) => L.rooms.get(l.room_id ?? -1)?.name ?? '',
          },
        ]}
      />
    </div>
  )
}
