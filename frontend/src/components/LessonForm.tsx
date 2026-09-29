import { useState } from 'react'
import { api } from '../api'
import { useApp } from '../context'
import type { Lesson } from '../types'
import { Checks, Field, Modal, SearchBox } from './ui'

const EMPTY: Omit<Lesson, 'id'> = {
  subject: '',
  kind: 'practice',
  teacher_id: null,
  group_ids: [],
  day: 0,
  pair: 1,
  week: 'all',
  required_equipment: [],
  min_computers: 0,
  room_id: null,
  locked: false,
}

export function LessonForm({ lesson, onClose }: { lesson: Partial<Lesson>; onClose: () => void }) {
  const { data, reload, toast, confirm } = useApp()
  const [f, setF] = useState({ ...EMPTY, ...lesson })
  const [gq, setGq] = useState('')
  const set = <K extends keyof Lesson>(k: K, v: Lesson[K]) => setF((s) => ({ ...s, [k]: v }))
  const subjects = [...new Set(data.lessons.map((l) => l.subject))].sort()

  async function save() {
    try {
      const { id, ...body } = f as Lesson
      if (lesson.id) await api.put(`/api/lessons/${lesson.id}`, body)
      else await api.post('/api/lessons', body)
      await reload()
      toast('Сохранено')
      onClose()
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }

  async function remove() {
    if (!(await confirm(`Удалить занятие «${f.subject}»?`, 'Удалить'))) return
    await api.del(`/api/lessons/${lesson.id}`)
    await reload()
    toast('Удалено')
    onClose()
  }

  const groups = data.groups.filter((g) => !gq || g.name.toLowerCase().includes(gq.toLowerCase()) || f.group_ids.includes(g.id))

  return (
    <Modal
      title={lesson.id ? 'Занятие' : 'Новое занятие'}
      onClose={onClose}
      wide
      footer={
        <>
          {lesson.id && (
            <button className="danger" onClick={remove}>
              Удалить
            </button>
          )}
          <span className="spacer" />
          <button onClick={onClose}>Отмена</button>
          <button className="primary" onClick={save} disabled={!f.subject.trim()}>
            Сохранить
          </button>
        </>
      }
    >
      <div className="form">
        <Field label="Дисциплина" wide>
          <input list="subjects" value={f.subject} onChange={(e) => set('subject', e.target.value)} autoFocus />
          <datalist id="subjects">
            {subjects.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
        </Field>
        <Field label="Тип">
          <select value={f.kind} onChange={(e) => set('kind', e.target.value)}>
            {Object.entries(data.dicts.lesson_kinds).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Преподаватель">
          <select value={f.teacher_id ?? ''} onChange={(e) => set('teacher_id', e.target.value ? Number(e.target.value) : null)}>
            <option value="">—</option>
            {data.teachers.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="День">
          <select value={f.day} onChange={(e) => set('day', Number(e.target.value))}>
            {data.dicts.days.slice(0, data.settings.days).map((d, i) => (
              <option key={i} value={i}>
                {d}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Пара">
          <select value={f.pair} onChange={(e) => set('pair', Number(e.target.value))}>
            {data.settings.pairs.map((p) => (
              <option key={p.n} value={p.n}>
                {p.n} ({p.start}–{p.end})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Неделя">
          <select value={f.week} onChange={(e) => set('week', e.target.value as Lesson['week'])}>
            {Object.entries(data.dicts.weeks).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Аудитория" hint="Можно оставить пустой — подберёт солвер">
          <select value={f.room_id ?? ''} onChange={(e) => set('room_id', e.target.value ? Number(e.target.value) : null)}>
            <option value="">— подобрать автоматически —</option>
            {data.rooms.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name} ({r.capacity} мест)
              </option>
            ))}
          </select>
        </Field>
        <Field label={`Группы (${f.group_ids.length})`} wide hint="Несколько групп = поток">
          <SearchBox value={gq} onChange={setGq} placeholder="Найти группу…" />
          <Checks
            options={groups.map((g) => ({ value: g.id, label: `${g.name} · ${g.size}` }))}
            value={f.group_ids}
            onChange={(v) => set('group_ids', v as number[])}
          />
        </Field>
        <Field label="Обязательное оборудование" wide>
          <Checks
            options={data.equipment.map((e) => ({ value: e.code, label: e.name }))}
            value={f.required_equipment}
            onChange={(v) => set('required_equipment', v as string[])}
          />
        </Field>
        <Field label="Минимум компьютеров">
          <input type="number" min={0} value={f.min_computers} onChange={(e) => set('min_computers', Number(e.target.value))} />
        </Field>
        <Field label="Закрепить">
          <label className="switch">
            <input type="checkbox" checked={f.locked} onChange={(e) => set('locked', e.target.checked)} /> 🔒 не двигать при
            автораспределении
          </label>
        </Field>
      </div>
    </Modal>
  )
}
