import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useApp } from '../context'
import type { Settings } from '../types'
import { Field } from '../components/ui'
import type { LlmStatus } from '../components/Assistant'
import { Building2, CalendarClock, Clock, Database, Download, FileSpreadsheet, Network, Plus, Projector, SlidersHorizontal, Sparkles, Upload, X } from 'lucide-react'

interface NetInfo {
  enabled: boolean
  running: boolean
  error: string | null
  port: number
  password_set: boolean
  urls: string[]
}

const WEIGHTS: { key: string; title: string; hint: string }[] = [
  { key: 'preference', title: 'Пожелания преподавателей', hint: 'умножается на важность пожелания (1–10)' },
  { key: 'move', title: 'Переходы между корпусами', hint: 'между соседними парами группы или преподавателя' },
  { key: 'kind', title: 'Тип аудитории', hint: 'лекция не в лекционной, лаба не в лаборатории' },
  { key: 'home', title: 'Свой корпус группы', hint: 'за каждую группу вне её корпуса' },
  { key: 'waste', title: 'Пустые места', hint: 'за каждые 10% незанятых мест' },
  { key: 'stability', title: 'Стабильность при «Исправить»', hint: 'цена переноса занятия, которое и так корректно' },
]

const TIME_WEIGHTS: { key: string; title: string; hint: string }[] = [
  { key: 'gap', title: 'Окна у групп', hint: 'пустая пара между занятиями группы' },
  { key: 'teacher_gap', title: 'Окна у преподавателей', hint: 'пустая пара между занятиями преподавателя' },
  { key: 'spread', title: 'Один предмет дважды в день', hint: 'одна и та же дисциплина у тех же групп в один день' },
  { key: 'late', title: 'Поздние пары и суббота', hint: 'за каждое занятие с 5-й пары или в субботу' },
  { key: 'time_stability', title: 'Стабильность при «Убрать накладки»', hint: 'цена переноса пары без накладок' },
]

