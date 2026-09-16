import type { Q21Runtime } from '../types'
import { EmptyState, formatNumber, StatusBadge } from './ui'

export function Q21ForecastPanel({ runtime }: { runtime: Q21Runtime | null }) {
  const bundle = runtime?.latest_forecast
  if (!bundle) return <section className="panel q21-forecast-panel"><EmptyState title="Траектория Q21 ещё не рассчитана" detail={`Накоплено ${runtime?.points ?? 0} из ${runtime?.required_points ?? 145} последовательных 10-минутных точек.`} state="unknown" /></section>
  const latestPointTime = runtime?.latest_point?.timestamp ? new Date(runtime.latest_point.timestamp).getTime() : NaN
  const forecastTime = new Date(bundle.origin_timestamp).getTime()
  const current = latestPointTime === forecastTime ? runtime?.latest_point?.Q21 : undefined
  const series = typeof current === 'number'
    ? [{ horizon_hours: 0, q21: current }, ...bundle.forecasts]
    : bundle.forecasts
  const values = series.map(point => point.q21).concat([10])
  const min = Math.min(...values) - .5
  const max = Math.max(...values) + .5
  const range = Math.max(1, max - min)
  const x = (hours: number) => 4 + (hours / 6) * 92
  const y = (value: number) => 52 - ((value - min) / range) * 44
  const points = series.map(point => `${x(point.horizon_hours)},${y(point.q21)}`).join(' ')
  const h1 = bundle.forecasts.find(point => point.horizon_hours === 1)
  return <section className="panel q21-forecast-panel">
    <div className="panel-heading"><div><span>Q21</span><h2>Прогнозная траектория</h2></div><StatusBadge state={runtime.data_state === 'historical' ? 'stale' : (h1?.q21 ?? 0) >= 10 ? 'critical' : (h1?.q21 ?? 0) >= 9 ? 'warning' : 'normal'}>{runtime.data_state === 'historical' ? 'Исторический replay · ' : ''}{new Date(bundle.origin_timestamp).toLocaleString('ru-RU')}</StatusBadge></div>
    <svg className="q21-forecast-chart" viewBox="0 0 100 58" preserveAspectRatio="none" role="img" aria-label="Прогноз Q21 от текущего значения до шести часов">
      <line x1="4" x2="96" y1={y(10)} y2={y(10)} className="q21-limit" />
      {h1?.lower != null && h1?.upper != null && <line x1={x(1)} x2={x(1)} y1={y(h1.lower)} y2={y(h1.upper)} className="q21-interval" />}
      <polyline points={points} className="q21-line" />
      {series.map(point => <circle key={point.horizon_hours} cx={x(point.horizon_hours)} cy={y(point.q21)} r="1.2" />)}
    </svg>
    <div className="q21-horizons">{series.map(point => <div key={point.horizon_hours}><span>{point.horizon_hours === 0 ? 'Сейчас' : `+${point.horizon_hours} ч`}</span><strong>{formatNumber(point.q21, 2)}</strong><small>ppm</small></div>)}</div>
    <div className="q21-shadow-summary"><span>Закрыто прогнозов: <b>{runtime.shadow_metrics.resolved}</b></span>{runtime.shadow_metrics.by_horizon.map(metric => <span key={metric.horizon_hours}>MAE {metric.horizon_hours} ч: <b>{formatNumber(metric.mae, 2)} ppm</b>{metric.interval_coverage != null && <small> · покрытие {Math.round(metric.interval_coverage * 100)}%</small>}</span>)}</div>
    <p className="fineprint">Интервал q10–q90 показан для +1 ч. Прогноз наблюдательный и не является командой оператору.</p>
  </section>
}
