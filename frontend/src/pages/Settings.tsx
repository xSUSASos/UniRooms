import { useRef, useState } from 'react'
import { api } from '../api'
import { useApp } from '../context'
import type { Settings } from '../types'
import { Field } from '../components/ui'

const WEIGHTS: { key: string; title: string; hint: string }[] = [
  { key: 'preference', title: 'Пожелания преподавателей', hint: 'умножается на важность пожелания (1–10)' },
  { key: 'move', title: 'Переходы между корпусами', hint: 'между соседними парами группы или преподавателя' },
  { key: 'kind', title: 'Тип аудитории', hint: 'лекция не в лекционной, лаба не в лаборатории' },
  { key: 'home', title: 'Свой корпус группы', hint: 'за каждую группу вне её корпуса' },
  { key: 'waste', title: 'Пустые места', hint: 'за каждые 10% незанятых мест' },
  { key: 'stability', title: 'Стабильность при «Исправить»', hint: 'цена переноса занятия, которое и так корректно' },
]

export function SettingsPage() {
  const { data, reload, toast, confirm } = useApp()
  const [s, setS] = useState<Settings>(data.settings)
  const [eqCode, setEqCode] = useState('')
  const [eqName, setEqName] = useState('')
  const [importErrors, setImportErrors] = useState<string[]>([])
  const fileRef = useRef<HTMLInputElement>(null)

  async function save() {
    try {
      await api.put('/api/settings', s)
      await reload()
      toast('Настройки сохранены')
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }

  async function doImport(file: File) {
    if (!(await confirm('Импорт заменит ВСЕ текущие данные (аудитории, преподавателей, группы, занятия). Продолжить?', 'Импортировать')))
      return
    const fd = new FormData()
    fd.append('file', file)
    try {
      const r = await api.post<Record<string, number>>('/api/import', fd)
      setImportErrors([])
      await reload()
      toast(`Импортировано: ${r.rooms} аудиторий, ${r.teachers} преподавателей, ${r.groups} групп, ${r.lessons} занятий`)
    } catch (e) {
      setImportErrors((e as Error).message.split('\n'))
      toast('Импорт не выполнен — исправьте ошибки в файле', 'error')
    }
    if (fileRef.current) fileRef.current.value = ''
  }

  const setPair = (i: number, key: 'start' | 'end', v: string) =>
    setS({ ...s, pairs: s.pairs.map((p, j) => (j === i ? { ...p, [key]: v } : p)) })

  return (
    <div className="page settings">
      <div className="page-head">
        <h1>Настройки</h1>
        <button className="primary" onClick={save}>
          Сохранить настройки
        </button>
      </div>

      <div className="cols">
        <section className="box">
          <h3>Сетка занятий</h3>
          <Field label="Учебных дней в неделе">
            <select value={s.days} onChange={(e) => setS({ ...s, days: Number(e.target.value) })}>
              {[5, 6, 7].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </Field>
          <table className="table compact">
            <thead>
              <tr>
                <th>Пара</th>
                <th>Начало</th>
                <th>Конец</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {s.pairs.map((p, i) => (
                <tr key={p.n}>
                  <td>{p.n}</td>
                  <td>
                    <input type="time" value={p.start} onChange={(e) => setPair(i, 'start', e.target.value)} />
                  </td>
                  <td>
                    <input type="time" value={p.end} onChange={(e) => setPair(i, 'end', e.target.value)} />
                  </td>
                  <td>
                    {i === s.pairs.length - 1 && s.pairs.length > 1 && (
                      <button className="icon" onClick={() => setS({ ...s, pairs: s.pairs.slice(0, -1) })}>
                        ✕
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button
            onClick={() => setS({ ...s, pairs: [...s.pairs, { n: s.pairs.length + 1, start: '19:00', end: '20:30' }] })}
          >
            ＋ Пара
          </button>
        </section>

        <section className="box">
          <h3>Важность правил</h3>
          <p className="muted">Чем больше число, тем сильнее солвер старается выполнить правило.</p>
          {WEIGHTS.map((w) => (
            <div key={w.key} className="weight-row">
              <div>
                <b>{w.title}</b>
                <small>{w.hint}</small>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                value={s.weights[w.key] ?? 0}
                onChange={(e) => setS({ ...s, weights: { ...s.weights, [w.key]: Number(e.target.value) } })}
              />
              <b className="num">{s.weights[w.key]}</b>
            </div>
          ))}
          <Field label="Лимит времени солвера, сек">
            <input
              type="number"
              min={1}
              max={600}
              value={s.time_limit}
              onChange={(e) => setS({ ...s, time_limit: Number(e.target.value) })}
            />
          </Field>
        </section>

        <section className="box">
          <h3>Оборудование</h3>
          <div className="chips">
            {data.equipment.map((e) => (
              <span key={e.code} className="pill">
                {e.name}
                <button
                  className="x"
                  title="Удалить"
                  onClick={async () => {
                    if (await confirm(`Удалить «${e.name}» из справочника?`, 'Удалить')) {
                      await api.del(`/api/equipment/${e.code}`)
                      await reload()
                    }
                  }}
                >
                  ✕
                </button>
              </span>
            ))}
          </div>
          <div className="row gap">
            <input placeholder="Название, напр. «Документ-камера»" value={eqName} onChange={(e) => setEqName(e.target.value)} />
            <input placeholder="код (латиницей)" value={eqCode} onChange={(e) => setEqCode(e.target.value.toLowerCase())} />
            <button
              disabled={!eqName.trim() || !/^[a-z0-9_]+$/.test(eqCode)}
              onClick={async () => {
                try {
                  await api.post('/api/equipment', { code: eqCode, name: eqName.trim() })
                  setEqCode('')
                  setEqName('')
                  await reload()
                } catch (e) {
                  toast((e as Error).message, 'error')
                }
              }}
            >
              Добавить
            </button>
          </div>
        </section>

        <section className="box">
          <h3>Данные</h3>
          <p className="muted">
            Файл экспорта — это и есть шаблон для импорта: все листы (аудитории, преподаватели, группы, занятия, закрытия,
            оборудование) с нужными столбцами.
          </p>
          <div className="row gap wrap">
            <a className="button" href="/api/export/data.xlsx" download>
              ⬇ Экспорт данных (Excel)
            </a>
            <a className="button" href="/api/export/schedule.xlsx" download>
              ⬇ Расписание (Excel)
            </a>
            <button onClick={() => fileRef.current?.click()}>⬆ Импорт из Excel</button>
            <input ref={fileRef} type="file" accept=".xlsx" hidden onChange={(e) => e.target.files?.[0] && doImport(e.target.files[0])} />
          </div>
          {importErrors.length > 0 && (
            <div className="import-errors">
              <b>Ошибки в файле:</b>
              <ul>
                {importErrors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="row gap wrap">
            <button
              onClick={async () => {
                if (await confirm('Заменить все данные демонстрационными?', 'Загрузить демо')) {
                  await api.post('/api/demo')
                  await reload()
                  toast('Демо-данные загружены')
                }
              }}
            >
              Загрузить демо-данные
            </button>
            <button
              className="danger"
              onClick={async () => {
                if (await confirm('Удалить ВСЕ данные? Сначала сделайте экспорт, если они нужны.', 'Удалить всё')) {
                  await api.post('/api/clear')
                  await reload()
                  toast('Данные очищены')
                }
              }}
            >
              Очистить всё
            </button>
          </div>
          <p className="muted small">База данных: {data.db_path}</p>
        </section>
      </div>
    </div>
  )
}
