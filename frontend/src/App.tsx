import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import { Ctx, type AppCtx, type SolveMode } from './context'
import type { Conflict, Lesson, Session, SolveResult, State } from './types'
import { Login } from './components/Login'
import { Modal } from './components/ui'
import { LessonPanel } from './components/LessonPanel'
import { Assistant } from './components/Assistant'
import { LessonForm } from './components/LessonForm'
import { SolveDialog } from './components/SolveDialog'
import { SchedulePage } from './pages/Schedule'
import { ConflictsPage } from './pages/Conflicts'
import { RoomsPage } from './pages/Rooms'
import { TeachersPage } from './pages/Teachers'
import { GroupsPage } from './pages/Groups'
import { LessonsPage } from './pages/Lessons'
import { SettingsPage } from './pages/Settings'

const PAGES = [
  ['schedule', '📅 Расписание'],
  ['conflicts', '⚠ Конфликты'],
  ['rooms', '🚪 Аудитории'],
  ['teachers', '👤 Преподаватели'],
  ['groups', '👥 Группы'],
  ['lessons', '📚 Занятия'],
  ['settings', '⚙ Настройки'],
] as const
type Page = (typeof PAGES)[number][0]

interface Toast {
  id: number
  message: string
  kind: 'ok' | 'error' | 'info'
}

export default function App() {
  const [data, setData] = useState<State | null>(null)
  const [conflicts, setConflicts] = useState<Conflict[]>([])
  const [page, setPage] = useState<Page>('schedule')
  const [toasts, setToasts] = useState<Toast[]>([])
  const [confirmState, setConfirmState] = useState<{ message: string; ok: string; resolve: (v: boolean) => void } | null>(null)
  const [openId, setOpenId] = useState<number | null>(null)
  const [editing, setEditing] = useState<Partial<Lesson> | null>(null)
  const [solving, setSolving] = useState<{ mode: SolveMode; result: SolveResult | null } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [session, setSession] = useState<Session | null>(null)
  const [needLogin, setNeedLogin] = useState(false)
  const toastId = useRef(0)
  const version = useRef(-1)

  const toast = useCallback((message: string, kind: Toast['kind'] = 'ok') => {
    const id = ++toastId.current
    setToasts((t) => [...t, { id, message, kind }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === 'error' ? 7000 : 3500)
  }, [])

  const reload = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([api.get<State>('/api/state'), api.get<Conflict[]>('/api/conflicts')])
      version.current = s.version
      setData(s)
      setConflicts(c)
      setError(null)
      setNeedLogin(false)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setNeedLogin(true)
      else setError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    api
      .get<Session>('/api/session')
      .then(setSession)
      .catch(() => undefined)
    reload()
  }, [reload])

  // several dispatchers may work at once: pick up changes made by others
  useEffect(() => {
    const t = setInterval(async () => {
      if (document.hidden || needLogin) return
      try {
        const v = await api.get<{ version: number }>('/api/version')
        if (version.current !== -1 && v.version !== version.current) await reload()
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) setNeedLogin(true)
      }
    }, 4000)
    return () => clearInterval(t)
  }, [reload, needLogin])

  const confirm = useCallback(
    (message: string, ok = 'Да') => new Promise<boolean>((resolve) => setConfirmState({ message, ok, resolve })),
    [],
  )

  const undo = useCallback(async () => {
    try {
      const r = await api.post<{ description: string }>('/api/undo')
      toast(`Отменено: ${r.description}`, 'info')
      await reload()
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }, [reload, toast])

  const runSolve = useCallback(
    async (mode: SolveMode, faculty?: string) => {
      setSolving({ mode, result: null })
      try {
        const result = mode.startsWith('time-')
          ? await api.post<SolveResult>('/api/timetable', { mode: mode.slice(5), faculty: faculty || null })
          : await api.post<SolveResult>('/api/solve', { mode })
        setSolving({ mode, result })
      } catch (e) {
        setSolving(null)
        toast((e as Error).message, 'error')
      }
    },
    [toast],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !['INPUT', 'TEXTAREA'].includes(tag)) {
        e.preventDefault()
        undo()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [undo])

  if (needLogin) return <Login onDone={reload} />

  if (!data) {
    return <div className="loading">{error ? `Не удалось загрузить данные: ${error}` : 'Загрузка…'}</div>
  }

  const ctx: AppCtx = {
    data,
    conflicts,
    reload,
    toast,
    confirm,
    openLesson: setOpenId,
    editLesson: setEditing,
    runSolve,
    undo,
  }
  const errors = conflicts.filter((c) => c.severity === 'error').length
  const warnings = conflicts.length - errors

  return (
    <Ctx.Provider value={ctx}>
      <div className="app">
        <nav className="sidebar">
          <div className="brand">
            <span className="logo">UR</span>
            <div>
              <b>UniRooms</b>
              <small>распределение аудиторий</small>
            </div>
          </div>
          {PAGES.map(([key, label]) => (
            <button key={key} className={`nav ${page === key ? 'active' : ''}`} onClick={() => {
                setPage(key)
                setOpenId(null)
              }}>
              {label}
              {key === 'conflicts' && conflicts.length > 0 && (
                <span className={`badge ${errors ? 'red' : 'yellow'}`}>{errors || warnings}</span>
              )}
            </button>
          ))}
          <button className={`nav assistant-btn ${assistantOpen ? 'active' : ''}`} onClick={() => setAssistantOpen(!assistantOpen)}>
            💬 Помощник
          </button>
          <div className="sidebar-foot">
            <button className="nav" onClick={undo} disabled={!data.history.length} title="Ctrl+Z">
              ↶ Отменить
            </button>
            {data.history[0] && <small className="muted">Последнее: {data.history[0].description}</small>}
            <a className="nav" href="/view" target="_blank" rel="noreferrer" title="Страница для преподавателей и студентов">
              👁 Просмотр расписания
            </a>
            {session && !session.local && (
              <button
                className="nav"
                onClick={async () => {
                  await api.post('/api/logout')
                  setNeedLogin(true)
                }}
              >
                ⎋ Выйти
              </button>
            )}
          </div>
        </nav>
        <main>
          {page === 'schedule' && <SchedulePage />}
          {page === 'conflicts' && <ConflictsPage />}
          {page === 'rooms' && <RoomsPage />}
          {page === 'teachers' && <TeachersPage />}
          {page === 'groups' && <GroupsPage />}
          {page === 'lessons' && <LessonsPage />}
          {page === 'settings' && <SettingsPage />}
        </main>
        {openId !== null && <LessonPanel id={openId} onClose={() => setOpenId(null)} />}
        {assistantOpen && <Assistant onClose={() => setAssistantOpen(false)} />}
      </div>

      {editing && <LessonForm lesson={editing} onClose={() => setEditing(null)} />}
      {solving && <SolveDialog mode={solving.mode} result={solving.result} onClose={() => setSolving(null)} />}
      {confirmState && (
        <Modal
          title="Подтверждение"
          onClose={() => {
            confirmState.resolve(false)
            setConfirmState(null)
          }}
          footer={
            <>
              <button
                onClick={() => {
                  confirmState.resolve(false)
                  setConfirmState(null)
                }}
              >
                Отмена
              </button>
              <button
                className="primary"
                autoFocus
                onClick={() => {
                  confirmState.resolve(true)
                  setConfirmState(null)
                }}
              >
                {confirmState.ok}
              </button>
            </>
          }
        >
          <p className="pre">{confirmState.message}</p>
        </Modal>
      )}
      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            {t.message}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}
