import { useState } from 'react'
import { api } from '../api'
import { DAY_SHORT, useApp, useLookups } from '../context'
import type { Pref, Teacher } from '../types'
import { DataTable } from '../components/DataTable'
import { Field, Modal, SearchBox } from '../components/ui'

const EMPTY: Omit<Teacher, 'id'> = { name: '', department: '', needs_accessible: false, unavailable: [], preferences: [] }

const PREF_KINDS: Record<Pref['kind'], string> = {
  building: 'Корпус',
  room: 'Аудитория',
  equipment: 'Оборудование',
  max_floor: 'Этаж не выше',
}

export function prefLabel(p: Pref, eq: Map<string, string>) {
  const value = p.kind === 'equipment' ? (p.value === 'computers' ? 'компьютеры' : eq.get(String(p.value)) ?? p.value) : p.value
  const head = PREF_KINDS[p.kind].toLowerCase()
  return `${p.mode === 'avoid' && p.kind !== 'max_floor' ? 'не ' : ''}${head} ${value}`
}

export function TeachersPage() {
  const { data } = useApp()
  const L = useLookups()
  const [q, setQ] = useState('')
  const [edit, setEdit] = useState<Partial<Teacher> | null>(null)
  const count = (id: number) => data.lessons.filter((l) => l.teacher_id === id).length
  const rows = data.teachers.filter((t) => `${t.name} ${t.department}`.toLowerCase().includes(q.toLowerCase()))
  return (
    <div className="page">
      <div className="page-head">
        <h1>Преподаватели</h1>
        <SearchBox value={q} onChange={setQ} placeholder="ФИО, кафедра…" />
        <button className="primary" onClick={() => setEdit({})}>
          ＋ Преподаватель
        </button>
      </div>
      <DataTable
        rows={rows}
        onRowClick={setEdit}
        empty="Преподавателей нет"
        columns={[
          { title: 'ФИО', render: (t) => <b>{t.name}</b>, sort: (t) => t.name },
          { title: 'Кафедра', render: (t) => t.department, sort: (t) => t.department },
          { title: 'Пар в неделю', render: (t) => count(t.id), sort: (t) => count(t.id) },
          {
            title: 'Пожелания',
            render: (t) => (
              <span className="chips">
                {t.needs_accessible && <span className="pill">♿ доступная среда</span>}
                {t.preferences.map((p, i) => (
                  <span key={i} className={`pill ${p.mode === 'avoid' ? 'red' : 'green'}`} title={`важность ${p.weight}/10`}>
                    {prefLabel(p, L.eq)}
                  </span>
                ))}
                {t.unavailable.length > 0 && <span className="pill yellow">недоступен: {t.unavailable.length} пар</span>}
              </span>
            ),
          },
        ]}
      />
      {edit && <TeacherForm teacher={edit} onClose={() => setEdit(null)} />}
    </div>
  )
}

