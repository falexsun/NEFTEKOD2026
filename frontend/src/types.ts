export type SemanticState = 'normal' | 'attention' | 'warning' | 'critical' | 'stale' | 'unknown' | 'unavailable'

export type Readiness = {
  ready: boolean
  prediction_ready: boolean
  quality_model_ready: boolean
  history_ready: boolean
  runtime_schema_ready: boolean
  optimization_ready: boolean
  surrogate_ready: boolean
  storage_ready: boolean
}

export type SourceState = {
  id: string
  label: string
  timestamp: string | null
  age_minutes: number | null
  state: SemanticState
}

export type Decision = {
  decision_id: string
  timestamp: string
  recommendation_type: 'recommendation' | 'abstain' | 'scenario' | string
  actor: string
  request_id: string
  data: Record<string, any>
}

export type Snapshot = {
  operating_policy?: OperatingPolicy
  flow_diagnostics?: {
    state: SemanticState; reason: string; note: string; timestamp: string | null;
    f30: number | null; w70: number | null; w70_f30_ratio: number | null;
    density_proxy_kg_m3: number | null; density_proxy_valid: boolean;
    flow_stationary: boolean | null; baseline_ready: boolean;
    baseline_days: number; baseline_points: number; baseline_median: number | null;
    density_proxy_robust_z: number | null; flowmeter_disagreement: boolean | null;
  }
  timestamp: string
  mode: 'live' | 'no_data'
  readiness: Readiness
  quality: {
    value: number | null
    unit: string
    source: string | null
    trend: Array<{ timestamp: string; value: number }>
  }
  sources: SourceState[]
  latest_decision: Decision | null
  buffer: { points: number; duration_minutes: number; required_points: number; required_minutes: number }
}

export type Control = {
  snapshot_timestamp?: string
  topology?: { equipment: string; stream: string; review_note?: string; source_file: string; provenance: string } | null
  id: string
  label: string
  stage: string
  unit: string
  min: number
  max: number
  max_step: number
  max_rate_of_change: number | null
  source: string
  confidence: 'high' | 'medium' | 'low'
  current: number | null
  available: boolean
}

export type ScenarioResult = {
  horizon_minutes: number
  baseline_timestamp: string
  scenario_id: string
  timestamp: string
  status: 'safe' | 'rejected'
  action: Record<string, number>
  predicted_sulfur: number
  sulfur_std: number
  violation_probability: number
  reliability_risk: number
  data_quality_score: number
  constraints: { allowed: boolean; violations: string[]; warnings: string[] }
  production_effect: number | null
  energy_effect: number | null
  model_version: string
}

export type OperatingPolicy = {
  allowed: boolean
  disposition: 'EVALUATE' | 'NO_ACTION' | 'ABSTAIN'
  reasons: string[]
  description: string
  units: Array<{ id: string; label: string; mode: string; mode_label: string; fresh: boolean }>
}

export type Q21Status = {
  ready: boolean
  error?: string | null
  available_horizons_hours: number[]
  risk_ready: boolean
  uncertainty_ready: boolean
  risk_lambda?: number
  risk_threshold?: number
  missing_artifacts: string[]
  mode?: string
}

export type Q21Runtime = {
  data_state: 'empty' | 'live' | 'historical'
  points: number
  required_points: number
  latest_point: ({ timestamp: string; Q21: number; operating_mode: string } & Record<string, unknown>) | null
  latest_forecast: {
    origin_timestamp: string
    forecast_id: string
    forecasts: Array<{ horizon_hours: number; target_timestamp: string; q21: number; lower: number | null; upper: number | null; actual: number | null; absolute_error: number | null }>
  } | null
  shadow_metrics: { resolved: number; by_horizon: Array<{ horizon_hours: number; n: number; mae: number; interval_coverage: number | null }> }
}
