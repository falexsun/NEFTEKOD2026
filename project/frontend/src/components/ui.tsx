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

export function presentReason(reason: string) {
  const unsafe = reason.match(/^No safe scenarios \((\d+) rejected\)$/)
  if (unsafe) return `Безопасных сценариев не найдено: отклонено ${unsafe[1]}`
  const history = reason.match(/^Feature buffer not ready: History not ready: (\d+) pts, (\d+) min$/)
  if (history) return `История признаков: ${history[1]} точек, ${history[2]} мин — недостаточно для расчёта`
  return reason
}

export function presentViolation(violation: string) {
  const sulfur = violation.match(/^Sulfur UCB ([\d.]+) > ([\d.]+)$/)
  if (sulfur) return `Верхняя граница прогноза серы ${formatNumber(Number(sulfur[1]), 2)} > ${formatNumber(Number(sulfur[2]), 1)} мг/кг`
  const probability = violation.match(/^P\(viol\) ([\d.]+) > ([\d.]+)$/)
  if (probability) return `Вероятность нарушения ${formatNumber(Number(probability[1]) * 100, 1)}% > допустимые ${formatNumber(Number(probability[2]) * 100, 1)}%`
  return violation
}
