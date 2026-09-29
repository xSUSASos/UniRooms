import { useState } from 'react'
import { api } from '../api'
import { DAY_SHORT, SOLVE_TITLES, useApp, type SolveMode } from '../context'
import type { SolveResult } from '../types'
import { Modal } from './ui'

export function SolveDialog(props: { mode: SolveMode; result: SolveResult | null; onClose: () => void }) {
  const { data, reload, toast, openLesson } = useApp()
  const [busy, setBusy] = useState(false)
  const r = props.result
  const title = SOLVE_TITLES[props.mode]
  const timeMode = props.mode.startsWith('time-')

  async function apply() {
    if (!r) return
    setBusy(true)
    try {
      const res = await api.post<{ changed: number }>('/api/apply', {
        changes: r.changes,
        description: title,
      })
      await reload()
      toast(`Применено изменений: ${res.changed}`)
      props.onClose()
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title={title}
      onClose={props.onClose}
      wide
      footer={
        r && (
          <>
            <span className="muted">
              {r.ok && `${r.optimal ? 'Оптимальное решение' : 'Лучшее найденное решение'} за ${r.seconds} с`}
            </span>
            <span className="spacer" />
            <button onClick={props.onClose}>{r.changes.length ? 'Отмена' : 'Закрыть'}</button>
            {r.changes.length > 0 && (
              <button className="primary" onClick={apply} disabled={busy}>
                Применить ({r.changes.length})
              </button>
            )}
          </>
        )
      }
    >
      {!r && (
        <div className="solving">
          <div className="spinner" />
          <p>
            {timeMode ? 'Подбираю время и аудитории' : 'Подбираю аудитории'}… (не дольше {data.settings.time_limit} с)
          </p>
        </div>
      )}
      {r && !r.ok && <p className="text-bad">{r.message}</p>}
      {r && r.ok && (
        <>
          {r.changes.length === 0 && r.unassigned.length === 0 && <p>✅ Всё уже распределено оптимально — изменений не нужно.</p>}
          {r.changes.length > 0 && (
            <>
              <p>
                Будет изменено занятий: <b>{r.changes.length}</b>
                {timeMode && <> (из них по времени: {r.moved_in_time ?? 0})</>}. Проверьте и нажмите «Применить» — отменить
                можно через Ctrl+Z.
              </p>
              <div className="table-wrap short">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Занятие</th>
                      <th>Было</th>
                      <th>Станет</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.changes.map((c) => (
                      <tr key={c.lesson_id}>
                        <td>{c.label}</td>
                        <td className="muted">
                          {DAY_SHORT[c.day]} {c.pair}, {c.from ?? 'без ауд.'}
                        </td>
                        <td>
                          <b className={c.to_day !== c.day || c.to_pair !== c.pair ? 'text-accent' : ''}>
                            {DAY_SHORT[c.to_day]} {c.to_pair}
                          </b>
                          , <b>{c.to ?? 'без ауд.'}</b>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {r.unassigned.length > 0 && (
            <>
              <h3 className="text-warn">Не удалось разместить: {r.unassigned.length}</h3>
              {props.mode === 'full' && data.lessons.length > 3000 && (
                <p className="hint-box">
                  Для большого расписания лучше «🛠 Исправить»: он меняет только проблемные занятия, а остальные оставляет в
                  их аудиториях — так свободных мест хватает всем.
                </p>
              )}
              {r.unassigned.map((u) => (
                <div key={u.lesson_id} className="issue warning clickable" onClick={() => openLesson(u.lesson_id)}>
                  <b>{u.label}</b> — {u.reason}
                </div>
              ))}
            </>
          )}
        </>
      )}
    </Modal>
  )
}
