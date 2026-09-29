import { createContext, useContext } from 'react'
import type { Conflict, Lesson, State } from './types'

export interface AppCtx {
  data: State
  conflicts: Conflict[]
  reload: () => Promise<void>
  toast: (message: string, kind?: 'ok' | 'error' | 'info') => void
  confirm: (message: string, okText?: string) => Promise<boolean>
  openLesson: (id: number | null) => void
  editLesson: (lesson: Partial<Lesson> | null) => void
  runSolve: (mode: 'full' | 'repair') => void
  undo: () => void
}

export const Ctx = createContext<AppCtx>(null as unknown as AppCtx)
export const useApp = () => useContext(Ctx)

/** Lookup helpers built from state once per render. */
export function useLookups() {
  const { data } = useApp()
  const rooms = new Map(data.rooms.map((r) => [r.id, r]))
  const teachers = new Map(data.teachers.map((t) => [t.id, t]))
  const groups = new Map(data.groups.map((g) => [g.id, g]))
  const eq = new Map(data.equipment.map((e) => [e.code, e.name]))
  const buildings = [...new Set(data.rooms.map((r) => r.building).filter(Boolean))].sort()
  const groupNames = (l: Lesson) => l.group_ids.map((g) => groups.get(g)?.name ?? '?').join(', ')
  const lessonSize = (l: Lesson) => l.group_ids.reduce((s, g) => s + (groups.get(g)?.size ?? 0), 0)
  return { rooms, teachers, groups, eq, buildings, groupNames, lessonSize }
}

export const DAY_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

export function shortName(name: string) {
  return name.split(' ')[0]
}
