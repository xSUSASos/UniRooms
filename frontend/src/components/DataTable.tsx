import { useState, type ReactNode } from 'react'
import { Empty } from './ui'

export interface Column<T> {
  title: string
  render: (row: T) => ReactNode
  sort?: (row: T) => string | number
  className?: string
}

export function DataTable<T extends { id: number }>(props: {
  rows: T[]
  columns: Column<T>[]
  onRowClick?: (row: T) => void
  empty?: ReactNode
}) {
  const [sortIdx, setSortIdx] = useState<number | null>(null)
  const [dir, setDir] = useState(1)
  let rows = props.rows
  const sortFn = sortIdx !== null ? props.columns[sortIdx].sort : undefined
  if (sortFn) {
    rows = [...rows].sort((a, b) => {
      const x = sortFn(a)
      const y = sortFn(b)
      return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'ru')) * dir
    })
  }
  if (!rows.length) return <Empty>{props.empty ?? 'Пусто'}</Empty>
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {props.columns.map((c, i) => (
              <th
                key={c.title}
                className={c.sort ? 'sortable' : ''}
                onClick={() => {
                  if (!c.sort) return
                  if (sortIdx === i) setDir(-dir)
                  else {
                    setSortIdx(i)
                    setDir(1)
                  }
                }}
              >
                {c.title}
                {sortIdx === i && (dir > 0 ? ' ▲' : ' ▼')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} onClick={() => props.onRowClick?.(r)} className={props.onRowClick ? 'clickable' : ''}>
              {props.columns.map((c) => (
                <td key={c.title} className={c.className}>
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
