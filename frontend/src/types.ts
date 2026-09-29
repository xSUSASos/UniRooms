export type Week = 'all' | 'odd' | 'even'

export interface Room {
  id: number
  name: string
  building: string
  floor: number
  capacity: number
  kind: string
  computers: number
  equipment: string[]
  accessible: boolean
  active: boolean
  notes: string
}

export interface Block {
  id: number
  room_id: number
  day: number | null
  pair: number | null
  reason: string
}

export interface Pref {
  kind: 'building' | 'room' | 'equipment' | 'max_floor'
  value: string | number
  mode: 'prefer' | 'avoid'
  weight: number
}

export interface Teacher {
  id: number
  name: string
  department: string
  needs_accessible: boolean
  unavailable: [number, number][]
  preferences: Pref[]
}

export interface Group {
  id: number
  name: string
  course: number
  size: number
  home_building: string
}

export interface Lesson {
  id: number
  subject: string
  kind: string
  teacher_id: number | null
  group_ids: number[]
  day: number
  pair: number
  week: Week
  required_equipment: string[]
  min_computers: number
  room_id: number | null
  locked: boolean
}

export interface Pair {
  n: number
  start: string
  end: string
}

export interface Settings {
  pairs: Pair[]
  days: number
  weights: Record<string, number>
  time_limit: number
}

export interface Equipment {
  code: string
  name: string
}

export interface HistoryItem {
  id: number
  ts: string
  description: string
  count: number
}

export interface State {
  settings: Settings
  equipment: Equipment[]
  rooms: Room[]
  blocks: Block[]
  teachers: Teacher[]
  groups: Group[]
  lessons: Lesson[]
  dicts: {
    room_kinds: Record<string, string>
    lesson_kinds: Record<string, string>
    weeks: Record<string, string>
    days: string[]
  }
  history: HistoryItem[]
  db_path: string
}

export interface Conflict {
  kind: string
  severity: 'error' | 'warning'
  message: string
  lesson_ids: number[]
}

export interface Suggestion {
  room_id: number
  room: string
  building: string
  status: 'ok' | 'warn' | 'bad'
  cost: number
  issues: string[]
  pros: string[]
  cons: string[]
}

export interface Cell {
  s: 'ok' | 'warn' | 'bad'
  r: string[]
}

export interface GridEval {
  cells: Record<number, Record<number, Cell>>
  pairs: Record<number, Cell>
}

export interface SolveChange {
  lesson_id: number
  label: string
  day: number
  pair: number
  from_room_id: number | null
  from: string | null
  to_room_id: number | null
  to: string | null
}

export interface SolveResult {
  ok: boolean
  status: string
  optimal?: boolean
  message?: string
  changes: SolveChange[]
  unassigned: { lesson_id: number; label: string; reason: string }[]
  seconds: number
}
