import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import type { Decision } from '../types'
import { EmptyState, formatNumber, presentReason, presentViolation } from '../components/ui'

function title(record: Decision) {
  if (record.recommendation_type === 'no_action') return 'Оптимизация приостановлена по режиму установки'
  if (record.recommendation_type === 'abstain') return 'Система отказалась от рекомендации'
  if (record.recommendation_type === 'scenario') return `What-if сценарий: ${record.data.status === 'safe' ? 'допущен' : 'отклонён'}`
  const changes = Object.keys(record.data.recommended_changes ?? {})
  return changes.length ? `Рекомендация по ${changes.join(', ')}` : 'Сохранить текущий режим'
}

function description(record: Decision) {
  if (record.data.reason) return presentReason(record.data.reason)
  if (record.data.predicted_sulfur != null) return `Сера ${formatNumber(record.data.predicted_sulfur, 2)} мг/кг · риск ${formatNumber((record.data.violation_probability ?? 0) * 100, 1)}%`
  if (record.data.expected_quality?.sulfur != null) return `Ожидаемая сера ${formatNumber(record.data.expected_quality.sulfur, 2)} мг/кг`
  return record.data.explanation ?? 'Подробности сохранены в записи аудита'
}

export function JournalView({ decisions }: { decisions: Decision[] }) {
  const [selected, setSelected] = useState<string | null>(null)
  return <section className="workspace-view"><div className="view-heading"><div><div className="section-kicker"><span>Ж04</span> АУДИТ</div><h1>Журнал решений</h1><p>Неизменяемые записи входного запроса, результата модели, проверок и инициатора действия.</p></div><div className="large-score"><span>{decisions.length}</span>записей загружено</div></div>{decisions.length ? <div className="journal-list">{decisions.map(record => {
    const expanded = selected === record.decision_id
    return <div className="journal-entry" key={record.decision_id}><article role="button" aria-expanded={expanded} tabIndex={0} onClick={() => setSelected(expanded ? null : record.decision_id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelected(expanded ? null : record.decision_id) } }}><time dateTime={record.timestamp}>{new Date(record.timestamp).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</time><span className={`decision-type ${record.recommendation_type === 'recommendation' ? 'recommendation-type' : record.recommendation_type === 'abstain' ? 'abstain' : 'no-action'}`}>{record.recommendation_type === 'recommendation' ? 'Рекомендация' : record.recommendation_type === 'abstain' ? 'Отказ' : record.recommendation_type === 'no_action' ? 'Без воздействия' : 'Сценарий'}</span><div><h3>{title(record)}</h3><p>{description(record)}</p><small>ID {record.decision_id.slice(0, 8)} · {record.actor}</small></div><b>{new Date(record.timestamp).toLocaleDateString('ru-RU')}</b><ChevronRight className={expanded ? 'rotated' : ''} size={18} /></article>{expanded && <div className="decision-details"><dl><div><dt>Decision ID</dt><dd>{record.decision_id}</dd></div><div><dt>Request ID</dt><dd>{record.request_id}</dd></div><div><dt>Версия модели</dt><dd>{record.data.model_version ?? record.data.model_versions?.quality ?? 'не указана'}</dd></div></dl>{record.data.constraints?.violations?.length > 0 && <div className="detail-warning"><strong>Нарушенные ограничения</strong>{record.data.constraints.violations.map((item: string) => presentViolation(item)).join(' · ')}</div>}<p>{record.data.explanation ?? (record.data.reason ? presentReason(record.data.reason) : 'Дополнительное объяснение отсутствует.')}</p></div>}</div>
  })}</div> : <EmptyState title="Журнал пока пуст" detail="Здесь появятся решения оркестратора и выполненные what-if расчёты." state="unknown" />}</section>
}
