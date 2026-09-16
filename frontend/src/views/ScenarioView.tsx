import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { Check, CircleAlert, LoaderCircle, Minus, Plus, RotateCcw, ShieldCheck, Sparkles } from 'lucide-react'
import { api } from '../api'
import type { Control, OperatingPolicy, Readiness, ScenarioResult } from '../types'
import { displayUnit, EmptyState, formatNumber, StatusBadge } from '../components/ui'

import { OperatingModes } from '../components/OperatingModes'

function stepFor(control: Control) { return Number.isInteger(control.max_step) ? 1 : 0.1 }

function ParameterInput({ control, value, onChange }: { control: Control; value: number; onChange: (value: number) => void }) {
  const min = Math.max(control.min, (control.current ?? control.min) - control.max_step)
  const max = Math.min(control.max, (control.current ?? control.max) + control.max_step)
  const step = stepFor(control)
  const safeChange = (next: number) => onChange(Math.min(max, Math.max(min, Number(next.toFixed(step < 1 ? 1 : 0)))))
  const range = max - min || 1
  const position = ((value - min) / range) * 100
  const baseline = (((control.current ?? min) - min) / range) * 100
  return <article className="control-row">
    <div className="control-name"><span>{control.topology?.equipment ?? control.stage} · {control.id}</span><h3>{control.label}</h3>{control.topology && <p className="cell-note">{control.topology.stream}</p>}<small>{control.source === 'expert' ? 'Экспертный модельный диапазон' : control.source} · уверенность {control.confidence}</small>{control.topology?.review_note && <p className="topology-note">{control.topology.review_note}</p>}</div>
    <div className="control-input">
      <div className="numeric-control"><button type="button" onClick={() => safeChange(value - step)} aria-label={`Уменьшить ${control.label}`}><Minus size={17} /></button><label><span>Новое значение</span><input type="number" min={min} max={max} step={step} value={value} onChange={event => safeChange(Number(event.target.value))} aria-describedby={`${control.id}-limits`} /></label><b>{displayUnit(control.unit)}</b><button type="button" onClick={() => safeChange(value + step)} aria-label={`Увеличить ${control.label}`}><Plus size={17} /></button></div>
      <input className="parameter-range" type="range" min={min} max={max} step={step} value={value} style={{ '--range': `${position}%` } as CSSProperties} onChange={event => safeChange(Number(event.target.value))} aria-label={control.label} aria-valuetext={`${value} ${displayUnit(control.unit)}`} />
      <div className="range-meta" id={`${control.id}-limits`}><span>{formatNumber(min)} — {formatNumber(max)} {displayUnit(control.unit)}</span><span className="baseline" style={{ left: `${baseline}%` }}>текущее {formatNumber(control.current)}</span></div>
    </div>
  </article>
}

