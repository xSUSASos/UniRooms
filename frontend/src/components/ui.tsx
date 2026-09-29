import { useEffect, type ReactNode } from 'react'

export function Modal(props: {
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && props.onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [props.onClose])
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && props.onClose()}>
      <div className={`modal ${props.wide ? 'wide' : ''}`} role="dialog" aria-label={props.title}>
        <header>
          <h2>{props.title}</h2>
          <button className="icon" onClick={props.onClose} aria-label="Закрыть">
            ✕
          </button>
        </header>
        <div className="modal-body">{props.children}</div>
        {props.footer && <footer>{props.footer}</footer>}
      </div>
    </div>
  )
}

export function Field(props: { label: string; hint?: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={`field ${props.wide ? 'wide' : ''}`}>
      <span className="label">{props.label}</span>
      {props.children}
      {props.hint && <span className="hint">{props.hint}</span>}
    </div>
  )
}

export function Checks(props: {
  options: { value: string | number; label: string }[]
  value: (string | number)[]
  onChange: (v: (string | number)[]) => void
}) {
  return (
    <div className="checks">
      {props.options.map((o) => {
        const on = props.value.includes(o.value)
        return (
          <button
            type="button"
            key={o.value}
            className={`chip ${on ? 'on' : ''}`}
            onClick={() => props.onChange(on ? props.value.filter((v) => v !== o.value) : [...props.value, o.value])}
          >
            {on ? '✓ ' : ''}
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

export function Empty(props: { children: ReactNode }) {
  return <div className="empty">{props.children}</div>
}

export function SearchBox(props: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <input
      className="search"
      type="search"
      placeholder={props.placeholder ?? 'Поиск…'}
      value={props.value}
      onChange={(e) => props.onChange(e.target.value)}
    />
  )
}