function WeightRow(props: {
  w: { key: string; title: string; hint: string }
  s: Settings
  setS: (s: Settings) => void
}) {
  const { w, s, setS } = props
  return (
    <div className="weight-row">
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
  )
}

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
          <h3>
            <CalendarClock size={16} />
            Сетка занятий
          </h3>
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
                        <X size={14} />
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
            <Plus size={15} />
            Пара
          </button>
        </section>

        <section className="box">
          <h3>
            <SlidersHorizontal size={16} />
            Важность правил
          </h3>
          <p className="muted">Чем больше число, тем сильнее солвер старается выполнить правило.</p>
          {WEIGHTS.map((w) => (
            <WeightRow key={w.key} w={w} s={s} setS={setS} />
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
          <h3>
            <Clock size={16} />
            Подбор времени
          </h3>
          <Field label="Не больше пар в день у группы" hint="0 — без ограничения (жёсткое правило)">
            <input
              type="number"
              min={0}
              max={10}
              value={s.max_per_day}
              onChange={(e) => setS({ ...s, max_per_day: Number(e.target.value) })}
            />
          </Field>
          {TIME_WEIGHTS.map((w) => (
            <WeightRow key={w.key} w={w} s={s} setS={setS} />
          ))}
        </section>

        <section className="box">
          <h3>
            <Projector size={16} />
            Оборудование
          </h3>
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
                  <X size={14} />
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
          <h3>
            <Database size={16} />
            Данные
          </h3>
          <p className="muted">
            Файл экспорта — это и есть шаблон для импорта: все листы (аудитории, преподаватели, группы, занятия, закрытия,
            оборудование) с нужными столбцами.
          </p>
          <div className="row gap wrap">
            <a className="button" href="/api/export/data.xlsx" download>
              <Download size={15} />
              Экспорт данных
            </a>
            <a className="button" href="/api/export/schedule.xlsx" download>
              <FileSpreadsheet size={15} />
              Расписание в Excel
            </a>
            <button onClick={() => fileRef.current?.click()}><Upload size={15} />
              Импорт из Excel</button>
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

        <DonstuBox />
        <NetworkBox />
        <LlmBox s={s} setS={setS} />
      </div>
    </div>
  )
}

function NetworkBox() {
  const { toast } = useApp()
  const [info, setInfo] = useState<NetInfo | null>(null)
  const [port, setPort] = useState(8765)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [local, setLocal] = useState(true)

  useEffect(() => {
    api.get<NetInfo>('/api/network').then((n) => {
      setInfo(n)
      setPort(n.port)
    })
    api.get<{ local: boolean }>('/api/session').then((s) => setLocal(s.local))
  }, [])

  async function apply(enabled: boolean) {
    setBusy(true)
    try {
      const n = await api.put<NetInfo>('/api/network', { enabled, port, password: password || null })
      setInfo(n)
      setPassword('')
      if (n.error) toast(`Не удалось открыть доступ: ${n.error}`, 'error')
      else toast(enabled ? 'Доступ по сети открыт' : 'Доступ по сети закрыт')
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  if (!info) return null
  return (
    <section className="box">
      <h3>
        <Network size={16} />
        Доступ по сети
      </h3>
      <p className="muted">
        Другие диспетчеры открывают программу в браузере по адресу ниже и входят по паролю. Преподаватели и студенты
        смотрят расписание на странице <b>/view</b> — без пароля, только чтение. Windows может спросить разрешение для
        брандмауэра — разрешите для частной сети.
      </p>
      {!local && <p className="text-warn">Настраивается только на главном компьютере.</p>}
      <div className="row gap wrap">
        <Field label="Порт">
          <input type="number" min={1024} max={65535} value={port} onChange={(e) => setPort(Number(e.target.value))} />
        </Field>
        <Field label={info.password_set ? 'Новый пароль (необязательно)' : 'Пароль редактора'}>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        </Field>
      </div>
      <div className="row gap">
        {info.running ? (
          <>
            <span className="pill green">
              <span className="dot ok" />
              открыт
            </span>
            <button disabled={busy || !local} onClick={() => apply(true)}>
              Сохранить
            </button>
            <button className="danger" disabled={busy || !local} onClick={() => apply(false)}>
              Закрыть доступ
            </button>
          </>
        ) : (
          <button
            className="primary"
            disabled={busy || !local || (!info.password_set && password.length < 4)}
            onClick={() => apply(true)}
            title={!info.password_set ? 'Задайте пароль (от 4 символов)' : ''}
          >
            Открыть доступ по сети
          </button>
        )}
      </div>
      {info.error && <p className="text-bad">{info.error}</p>}
      {info.running && (
        <div className="urls">
          {info.urls.map((u) => (
            <div key={u}>
              <span className="muted">Редактирование:</span> <code>{u}</code> · <span className="muted">просмотр:</span>{' '}
              <code>{u}view</code>
            </div>
          ))}
          {!info.urls.length && <p className="muted">Не удалось определить IP-адрес компьютера.</p>}
        </div>
      )}
    </section>
  )
}

function LlmBox({ s, setS }: { s: Settings; setS: (s: Settings) => void }) {
  const [status, setStatus] = useState<LlmStatus | null>(null)
  const check = () => api.get<LlmStatus>('/api/assistant/status').then(setStatus).catch(() => setStatus(null))
  useEffect(() => {
    check()
  }, [])
  return (
    <section className="box">
      <h3>
        <Sparkles size={16} />
        ИИ-помощник
      </h3>
      <p className="muted">
        Помощник понимает команды обычным языком. Работает через локальную модель в Ollama — без интернета, данные не
        покидают компьютер.
      </p>
      <p>
        {status?.available ? (
          <span className="pill green">
            <span className="dot ok" />
            подключено: {status.model}
          </span>
        ) : (
          <span className="pill yellow">
            Ollama не найдена — установите с ollama.com и выполните <code>ollama pull qwen2.5:7b</code>
          </span>
        )}{' '}
        <button className="small" onClick={check}>
          Проверить
        </button>
      </p>
      <Field label="Адрес Ollama">
        <input value={s.llm.url} onChange={(e) => setS({ ...s, llm: { ...s.llm, url: e.target.value } })} />
      </Field>
      <Field label="Модель" hint="Сохраните настройки, чтобы применить">
        <select value={s.llm.model} onChange={(e) => setS({ ...s, llm: { ...s.llm, model: e.target.value } })}>
          <option value="">автоматически (первая установленная)</option>
          {status?.models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </Field>
    </section>
  )
}

interface DonstuJob {
  running: boolean
  stage?: string
  done?: number
  total?: number
  year: string
  error?: string | null
  result?: { rooms: number; teachers: number; groups: number; lessons: number; window?: string[] | null; failed?: string[] } | null
}

function DonstuBox() {
  const { reload, toast, confirm } = useApp()
  const [job, setJob] = useState<DonstuJob | null>(null)
  const [year, setYear] = useState('')

  useEffect(() => {
    api.get<DonstuJob>('/api/import/donstu').then((j) => {
      setJob(j)
      setYear(j.year)
    })
  }, [])

  useEffect(() => {
    if (!job?.running) return
    const t = setInterval(async () => {
      const j = await api.get<DonstuJob>('/api/import/donstu')
      setJob(j)
      if (!j.running) {
        clearInterval(t)
        if (j.error) toast(`Загрузка не удалась: ${j.error}`, 'error')
        else {
          await reload()
          toast('Расписание ДГТУ загружено')
        }
      }
    }, 1500)
    return () => clearInterval(t)
  }, [job?.running])

  async function start(refresh: boolean) {
    if (!(await confirm('Все текущие данные будут заменены расписанием ДГТУ с edu.donstu.ru. Продолжить?', 'Загрузить')))
      return
    try {
      setJob(await api.post<DonstuJob>('/api/import/donstu', { year, refresh }))
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }

  const pct = job?.total ? Math.round(((job.done ?? 0) / job.total) * 100) : 0
  return (
    <section className="box">
      <h3>
        <Building2 size={16} />
        Расписание ДГТУ
      </h3>
      <p className="muted">
        Загружает открытое расписание всех групп университета с edu.donstu.ru (без колледжей): аудитории, преподавателей,
        группы и занятия реальной двухнедельки (верхняя + нижняя неделя). Вместимость аудиторий и численность групп не
        публикуются — они оценены; уточните их в справочниках или через Excel.
      </p>
      <div className="row gap wrap">
        <Field label="Учебный год">
          <input value={year} onChange={(e) => setYear(e.target.value)} placeholder="2026-2027" />
        </Field>
      </div>
      <div className="row gap wrap">
        <button className="primary" disabled={job?.running} onClick={() => start(false)}>
          <Download size={15} />
          Загрузить расписание ДГТУ
        </button>
        <button disabled={job?.running} onClick={() => start(true)} title="Скачать заново, не используя сохранённые файлы">
          Обновить с сайта
        </button>
      </div>
      {job?.running && (
        <div className="progress-box">
          <small>
            {job.stage} {job.total ? `${job.done} из ${job.total}` : ''}
          </small>
          <progress max={100} value={pct} />
        </div>
      )}
      {!job?.running && job?.result && (
        <p className="text-ok">
          Загружено: {job.result.groups} групп, {job.result.teachers} преподавателей, {job.result.rooms} аудиторий,{' '}
          {job.result.lessons} занятий
          {job.result.window && ` (недели с ${job.result.window[0]})`}
        </p>
      )}
      {!job?.running && job?.error && <p className="text-bad">{job.error}</p>}
    </section>
  )
}
