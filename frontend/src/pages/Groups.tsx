import { useState } from 'react'
import { api } from '../api'
import { useApp, useLookups } from '../context'
import type { Group } from '../types'
import { DataTable } from '../components/DataTable'
import { Field, Modal, SearchBox } from '../components/ui'

const EMPTY: Omit<Group, 'id'> = { name: '', course: 1, size: 25, home_building: '' }

export function GroupsPage() {
  const { data } = useApp()
  const [q, setQ] = useState('')
  const [edit, setEdit] = useState<Partial<Group> | null>(null)
  const count = (id: number) => data.lessons.filter((l) => l.group_ids.includes(id)).length
  const rows = data.groups.filter((g) => g.name.toLowerCase().includes(q.toLowerCase()))
  return (
    <div className="page">
      <div className="page-head">
        <h1>Группы</h1>
        <SearchBox value={q} onChange={setQ} />
        <button className="primary" onClick={() => setEdit({})}>
          ＋ Группа
        </button>
      </div>
      <DataTable
        rows={rows}
        onRowClick={setEdit}
        empty="Групп нет"
        columns={[
          { title: 'Группа', render: (g) => <b>{g.name}</b>, sort: (g) => g.name },
          { title: 'Курс', render: (g) => g.course, sort: (g) => g.course },
          { title: 'Студентов', render: (g) => g.size, sort: (g) => g.size },
          { title: 'Свой корпус', render: (g) => g.home_building, sort: (g) => g.home_building },
          { title: 'Пар в неделю', render: (g) => count(g.id), sort: (g) => count(g.id) },
        ]}
      />
      {edit && <GroupForm group={edit} onClose={() => setEdit(null)} />}
    </div>
  )
}

function GroupForm({ group, onClose }: { group: Partial<Group>; onClose: () => void }) {
  const { reload, toast, confirm } = useApp()
  const L = useLookups()
  const [f, setF] = useState({ ...EMPTY, ...group })
  const set = <K extends keyof Group>(k: K, v: Group[K]) => setF((s) => ({ ...s, [k]: v }))

  async function save() {
    try {
      const { id, ...body } = f as Group
      if (group.id) await api.put(`/api/groups/${group.id}`, body)
      else await api.post('/api/groups', body)
      await reload()
      toast('Сохранено')
      onClose()
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }

  async function remove() {
    if (!(await confirm(`Удалить группу ${f.name}?`, 'Удалить'))) return
    await api.del(`/api/groups/${group.id}`)
    await reload()
    onClose()
  }

  return (
    <Modal
      title={group.id ? `Группа ${group.name}` : 'Новая группа'}
      onClose={onClose}
      footer={
        <>
          {group.id && (
            <button className="danger" onClick={remove}>
              Удалить
            </button>
          )}
          <span className="spacer" />
          <button onClick={onClose}>Отмена</button>
          <button className="primary" onClick={save} disabled={!f.name.trim()}>
            Сохранить
          </button>
        </>
      }
    >
      <div className="form">
        <Field label="Название">
          <input value={f.name} onChange={(e) => set('name', e.target.value)} autoFocus />
        </Field>
        <Field label="Курс">
          <input type="number" min={1} value={f.course} onChange={(e) => set('course', Number(e.target.value))} />
        </Field>
        <Field label="Студентов">
          <input type="number" min={0} value={f.size} onChange={(e) => set('size', Number(e.target.value))} />
        </Field>
        <Field label="Свой корпус" hint="Солвер старается ставить пары группы сюда">
          <select value={f.home_building} onChange={(e) => set('home_building', e.target.value)}>
            <option value="">—</option>
            {L.buildings.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </Field>
      </div>
    </Modal>
  )
}
