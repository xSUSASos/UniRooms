import { useState } from 'react'
import { api } from '../api'
import { DAY_SHORT, useApp, useLookups } from '../context'
import type { Room } from '../types'
import { DataTable } from '../components/DataTable'
import { Checks, Field, Modal, SearchBox } from '../components/ui'
import { BlockRoomDialog } from '../components/BlockRoomDialog'
import { Plus } from 'lucide-react'
import { Accessibility, Ban } from 'lucide-react'

const EMPTY: Omit<Room, 'id'> = {
  name: '',
  building: '',
  floor: 1,
  capacity: 30,
  kind: 'practice',
  computers: 0,
  equipment: [],
  accessible: false,
  active: true,
  notes: '',
}

export function RoomsPage() {
  const { data } = useApp()
  const L = useLookups()
  const [q, setQ] = useState('')
  const [edit, setEdit] = useState<Partial<Room> | null>(null)
  const load = (id: number) => data.lessons.filter((l) => l.room_id === id).length
  const slots = data.settings.days * data.settings.pairs.length
  const rows = data.rooms.filter((r) =>
    `${r.name} ${r.building} ${r.notes} ${r.equipment.map((e) => L.eq.get(e)).join(' ')}`.toLowerCase().includes(q.toLowerCase()),
  )

  return (
    <div className="page">
      <div className="page-head">
        <h1>Аудитории</h1>
        <SearchBox value={q} onChange={setQ} placeholder="Номер, корпус, оборудование…" />
        <button className="primary" onClick={() => setEdit({})}>
          <Plus size={15} />
          Аудитория
        </button>
      </div>
      <DataTable
        rows={rows}
        onRowClick={setEdit}
        empty="Аудиторий нет. Добавьте вручную или импортируйте из Excel (Настройки)."
        columns={[
          { title: 'Номер', render: (r) => <b>{r.name}</b>, sort: (r) => r.name },
          { title: 'Корпус', render: (r) => r.building, sort: (r) => r.building },
          { title: 'Этаж', render: (r) => r.floor, sort: (r) => r.floor },
          { title: 'Мест', render: (r) => r.capacity, sort: (r) => r.capacity },
          { title: 'Тип', render: (r) => data.dicts.room_kinds[r.kind], sort: (r) => r.kind },
          { title: 'ПК', render: (r) => r.computers || '', sort: (r) => r.computers },
          {
            title: 'Оборудование',
            render: (r) => (
              <span className="chips">
                {r.equipment.map((e) => (
                  <span key={e} className="pill">
                    {L.eq.get(e) ?? e}
                  </span>
                ))}
              </span>
            ),
          },
          {
            title: 'Статус',
            render: (r) => {
              const blocks = data.blocks.filter((b) => b.room_id === r.id)
              return (
                <>
                  {!r.active && <span className="pill red">выкл.</span>}
                  {blocks.length > 0 && <span className="pill yellow">
                      <Ban size={12} />
                      {blocks.length}
                    </span>}
                  {r.accessible && <Accessibility size={15} className="muted" aria-label="Доступная среда" />}
                </>
              )
            },
          },
          {
            title: 'Загрузка',
            render: (r) => {
              const pct = Math.round((load(r.id) / slots) * 100)
              return (
                <span className="meter" title={`${load(r.id)} занятий из ${slots} слотов`}>
                  <span className="track">
                    <span className="fill" style={{ width: `${Math.min(100, pct)}%` }} />
                  </span>
                  <em>{pct}%</em>
                </span>
              )
            },
            sort: (r) => load(r.id),
          },
        ]}
      />
      {edit && <RoomForm room={edit} onClose={() => setEdit(null)} />}
    </div>
  )
}

