import type { Snapshot } from '../types'
import { formatNumber, StatusBadge } from './ui'

export function FlowDiagnostics({ data }: { data: Snapshot['flow_diagnostics'] }) {
  if (!data) return null
  return <section className="panel flow-diagnostics">
    <div className="panel-heading"><div><span>АВТ</span><h2>Дизельная фракция · F30 / W70</h2></div><StatusBadge state={data.state} /></div>
    <p>{data.reason}</p>
    <dl className="flow-values">
      <div><dt>F30 · объёмный расход*</dt><dd>{formatNumber(data.f30, 2)}</dd></div>
      <div><dt>W70 · массовый расход*</dt><dd>{formatNumber(data.w70, 2)}</dd></div>
      <div><dt>Отношение W70 / F30</dt><dd>{formatNumber(data.w70_f30_ratio, 4)}</dd></div>
    </dl>
    <dl className="flow-values">
      <div><dt>Устойчивость расходов за час</dt><dd>{data.flow_stationary == null ? 'Нет оценки' : data.flow_stationary ? 'Устойчивы' : 'Меняются'}</dd></div>
      <div><dt>История за 30 дней</dt><dd>{data.baseline_days} / 7 дней</dd><small>{data.baseline_points} пригодных точек</small></div>
      <div><dt>Отклонение от медианы</dt><dd>{formatNumber(data.density_proxy_robust_z, 2)}</dd><small>Медиана отношения: {formatNumber(data.baseline_median, 4)}</small></div>
    </dl>
    <details><summary>Как оценивается согласованность</summary><p>За час нужны 6 измерений без больших пропусков и разброс расходов не более 5%. Для сравнения нужны минимум 7 дней с покрытием 70%. Сильное отклонение может означать смену состава или рассогласование датчиков. Пороги диагностические, не паспортные.</p></details>
    <p className="cell-note">* {data.note}</p>
    <p className="cell-note">Измерение АВТ: {data.timestamp ? new Date(data.timestamp).toLocaleString('ru-RU') : 'время неизвестно'}. Аппарат: К-2 / К-9.</p>
  </section>
}
