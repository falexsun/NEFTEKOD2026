import { ArrowRight, Check, CircleAlert, Database, Play, ShieldCheck } from 'lucide-react'
import type { Q21Runtime, Q21Status, Snapshot } from '../types'
import { OperatingModes } from '../components/OperatingModes'
import { FlowDiagnostics } from '../components/FlowDiagnostics'
import { Q21ForecastPanel } from '../components/Q21ForecastPanel'
import { EmptyState, formatAge, formatNumber, StatusBadge } from '../components/ui'

function Sparkline({ points }: { points: Snapshot['quality']['trend'] }) {
  if (points.length < 2) return <div className="chart-empty">Для тренда нужно минимум две точки</div>
  const values = points.map(point => point.value)
  const min = Math.min(...values, 0)
  const max = Math.max(...values, 10)
  const range = Math.max(1, max - min)
  const line = points.map((point, index) => `${(index / (points.length - 1)) * 100},${50 - ((point.value - min) / range) * 44}`).join(' ')
  const limitY = 50 - ((10 - min) / range) * 44
  return <svg className="sparkline" viewBox="0 0 100 52" preserveAspectRatio="none" role="img" aria-label="Тренд серы">
    <polyline points={line} fill="none" stroke="var(--amber)" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
    {limitY >= 0 && limitY <= 52 && <line x1="0" x2="100" y1={limitY} y2={limitY} stroke="var(--red)" strokeDasharray="2 3" strokeWidth=".7" vectorEffect="non-scaling-stroke" />}
  </svg>
}

function QualityHero({ snapshot }: { snapshot: Snapshot }) {
  const value = snapshot.quality.value
  const state = value == null ? 'unknown' : value >= 10 ? 'critical' : value >= 9 ? 'warning' : 'normal'
  return <section className="quality-hero">
    <div className="section-kicker"><span>К01</span> СЕРА В ТОВАРНОМ ДИЗЕЛЕ</div>
    <div className="quality-copy"><StatusBadge state={state}>{value == null ? 'Нет подтверждённого измерения' : value >= 10 ? 'Предел превышен' : value >= 9 ? 'Запас сокращается' : 'В допустимой зоне'}</StatusBadge><div className="quality-number">{formatNumber(value, 2)} <small>мг/кг</small></div><p>Источник: <b>{snapshot.quality.source ?? 'не определён'}</b></p></div>
    <div className="quality-chart"><Sparkline points={snapshot.quality.trend} /><div className="chart-label limit">Предел 10,0</div></div>
    <div className="forecast"><span>ГОТОВНОСТЬ ПРОГНОЗА</span><strong>{snapshot.readiness.prediction_ready ? 'ГОТОВ' : 'НЕТ'} </strong><p>{snapshot.readiness.history_ready ? 'История накоплена' : `${snapshot.buffer.points} из ${snapshot.buffer.required_points} точек · ${Math.round(snapshot.buffer.duration_minutes)} из ${snapshot.buffer.required_minutes} мин`}</p></div>
  </section>
}

function Recommendation({ snapshot, onScenario }: { snapshot: Snapshot; onScenario: () => void }) {
  if (!snapshot.operating_policy?.allowed) return <section className="recommendation unavailable-card"><EmptyState title="Рекомендации приостановлены" detail={snapshot.operating_policy?.reasons.join(' · ') ?? 'Режим установки не подтверждён'} state="warning" /></section>
  const record = snapshot.latest_decision
  if (!snapshot.readiness.optimization_ready) return <section className="recommendation unavailable-card"><EmptyState title="Рекомендация заблокирована" detail="Модель сценариев или вектор признаков не готовы. Система не подставляет демонстрационные значения." /></section>
  if (!record || record.recommendation_type !== 'recommendation') return <section className="recommendation unavailable-card"><EmptyState title="Актуальной рекомендации нет" detail={record?.data.reason ?? 'После появления нового технологического среза запустите цикл принятия решения.'} state="unknown" /></section>
  const changes = Object.entries(record.data.recommended_changes ?? {}) as Array<[string, { current: number; recommended: number; change: number }]>
  return <section className="recommendation">
    <div className="rec-index">{record.decision_id.slice(0, 8)}</div>
    <div className="rec-title"><div className="section-kicker">РЕКОМЕНДАЦИЯ · ПРОВЕРИТЬ ОПЕРАТОРУ</div><h1>{changes.length ? `Скорректировать ${changes.length} параметр${changes.length === 1 ? '' : 'а'}` : 'Сохранить текущий режим'}</h1><p>{record.data.explanation}</p></div>
    <div className="rec-actions">{changes.length ? changes.map(([name, change]) => <div className="change" key={name}><span>{name}</span><div><s>{formatNumber(change.current)}</s><ArrowRight size={18} /><strong>{formatNumber(change.recommended)}</strong></div><small>Изменение {formatNumber(change.change)}</small></div>) : <div className="change"><span>УПРАВЛЯЮЩИЕ ВОЗДЕЙСТВИЯ</span><strong>Не требуются</strong></div>}</div>
    <div className="rec-footer"><div className="confidence"><span>УВЕРЕННОСТЬ</span><strong>{record.data.confidence == null ? 'Не калибрована' : `${Math.round(record.data.confidence * 100)}%`}</strong><small>Решение {new Date(record.timestamp).toLocaleString('ru-RU')}</small></div><button className="primary" onClick={onScenario}><Play size={16} />Проверить сценарий</button></div>
  </section>
}