function RoomForm({ room, onClose }: { room: Partial<Room>; onClose: () => void }) {
  const { data, reload, toast, confirm } = useApp()
  const L = useLookups()
  const [f, setF] = useState({ ...EMPTY, ...room })
  const [blocking, setBlocking] = useState(false)
  const set = <K extends keyof Room>(k: K, v: Room[K]) => setF((s) => ({ ...s, [k]: v }))
  const blocks = data.blocks.filter((b) => b.room_id === room.id)

  async function save() {
    try {
      const { id, ...body } = f as Room
      if (room.id) await api.put(`/api/rooms/${room.id}`, body)
      else await api.post('/api/rooms', body)
      await reload()
      toast('Сохранено')
      onClose()
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }

  async function remove() {
    const n = data.lessons.filter((l) => l.room_id === room.id).length
    if (!(await confirm(`Удалить аудиторию ${f.name}?${n ? `\n${n} занятий останутся без аудитории.` : ''}`, 'Удалить'))) return
    await api.del(`/api/rooms/${room.id}`)
    await reload()
    toast('Удалено')
    onClose()
  }

  return (
    <Modal
      title={room.id ? `Аудитория ${room.name}` : 'Новая аудитория'}
      onClose={onClose}
      wide
      footer={
        <>
          {room.id && (
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
        <Field label="Номер">
          <input value={f.name} onChange={(e) => set('name', e.target.value)} autoFocus />
        </Field>
        <Field label="Корпус">
          <input list="buildings" value={f.building} onChange={(e) => set('building', e.target.value)} />
          <datalist id="buildings">
            {L.buildings.map((b) => (
              <option key={b} value={b} />
            ))}
          </datalist>
        </Field>
        <Field label="Этаж">
          <input type="number" value={f.floor} onChange={(e) => set('floor', Number(e.target.value))} />
        </Field>
        <Field label="Мест">
          <input type="number" min={0} value={f.capacity} onChange={(e) => set('capacity', Number(e.target.value))} />
        </Field>
        <Field label="Тип">
          <select value={f.kind} onChange={(e) => set('kind', e.target.value)}>
            {Object.entries(data.dicts.room_kinds).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Компьютеров">
          <input type="number" min={0} value={f.computers} onChange={(e) => set('computers', Number(e.target.value))} />
        </Field>
        <Field label="Оборудование" wide hint="Список оборудования редактируется в Настройках">
          <Checks
            options={data.equipment.map((e) => ({ value: e.code, label: e.name }))}
            value={f.equipment}
            onChange={(v) => set('equipment', v as string[])}
          />
        </Field>
        <Field label="Доступность">
          <label className="switch">
            <input type="checkbox" checked={f.accessible} onChange={(e) => set('accessible', e.target.checked)} /> доступная среда
          </label>
        </Field>
        <Field label="Использовать">
          <label className="switch">
            <input type="checkbox" checked={f.active} onChange={(e) => set('active', e.target.checked)} /> аудитория активна
          </label>
        </Field>
        <Field label="Примечание" wide>
          <input value={f.notes} onChange={(e) => set('notes', e.target.value)} />
        </Field>
      </div>
      {room.id && (
        <section>
          <h3>Закрытия (ремонт, мероприятия)</h3>
          {!blocks.length && <p className="muted">Аудитория открыта всегда.</p>}
          {blocks.map((b) => (
            <div key={b.id} className="issue warning">
              <Ban size={15} />
              <span className="grow">
              {b.day === null ? 'все дни' : DAY_SHORT[b.day]}, {b.pair === null ? 'все пары' : `${b.pair} пара`} —{' '}
              {b.reason || 'без причины'}
              </span>
              <button
                className="small"
                onClick={async () => {
                  await api.del(`/api/blocks/${b.id}`)
                  await reload()
                  toast('Закрытие снято')
                }}
              >
                Снять
              </button>
            </div>
          ))}
          <button onClick={() => setBlocking(true)}>
            <Plus size={15} />
            Закрыть на время
          </button>
        </section>
      )}
      {blocking && <BlockRoomDialog day={0} roomId={room.id} onClose={() => setBlocking(false)} />}
    </Modal>
  )
}
