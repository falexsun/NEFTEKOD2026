import { useEffect, useState } from 'react'
import type { Q21Runtime } from '../types'
import { EmptyState, formatNumber, StatusBadge } from './ui'

const LIMIT = 10
const WATCH = 9
const HORIZONS = [0.5, 1, 2, 3, 6]
const horizonLabel = (hours: number) => hours === 0.5 ? '+30 мин' : `+${hours} ч`
const pointState = (value: number) => value >= LIMIT ? 'critical' : value >= WATCH ? 'warning' : 'normal'
const timeLabel = (value: string) => new Date(value).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
const settingKey = 'neftekod.q21.chart.v1'
type ChartSettings = { showValues: boolean; showInterval: boolean }

function readSettings(): ChartSettings {
  try {
    const saved = JSON.parse(window.localStorage.getItem(settingKey) ?? '{}') as Partial<ChartSettings>
    return { showValues: saved.showValues === true, showInterval: saved.showInterval !== false }
  } catch {
    return { showValues: false, showInterval: true }
  }
}

export function Q21ForecastPanel({ runtime }: { runtime: Q21Runtime | null }) {
  const [settings, setSettings] = useState<ChartSettings>(readSettings)
  useEffect(() => {
    try { window.localStorage.setItem(settingKey, JSON.stringify(settings)) } catch { /* Private browsing may block storage. */ }
  }, [settings])
  const bundle = runtime?.latest_forecast
  if (!bundle) return <section className="panel q21-forecast-panel"><EmptyState title="Траектория Q21 ещё не рассчитана" detail={`Накоплено ${runtime?.points ?? 0} из ${runtime?.required_points ?? 145} последовательных 10-минутных точек.`} state="unknown" /></section>

  const originMs = new Date(bundle.origin_timestamp).getTime()
  const latestMs = runtime?.latest_point?.timestamp ? new Date(runtime.latest_point.timestamp).getTime() : NaN
  const archived = runtime?.data_state !== 'live' || !Number.isFinite(latestMs) || latestMs !== originMs
  const forecasts = [...bundle.forecasts].filter(point => HORIZONS.includes(point.horizon_hours) && Number.isFinite(point.q21)).sort((a, b) => a.horizon_hours - b.horizon_hours)
  const observed = (runtime?.history ?? [])
    .map(point => ({ hour: (new Date(point.timestamp).getTime() - originMs) / 3_600_000, q21: point.q21 }))
    .filter(point => Number.isFinite(point.hour) && Number.isFinite(point.q21) && point.hour >= -3 && point.hour <= 0)
    .sort((a, b) => a.hour - b.hour)
  const originPoint = observed.find(point => Math.abs(point.hour) < 0.001)
  const modelLine = [...(originPoint ? [{ hour: 0, q21: originPoint.q21 }] : []), ...forecasts.map(point => ({ hour: point.horizon_hours, q21: point.q21 }))]
  const values = [...observed, ...modelLine].map(point => point.q21).concat(LIMIT,
    ...forecasts.flatMap(point => [point.lower, point.upper].filter((bound): bound is number => typeof bound === 'number' && Number.isFinite(bound))))
  const bottom = Math.floor(Math.min(...values) - 0.4)
  const top = Math.ceil(Math.max(...values) + 0.4)
  const range = Math.max(1, top - bottom)
  const x = (hour: number) => 72 + ((hour + 3) / 9) * 1000
  const y = (value: number) => 276 - ((value - bottom) / range) * 208
  const path = (points: Array<{ hour: number; q21: number }>) => points.map((point, index) => `${index ? 'L' : 'M'} ${x(point.hour).toFixed(1)} ${y(point.q21).toFixed(1)}`).join(' ')
  const ticks = Array.from({ length: top - bottom + 1 }, (_, index) => bottom + index)
  const firstLimit = forecasts.find(point => point.q21 >= LIMIT)
  const firstWatch = forecasts.find(point => point.q21 >= WATCH)
  const peak = forecasts.reduce<(typeof forecasts)[number] | undefined>((best, point) => !best || point.q21 > best.q21 ? point : best, undefined)
  const interval = forecasts.find(point => point.horizon_hours === 1 && point.lower != null && point.upper != null && Number.isFinite(point.lower) && Number.isFinite(point.upper))
  const status = archived ? 'stale' : firstLimit ? 'critical' : firstWatch ? 'warning' : 'normal'
  const message = archived
    ? 'Исторический расчёт: не использовать как текущую рекомендацию.'
    : firstLimit
      ? `Проверить анализатор и режим: модель для ${horizonLabel(firstLimit.horizon_hours)} показывает ${formatNumber(firstLimit.q21, 2)} ppm — выше предела.`
      : firstWatch
        ? `Усилить наблюдение: модель для ${horizonLabel(firstWatch.horizon_hours)} показывает ${formatNumber(firstWatch.q21, 2)} ppm.`
        : peak
          ? `Превышения в пяти расчётных горизонтах нет. Максимум — ${formatNumber(peak.q21, 2)} ppm для ${horizonLabel(peak.horizon_hours)}.`
          : 'Нет доступных прогнозов для оценки риска.'

  return <section className="panel q21-forecast-panel" aria-label="Прогноз Q21 на шесть часов">
    <div className="panel-heading q21-heading"><div><span>Q21 · НАБЛЮДАТЕЛЬНЫЙ ПРОГНОЗ</span><h2>История и прогноз до 6 часов</h2><p>Синим — измерения за 3 часа; янтарным — отдельные прогнозы моделей.</p></div><StatusBadge state={archived ? 'stale' : 'normal'}>{archived ? 'Архив · ' : 'Расчёт · '}{new Date(bundle.origin_timestamp).toLocaleString('ru-RU')}</StatusBadge></div>
    <div className={`q21-guidance q21-guidance-${status}`} role="status"><span>{archived ? 'НЕАКТУАЛЬНО' : firstLimit ? 'РИСК ПРЕВЫШЕНИЯ' : firstWatch ? 'КОНТРОЛЬ КАЧЕСТВА' : 'ПРОГНОЗ В ДОПУСКЕ'}</span><strong>{message}</strong><small>Подсказка для проверки, не команда на изменение уставки.</small></div>
    <div className="q21-chart-settings" role="group" aria-label="Настройки графика"><span>ВИД ГРАФИКА</span><button type="button" className={settings.showValues ? 'active' : ''} aria-pressed={settings.showValues} onClick={() => setSettings(current => ({ ...current, showValues: !current.showValues }))}>Значения на графике</button><button type="button" className={settings.showInterval ? 'active' : ''} aria-pressed={settings.showInterval} disabled={!interval} title={interval ? 'Интервал q10–q90 рассчитан только для прогноза +1 ч' : 'Интервал неопределённости пока недоступен'} onClick={() => setSettings(current => ({ ...current, showInterval: !current.showInterval }))}>Интервал q10–q90 · +1 ч</button></div>
    <div className="q21-chart-wrap"><svg className="q21-forecast-chart" viewBox="0 0 1120 330" role="img" aria-label="Q21: история за три часа, прогнозы отдельных моделей на 30 минут, 1, 2, 3 и 6 часов, предел 10 ppm">
      {ticks.map(tick => <g key={tick}><line className="q21-grid-line" x1="72" x2="1072" y1={y(tick)} y2={y(tick)} /><text className="q21-axis-label" x="57" y={y(tick) + 4} textAnchor="end">{tick}</text></g>)}
      <line className="q21-now-line" x1={x(0)} x2={x(0)} y1="68" y2="276" />
      <line className="q21-limit" x1="72" x2="1072" y1={y(LIMIT)} y2={y(LIMIT)} />
      <text className="q21-limit-label" x="1068" y={y(LIMIT) - 9} textAnchor="end">ПРЕДЕЛ 10,0 PPM</text>
      {forecasts.map(point => <line key={`guide-${point.horizon_hours}`} className="q21-forecast-guide" x1={x(point.horizon_hours)} x2={x(point.horizon_hours)} y1={y(point.q21)} y2="276" />)}
      {settings.showInterval && interval && <g className="q21-interval-group" aria-label={`Интервал q10–q90 для +1 ч: ${formatNumber(interval.lower, 2)}–${formatNumber(interval.upper, 2)} ppm`}><line className="q21-interval" x1={x(1)} x2={x(1)} y1={y(interval.lower!)} y2={y(interval.upper!)} /><line className="q21-interval-cap" x1={x(1) - 12} x2={x(1) + 12} y1={y(interval.lower!)} y2={y(interval.lower!)} /><line className="q21-interval-cap" x1={x(1) - 12} x2={x(1) + 12} y1={y(interval.upper!)} y2={y(interval.upper!)} /><text className="q21-bound-label" x={x(1) + 55} y={y(interval.upper!) + 4}>q90 {formatNumber(interval.upper, 2)}</text><text className="q21-bound-label" x={x(1) + 55} y={y(interval.lower!) + 4}>q10 {formatNumber(interval.lower, 2)}</text></g>}
      {observed.length > 1 && <path className="q21-history-line" d={path(observed)} />}
      {modelLine.length > 1 && <path className="q21-model-line" d={path(modelLine)} />}
      {originPoint && <circle className="q21-origin-point" cx={x(0)} cy={y(originPoint.q21)} r="6" />}
      {forecasts.map(point => <circle key={point.horizon_hours} className={`q21-model-point state-${pointState(point.q21)}`} cx={x(point.horizon_hours)} cy={y(point.q21)} r="6"><title>{`${horizonLabel(point.horizon_hours)} · ${timeLabel(point.target_timestamp)} · ${formatNumber(point.q21, 2)} ppm`}</title></circle>)}
      {settings.showValues && forecasts.map(point => <text key={`value-${point.horizon_hours}`} className="q21-value-label" x={x(point.horizon_hours)} y={y(point.q21) - 14} textAnchor="middle">{formatNumber(point.q21, 2)}</text>)}
      {[-3, -2, -1, 0, 1, 2, 3, 6].map(hour => <text key={hour} className={`q21-axis-label ${hour === 0 ? 'q21-axis-now' : ''}`} x={x(hour)} y="311" textAnchor="middle">{hour < 0 ? `${hour} ч` : hour === 0 ? 'СЕЙЧАС' : `+${hour} ч`}</text>)}
    </svg><div className="q21-chart-legend"><span><i className="history" />Измерено</span><span><i className="forecast" />Прогноз модели</span>{settings.showInterval && interval && <span><i className="interval" />Интервал q10–q90 только для +1 ч</span>}</div></div>
    <div className="q21-horizon-board" aria-label="Прогноз по горизонтам">{forecasts.map(point => <div className={`q21-horizon q21-horizon-${pointState(point.q21)}`} key={point.horizon_hours}><span>{horizonLabel(point.horizon_hours)}</span><small>{timeLabel(point.target_timestamp)}</small><strong>{formatNumber(point.q21, 2)} <em>ppm</em></strong><b>{point.q21 >= LIMIT ? 'Выше предела' : point.q21 >= WATCH ? 'Следить' : 'В допуске'}</b></div>)}</div>
    <div className="q21-shadow-summary"><span>Закрыто прогнозов: <b>{runtime?.shadow_metrics.resolved ?? 0}</b></span>{runtime?.shadow_metrics.by_horizon.map(metric => <span key={metric.horizon_hours}>MAE {horizonLabel(metric.horizon_hours)}: <b>{formatNumber(metric.mae, 2)} ppm</b></span>)}</div>
    <p className="fineprint">Для +4 и +5 ч отдельных моделей нет: линия только соединяет известные расчёты. {interval ? 'Интервал q10–q90 рассчитан только для +1 ч; он не является погрешностью всех горизонтов.' : 'Интервал неопределённости для этого расчёта недоступен.'}</p>
  </section>
}
