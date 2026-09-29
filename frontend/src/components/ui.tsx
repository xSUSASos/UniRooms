import { useEffect, type ReactNode } from 'react'
import { Check, Inbox, Search, X, type LucideIcon } from 'lucide-react'

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
            <X size={17} />
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
            {on && <Check size={13} strokeWidth={2.5} />}
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

export function Empty(props: { children: ReactNode; icon?: LucideIcon }) {
  const Icon = props.icon ?? Inbox
  return (
    <div className="empty">
      <Icon size={28} strokeWidth={1.5} />
      <div>{props.children}</div>
    </div>
  )
}

export function SearchBox(props: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <span className="search-wrap">
      <Search size={15} />
      <input
        className="search"
        type="search"
        placeholder={props.placeholder ?? 'Поиск'}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
      />
    </span>
  )
}

/** Brand mark: a 2×2 room grid with one highlighted cell. */
export function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg className="logo" width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <defs>
        <linearGradient id="ur-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#6366f1" />
          <stop offset="1" stopColor="#4338ca" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#ur-g)" />
      <rect x="8" y="8" width="7" height="7" rx="2" fill="#fff" />
      <rect x="17" y="8" width="7" height="7" rx="2" fill="#fff" fillOpacity="0.55" />
      <rect x="8" y="17" width="7" height="7" rx="2" fill="#fff" fillOpacity="0.55" />
      <rect x="17" y="17" width="7" height="7" rx="2" fill="#fff" fillOpacity="0.55" />
    </svg>
  )
}