function TeacherForm({ teacher, onClose }: { teacher: Partial<Teacher>; onClose: () => void }) {
  const { data, reload, toast, confirm } = useApp()
  const L = useLookups()
  const [f, setF] = useState({ ...EMPTY, ...teacher })
  const set = <K extends keyof Teacher>(k: K, v: Teacher[K]) => setF((s) => ({ ...s, [k]: v }))
  const setPref = (i: number, p: Partial<Pref>) =>
    set(
      'preferences',
      f.preferences.map((x, j) => (j === i ? { ...x, ...p } : x)),
    )

  const isOff = (d: number, p: number) => f.unavailable.some(([a, b]) => a === d && b === p)
  const toggle = (d: number, p: number) =>
    set('unavailable', isOff(d, p) ? f.unavailable.filter(([a, b]) => !(a === d && b === p)) : [...f.unavailable, [d, p]])
  const toggleDay = (d: number) => {
    const all = data.settings.pairs.every((p) => isOff(d, p.n))
    const rest = f.unavailable.filter(([a]) => a !== d)
    set('unavailable', all ? rest : [...rest, ...data.settings.pairs.map((p) => [d, p.n] as [number, number])])
  }

  function valueOptions(kind: Pref['kind']) {
    if (kind === 'building') return L.buildings.map((b) => [b, b])
    if (kind === 'room') return data.rooms.map((r) => [r.name, r.name])
    if (kind === 'equipment') return [['computers', 'Компьютеры'], ...data.equipment.map((e) => [e.code, e.name])]
    return [1, 2, 3, 4, 5].map((n) => [String(n), String(n)])
  }

  async function save() {
    try {
      const { id, ...body } = f as Teacher
      if (teacher.id) await api.put(`/api/teachers/${teacher.id}`, body)
      else await api.post('/api/teachers', body)
      await reload()
      toast('Сохранено')
      onClose()
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }

  async function remove() {
    if (!(await confirm(`Удалить преподавателя ${f.name}? Его занятия останутся без преподавателя.`, 'Удалить'))) return
    await api.del(`/api/teachers/${teacher.id}`)
    await reload()
    onClose()
  }

  return (
    <Modal
      title={teacher.id ? f.name : 'Новый преподаватель'}
      onClose={onClose}
      wide
      footer={
        <>
          {teacher.id && (
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
        <Field label="ФИО" wide>
          <input value={f.name} onChange={(e) => set('name', e.target.value)} autoFocus />
        </Field>
        <Field label="Кафедра">
          <input value={f.department} onChange={(e) => set('department', e.target.value)} />
        </Field>
        <Field label="Особые условия">
          <label className="switch">
            <input type="checkbox" checked={f.needs_accessible} onChange={(e) => set('needs_accessible', e.target.checked)} /> ♿
            нужна доступная среда (обязательно)
          </label>
        </Field>
      </div>

      <section>
        <h3>Пожелания к аудиториям</h3>
        <p className="muted">Солвер старается их выполнить; чем выше важность, тем сильнее. Обязательными они не являются.</p>
        {f.preferences.map((p, i) => (
          <div className="pref-row" key={i}>
            <select
              value={p.kind}
              onChange={(e) => {
                const kind = e.target.value as Pref['kind']
                setPref(i, { kind, value: String(valueOptions(kind)[0]?.[0] ?? ''), mode: 'prefer' })
              }}
            >
              {Object.entries(PREF_KINDS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
            {p.kind !== 'max_floor' && (
              <select value={p.mode} onChange={(e) => setPref(i, { mode: e.target.value as Pref['mode'] })}>
                <option value="prefer">предпочитает</option>
                <option value="avoid">избегает</option>
              </select>
            )}
            <select value={String(p.value)} onChange={(e) => setPref(i, { value: p.kind === 'max_floor' ? Number(e.target.value) : e.target.value })}>
              {valueOptions(p.kind).map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </select>
            <label className="weight" title="Важность">
              важность
              <input type="range" min={1} max={10} value={p.weight} onChange={(e) => setPref(i, { weight: Number(e.target.value) })} />
              <b>{p.weight}</b>
            </label>
            <button className="icon" onClick={() => set('preferences', f.preferences.filter((_, j) => j !== i))} aria-label="Удалить">
              ✕
            </button>
          </div>
        ))}
        <button
          onClick={() =>
            set('preferences', [...f.preferences, { kind: 'building', value: L.buildings[0] ?? '', mode: 'prefer', weight: 5 }])
          }
        >
          ＋ Пожелание
        </button>
      </section>

      <section>
        <h3>Когда не может вести занятия</h3>
        <p className="muted">Нажмите на ячейку, чтобы отметить; на день — чтобы отметить весь день.</p>
        <table className="avail">
          <thead>
            <tr>
              <th />
              {data.settings.pairs.map((p) => (
                <th key={p.n}>{p.n}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: data.settings.days }, (_, d) => (
              <tr key={d}>
                <th className="clickable" onClick={() => toggleDay(d)}>
                  {DAY_SHORT[d]}
                </th>
                {data.settings.pairs.map((p) => (
                  <td key={p.n} className={isOff(d, p.n) ? 'off' : ''} onClick={() => toggle(d, p.n)}>
                    {isOff(d, p.n) ? '✕' : ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </Modal>
  )
}