export function ShiftView({ snapshot, q21Status, q21Runtime, onScenario }: { snapshot: Snapshot; q21Status: Q21Status | null; q21Runtime: Q21Runtime | null; onScenario: () => void }) {
  const staleCount = snapshot.sources.filter(source => ['stale', 'critical', 'unknown'].includes(source.state)).length
  return <>
    <section className="shift-summary" aria-label="Сводка смены"><div className="summary-title"><span>ОПЕРАТИВНЫЙ СРЕЗ</span><strong>{snapshot.mode === 'live' ? 'Данные получены' : 'Нет технологических данных'}</strong></div><div className="summary-item"><Database size={17} /><span>Буфер признаков<strong>{snapshot.buffer.points} точек · {Math.round(snapshot.buffer.duration_minutes)} мин</strong></span></div><div className={`summary-item ${staleCount ? 'warning' : 'normal'}`}><CircleAlert size={17} /><span>Источники данных<strong>{staleCount ? `${staleCount} требуют внимания` : 'Все актуальны'}</strong></span></div><div className={`summary-item ${snapshot.readiness.storage_ready ? 'normal' : 'warning'}`}><ShieldCheck size={17} /><span>Аудит решений<strong>{snapshot.readiness.storage_ready ? 'Запись активна' : 'Хранилище недоступно'}</strong></span></div></section>
    {snapshot.mode === 'no_data' && <EmptyState title="Технологический срез ещё не поступил" detail="Экран не показывает вымышленные показания. Отправьте телеметрию через /decision или подключите источник данных." state="unknown" />}
    <OperatingModes policy={snapshot.operating_policy} />
    <div className="primary-workspace"><QualityHero snapshot={snapshot} /><Recommendation snapshot={snapshot} onScenario={onScenario} /></div>
    <FlowDiagnostics data={snapshot.flow_diagnostics} />
    <section className="panel q21-runtime"><div><span className="eyebrow">SHADOW PIPELINE · Q21</span><h2>{q21Status?.ready ? 'Пять горизонтов прогноза загружены' : 'Контур Q21 недоступен'}</h2><p>{q21Status?.ready ? `Основной h=1 · Risk λ=${q21Status.risk_lambda}, порог ${formatNumber(q21Status.risk_threshold, 3)} · 80% интервал ${q21Status.uncertainty_ready ? 'готов' : 'недоступен'}. Без передачи уставок.` : q21Status?.error ?? 'Статус модели не получен.'}</p></div><div><StatusBadge state={q21Status?.ready ? 'normal' : 'unavailable'}>{q21Status?.ready ? 'SHA проверен' : 'Недоступен'}</StatusBadge><small>Доступные горизонты: {q21Status?.available_horizons_hours.map(value => `${value} ч`).join(', ') || 'нет'}</small><small>Не подключены: {q21Status?.missing_artifacts.join(', ') || 'нет'}</small></div></section>
    <Q21ForecastPanel runtime={q21Runtime} />
    <section className="evidence-grid">
      <div className="freshness panel"><div className="panel-heading"><div><span>03</span><h2>Свежесть источников</h2></div></div>{snapshot.sources.map(source => <div className="source" key={source.id}><div><i className={`state-dot state-${source.state}`} /><span>{source.label}<small>{source.timestamp ? new Date(source.timestamp).toLocaleString('ru-RU') : 'Отметка времени отсутствует'}</small></span></div><strong>{formatAge(source.age_minutes)}</strong><StatusBadge state={source.state} /></div>)}</div>
      <div className="constraints panel"><div className="panel-heading"><div><span>04</span><h2>Готовность контура</h2></div><ShieldCheck size={24} /></div><ul>{[
        ['Модель качества', snapshot.readiness.quality_model_ready], ['История признаков', snapshot.readiness.history_ready], ['Схема признаков', snapshot.readiness.runtime_schema_ready], ['Модель сценариев', snapshot.readiness.optimization_ready], ['Журнал аудита', snapshot.readiness.storage_ready],
      ].map(([label, ready]) => <li key={String(label)}>{ready ? <Check size={16} /> : <CircleAlert size={16} />}<div><strong>{label}</strong><span>{ready ? 'Готово' : 'Недоступно или прогревается'}</span></div></li>)}</ul><div className="assumption"><CircleAlert size={17} /><p><strong>Безопасный отказ</strong>При неполных данных рекомендация и what-if расчёт блокируются.</p></div></div>
    </section>
  </>
}
