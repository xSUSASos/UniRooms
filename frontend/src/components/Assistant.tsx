import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useApp, type SolveMode } from '../context'

interface Action {
  action: string
  solve_mode?: SolveMode
  [key: string]: unknown
}

interface Plan {
  ok: boolean
  message?: string
  reply?: string
  summary?: string
  action?: Action | null
  auto?: boolean
  llm?: boolean
}

interface Msg {
  id: number
  role: 'user' | 'bot'
  text: string
  plan?: Plan
  state?: 'pending' | 'done' | 'cancelled'
  followUp?: { label: string; mode: SolveMode }
}

export interface LlmStatus {
  available: boolean
  models: string[]
  model: string | null
  url: string
}

const EXAMPLES = [
  'Закрой А-202 в среду, ремонт',
  'Петрова не любит корпус В',
  'Сидоров в пятницу не может',
  'Убери накладки',
  'Почему у ПИ-21 информатика в этой аудитории?',
]

export function Assistant({ onClose }: { onClose: () => void }) {
  const { reload, toast, runSolve } = useApp()
  const [status, setStatus] = useState<LlmStatus | null>(null)
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const nextId = useRef(1)
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.get<LlmStatus>('/api/assistant/status').then(setStatus).catch(() => setStatus(null))
  }, [])
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [msgs, busy])

  const push = (m: Omit<Msg, 'id'>) => setMsgs((list) => [...list, { ...m, id: nextId.current++ }])
  const update = (id: number, patch: Partial<Msg>) => setMsgs((list) => list.map((m) => (m.id === id ? { ...m, ...patch } : m)))

  async function execute(msg: Msg) {
    const action = msg.plan?.action
    if (!action) return
    if (action.action === 'solve') {
      update(msg.id, { state: 'done' })
      runSolve(action.solve_mode ?? 'repair')
      return
    }
    setBusy(true)
    try {
      const res = await api.post<{ message: string; affected?: number }>('/api/assistant/execute', { action })
      update(msg.id, { state: 'done' })
      let followUp: Msg['followUp']
      if (res.affected && action.action === 'block_room') followUp = { label: 'Подобрать другие аудитории', mode: 'repair' }
      if (res.affected && ['set_unavailable', 'move_lesson'].includes(action.action))
        followUp = { label: 'Убрать накладки автоматически', mode: 'time-repair' }
      push({ role: 'bot', text: res.message, followUp })
      await reload()
    } catch (e) {
      push({ role: 'bot', text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  async function send(value = text) {
    const q = value.trim()
    if (!q || busy) return
    setText('')
    push({ role: 'user', text: q })
    setBusy(true)
    try {
      const plan = await api.post<Plan>('/api/assistant/interpret', { text: q })
      if (!plan.ok) push({ role: 'bot', text: plan.message ?? 'Не понял' })
      else if (plan.reply) push({ role: 'bot', text: plan.reply })
      else if (plan.action) {
        const msg: Msg = { id: nextId.current++, role: 'bot', text: plan.summary ?? '', plan, state: 'pending' }
        setMsgs((list) => [...list, msg])
        if (plan.auto) {
          setBusy(false)
          await execute(msg)
        }
      }
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="panel assistant">
      <header>
        <div>
          <h2>💬 Помощник</h2>
          <small>
            {status === null
              ? 'проверяю ИИ…'
              : status.available
                ? `локальная ИИ-модель: ${status.model}`
                : 'ИИ не найден — работают простые команды'}
          </small>
        </div>
        <button className="icon" onClick={onClose} aria-label="Закрыть">
          ✕
        </button>
      </header>

      {status && !status.available && (
        <div className="hint-box">
          Чтобы помощник понимал свободные фразы, установите <b>Ollama</b> (ollama.com) и скачайте модель командой{' '}
          <code>ollama pull qwen2.5:7b</code>. Всё работает локально, без интернета. Без неё понимаются команды вида
          «закрой А-202», «убери накладки», «распредели аудитории».
        </div>
      )}

      <div className="chat">
        {!msgs.length && (
          <div className="examples">
            <p className="muted">Напишите, что нужно сделать. Например:</p>
            {EXAMPLES.map((e) => (
              <button key={e} className="chip" onClick={() => send(e)}>
                {e}
              </button>
            ))}
          </div>
        )}
        {msgs.map((m) => (
          <div key={m.id} className={`msg ${m.role}`}>
            {m.plan?.action && !m.plan.auto ? (
              <div className="plan">
                <small>Понял так{m.plan.llm ? '' : ' (простой разбор)'}:</small>
                <b>{m.text}</b>
                {m.state === 'pending' && (
                  <div className="row gap">
                    <button className="primary small" disabled={busy} onClick={() => execute(m)}>
                      {m.plan.action.action === 'solve' ? 'Запустить' : 'Выполнить'}
                    </button>
                    <button className="small" onClick={() => update(m.id, { state: 'cancelled' })}>
                      Отмена
                    </button>
                  </div>
                )}
                {m.state === 'done' && <small className="text-ok">✓ выполнено</small>}
                {m.state === 'cancelled' && <small className="muted">отменено</small>}
              </div>
            ) : (
              <p className="pre">{m.text}</p>
            )}
            {m.followUp && (
              <button className="small" onClick={() => runSolve(m.followUp!.mode)}>
                {m.followUp.label}
              </button>
            )}
          </div>
        ))}
        {busy && <div className="msg bot typing">думаю…</div>}
        <div ref={bottom} />
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Например: перенеси физику ИВТ-21 на четверг 2 пару"
          autoFocus
        />
        <button className="primary" disabled={busy || !text.trim()}>
          ➤
        </button>
      </form>
    </aside>
  )
}
