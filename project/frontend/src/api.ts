import type { Control, Decision, Q21Runtime, Q21Status, ScenarioResult, Snapshot } from './types'

const base = import.meta.env.DEV ? '/api' : ''

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const key = window.sessionStorage.getItem('neftekod-api-key')
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(key ? { 'X-API-Key': key } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    let message = `Ошибка API (${response.status})`
    try {
      const body = await response.json()
      message = typeof body.detail === 'string' ? body.detail : message
    } catch { /* response has no JSON body */ }
    throw new ApiError(message, response.status)
  }
  return response.json() as Promise<T>
}

export const api = {
  snapshot: () => request<Snapshot>('/operator/snapshot'),
  controls: () => request<{ controls: Control[]; count: number }>('/controls'),
  decisions: () => request<{ decisions: Decision[]; count: number }>('/decisions?limit=100'),
  q21Status: () => request<Q21Status>('/q21/status'),
  q21Runtime: () => request<Q21Runtime>('/q21/runtime'),
  scenario: (action: Record<string, number>, baseline_timestamp: string, signal: AbortSignal) => request<ScenarioResult>('/scenarios/evaluate', {
    method: 'POST', body: JSON.stringify({ action, baseline_timestamp }), signal,
  }),
}
