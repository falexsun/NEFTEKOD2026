import type { ReactNode } from 'react'
import { AlertTriangle, CircleAlert, CircleCheck, CircleHelp, WifiOff } from 'lucide-react'
import type { SemanticState } from '../types'

const stateLabels: Record<SemanticState, string> = {
  normal: 'Актуально', attention: 'Внимание', warning: 'Предупреждение', critical: 'Критично',
  stale: 'Устарело', unknown: 'Нет отметки времени', unavailable: 'Недоступно',
}

export function StatusBadge({ state, children }: { state: SemanticState; children?: ReactNode }) {
  const Icon = state === 'normal' ? CircleCheck : state === 'unknown' ? CircleHelp : state === 'unavailable' ? WifiOff : state === 'critical' ? AlertTriangle : CircleAlert
  return <span className={`status-badge state-${state}`}><Icon size={14} />{children ?? stateLabels[state]}</span>
}

export function EmptyState({ title, detail, state = 'unavailable' }: { title: string; detail: string; state?: SemanticState }) {
  return <div className={`empty-state state-${state}`}><WifiOff size={26} /><div><strong>{title}</strong><p>{detail}</p></div></div>
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return <div className="skeleton" aria-label="Загрузка">{Array.from({ length: lines }, (_, index) => <i key={index} />)}</div>
}

export function formatNumber(value: number | null | undefined, digits = 1) {
  return value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function formatAge(minutes: number | null) {
  if (minutes == null) return 'время неизвестно'
  if (minutes < 1) return `${Math.max(1, Math.round(minutes * 60))} сек назад`
  if (minutes < 60) return `${Math.round(minutes)} мин назад`
  return `${Math.floor(minutes / 60)} ч ${Math.round(minutes % 60)} мин назад`
}

export function displayUnit(unit: string) {
  return ({ 'mg/kg': 'мг/кг', 'm3/h': 'м³/ч', 't/h': 'т/ч' } as Record<string, string>)[unit] ?? unit
}
