import { useState } from 'react'
import { api } from '../api'

/** Shown to dispatchers who open the app from another computer in the network. */
export function Login({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      await api.post('/api/login', { password })
      onDone()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <form
        className="box"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <div className="brand">
          <span className="logo">UR</span>
          <div>
            <b>UniRooms</b>
            <small>вход для редактирования</small>
          </div>
        </div>
        <input
          type="password"
          placeholder="Пароль редактора"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
        />
        {error && <p className="text-bad">{error}</p>}
        <button className="primary" disabled={busy || !password}>
          Войти
        </button>
        <a href="/view" className="muted">
          Только посмотреть расписание →
        </a>
      </form>
    </div>
  )
}
