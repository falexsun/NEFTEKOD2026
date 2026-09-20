import type { OperatingPolicy } from '../types'
import { EmptyState, StatusBadge } from './ui'

export function OperatingModes({ policy }: { policy?: OperatingPolicy }) {
  if (!policy) return <EmptyState title="Режим установки не подтверждён" detail="Нет статуса от источника телеметрии. Расчёты заблокированы." state="unknown" />
  return <section className="panel operating-modes" aria-label="Режимы установки">
    <div><span className="eyebrow">ДОПУСК К РАСЧЁТУ</span><h2>{policy.allowed ? 'Рабочие режимы подтверждены' : policy.disposition === 'NO_ACTION' ? 'Оптимизация приостановлена' : 'Недостаточно данных о режиме'}</h2><p>{policy.allowed ? 'Режим установки подтверждён телеметрией; готовность модели и истории проверяется отдельно.' : policy.reasons.join(' · ')}</p></div>
    <div className="mode-units">{policy.units.map(unit => <div key={unit.id}><strong>{unit.label}</strong><StatusBadge state={!unit.fresh || unit.mode === 'unknown' ? 'unknown' : unit.mode === 'normal' ? 'normal' : 'warning'}>{unit.mode_label}</StatusBadge></div>)}</div>
    <p className="fineprint">{policy.description} {!policy.allowed && 'Передайте актуальные режимы через интеграцию телеметрии. NO_ACTION — отсутствие рекомендации, а не команда остановить установку.'}</p>
  </section>
}
