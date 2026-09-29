import { useState } from 'react'
import { api } from '../api'
import { useApp } from '../context'
import { Field, Modal } from './ui'

/** Quick action: close a room (repair, event) and offer to move affected lessons. */
export function BlockRoomDialog({ day, onClose, roomId }: { day: number; onClose: () => void; roomId?: number }) {
  const { data, reload, toast, confirm, runSolve } = useApp()
  const [room, setRoom] = useState<number | ''>(roomId ?? '')
  const [bday, setBday] = useState<number | ''>(day)
  const [pair, setPair] = useState<number | ''>('')
  const [reason, setReason] = useState('ремонт')

  const affected = data.lessons.filter(
    (l) => l.room_id === room && (bday === '' || l.day === bday) && (pair === '' || l.pair === pair),
  )

  async function save() {
    if (room === '') return
    try {
      await api.post('/api/blocks', {
        room_id: room,
        day: bday === '' ? null : bday,
        pair: pair === '' ? null : pair,
        reason,
      })
      await reload()
      onClose()
      toast('Аудитория закрыта')
      if (affected.length && (await confirm(`Затронуто занятий: ${affected.length}. Подобрать им другие аудитории?`, 'Подобрать'))) {
        runSolve('repair')
      }
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }

  return (
    <Modal
      title="Закрыть аудиторию"
      onClose={onClose}
      footer={
        <>
          <span className={affected.length ? 'text-warn' : 'muted'}>Затронуто занятий: {affected.length}</span>
          <span className="spacer" />
          <button onClick={onClose}>Отмена</button>
          <button className="primary" disabled={room === ''} onClick={save}>
            Закрыть аудиторию
          </button>
        </>
      }
    >
      <div className="form">
        <Field label="Аудитория" wide>
          <select value={room} onChange={(e) => setRoom(e.target.value ? Number(e.target.value) : '')} autoFocus>
            <option value="">— выберите —</option>
            {data.rooms.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name} (корп. {r.building})
              </option>
            ))}
          </select>
        </Field>
        <Field label="День">
          <select value={bday} onChange={(e) => setBday(e.target.value === '' ? '' : Number(e.target.value))}>
            <option value="">Все дни</option>
            {data.dicts.days.slice(0, data.settings.days).map((d, i) => (
              <option key={i} value={i}>
                {d}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Пара">
          <select value={pair} onChange={(e) => setPair(e.target.value === '' ? '' : Number(e.target.value))}>
            <option value="">Все пары</option>
            {data.settings.pairs.map((p) => (
              <option key={p.n} value={p.n}>
                {p.n} пара
              </option>
            ))}
          </select>
        </Field>
        <Field label="Причина" wide>
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </div>
      <p className="muted">Снять закрытие можно в карточке аудитории (раздел «Аудитории»).</p>
    </Modal>
  )
}