export function ScenarioView({ controls, readiness, policy }: { controls: Control[]; readiness: Readiness; policy?: OperatingPolicy }) {
  const available = controls.filter(control => control.available && control.current != null)
  const [activeIds, setActiveIds] = useState<string[]>([])
  const [values, setValues] = useState<Record<string, number>>({})
  const [result, setResult] = useState<ScenarioResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const pending = useRef<AbortController | null>(null)
  const invalidate = () => { pending.current?.abort(); pending.current = null; setLoading(false); setResult(null); setError(null) }
  const baseline = available[0]?.snapshot_timestamp
  const availableRevision = available.map(control => `${control.id}:${control.current}:${control.snapshot_timestamp}`).join('|')

  useEffect(() => {
    invalidate()
    setActiveIds(available.map(control => control.id))
    setValues(Object.fromEntries(available.map(control => [control.id, control.current as number])))
    setResult(null)
    setError(null)
  }, [availableRevision])

  useEffect(() => { invalidate() }, [policy?.allowed, readiness.optimization_ready])
  useEffect(() => () => { pending.current?.abort(); pending.current = null }, [])

  const selected = useMemo(() => available.filter(control => activeIds.includes(control.id)), [available, activeIds])
  const action = Object.fromEntries(selected.filter(control => values[control.id] !== control.current).map(control => [control.id, values[control.id]]))
  const canRun = policy?.allowed && baseline && readiness.optimization_ready && Object.keys(action).length > 0 && !loading

  const reset = () => { invalidate(); setValues(Object.fromEntries(available.map(control => [control.id, control.current as number]))); setResult(null); setError(null) }
  const toggleControl = (control: Control) => {
    invalidate()
    const active = activeIds.includes(control.id)
    setActiveIds(current => active ? current.filter(id => id !== control.id) : [...current, control.id])
    // A hidden parameter is not part of the scenario. Reset it immediately so
    // a stale edit cannot reappear when the chip is enabled again.
    setValues(current => ({ ...current, [control.id]: control.current as number }))
    setResult(null)
    setError(null)
  }
  const run = async () => {
    if (!canRun || !baseline) return
    const request = new AbortController()
    pending.current = request
    setLoading(true); setError(null)
    try {
      const response = await api.scenario(action, baseline, request.signal)
      if (pending.current === request) setResult(response)
    } catch (caught) {
      if (pending.current === request && !request.signal.aborted) { setResult(null); setError(caught instanceof Error ? caught.message : 'Расчёт не выполнен') }
    } finally { if (pending.current === request) { pending.current = null; setLoading(false) } }
  }

  return <section className="workspace-view scenario-view">
    <div className="view-heading"><div><div className="section-kicker"><span>С02</span> WHAT—IF</div><h1>Проверка сценария</h1><p>Исследовательская оценка по историческим данным. Действующее регулирование влияет на зависимости: изменение прогноза не подтверждает причинный эффект изменения уставки.</p></div><button className="ghost" onClick={reset}><RotateCcw size={16} />Вернуть текущие</button></div>
    <OperatingModes policy={policy} />
    {!readiness.optimization_ready && <EmptyState title="Расчёт сценариев недоступен" detail="Нужно дождаться модели, полной истории и корректной схемы признаков. Управляющие элементы остаются видимыми для проверки диапазонов." state="warning" />}
    <div className="parameter-picker"><div><strong>Параметры сценария</strong><span>Выбрано {activeIds.length} из {available.length} доступных</span></div><div className="parameter-chips">{controls.map(control => {
      const active = activeIds.includes(control.id)
      return <button key={control.id} disabled={!control.available} className={active ? 'active' : ''} aria-pressed={active} onClick={() => toggleControl(control)}><i>{control.stage === 'AVT' ? 'АВТ' : '24'}</i>{control.id}{active && <Check size={14} />}{!control.available && <span>нет сигнала</span>}</button>
    })}</div></div>
    <div className="scenario-grid"><div className="control-board">{selected.length ? selected.map(control => <ParameterInput key={control.id} control={control} value={values[control.id]} onChange={value => { invalidate(); setValues(current => ({ ...current, [control.id]: value })); setResult(null) }} />) : <EmptyState title="Нет выбранных параметров" detail="Выберите один или несколько доступных параметров выше." state="unknown" />}</div>
      <aside className="scenario-result" aria-live="polite"><span className="eyebrow">РАСЧЁТНЫЙ РЕЗУЛЬТАТ</span>{error && <div className="inline-error"><CircleAlert size={18} /><span><strong>Расчёт остановлен</strong>{error}</span></div>}{result ? <>
        <div className="result-main"><small>Сера через {result.horizon_minutes} мин</small><strong>{formatNumber(result.predicted_sulfur, 2)} <em>мг/кг</em></strong><StatusBadge state={result.status === 'safe' ? 'normal' : 'critical'}>{result.status === 'safe' ? 'Сценарий допущен' : 'Сценарий отклонён'}</StatusBadge></div>
        <dl className="result-facts"><div><dt>Вероятность нарушения</dt><dd>{formatNumber(result.violation_probability * 100, 1)}%</dd></div><div><dt>Риск оборудования</dt><dd>{formatNumber(result.reliability_risk, 2)} / 1</dd></div><div><dt>Качество данных</dt><dd>{formatNumber(result.data_quality_score * 100, 0)} / 100</dd></div></dl>
        <ul>{result.constraints.violations.length ? result.constraints.violations.map(item => <li className="violation" key={item}><CircleAlert size={15} />{item}</li>) : <li><ShieldCheck size={15} />Проверки безопасности пройдены</li>}<li className="neutral-check">Выпуск и энергия: модель эффекта отсутствует</li></ul>
      </> : <EmptyState title="Сценарий ещё не рассчитан" detail={Object.keys(action).length ? `Изменено параметров: ${Object.keys(action).length}` : 'Измените хотя бы одно значение.'} state="unknown" />}
      <button className="primary wide" disabled={!canRun} onClick={run}>{loading ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}{loading ? 'Выполняется проверка…' : 'Рассчитать на сервере'}</button><p className="fineprint">Результат сохраняется в журнал с версией модели и идентификатором запроса.</p></aside>
    </div>
  </section>
}
