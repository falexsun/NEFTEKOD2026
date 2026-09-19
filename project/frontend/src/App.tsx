import { Component, useCallback, useEffect, useState, type ErrorInfo, type FormEvent, type ReactNode } from 'react'
import { RefreshCw } from 'lucide-react'
import { api, ApiError } from './api'
import { Shell, type View } from './components/Shell'
import { EmptyState, Skeleton } from './components/ui'
import { AlertBanner } from './components/AlertBanner'
import { TimelinePanel } from './components/TimelinePanel'
import { useQ21WebSocket } from './hooks/useQ21WebSocket'
import type { Control, Decision, Q21Runtime, Q21Status, Snapshot } from './types'
import { ShiftView } from './views/ShiftView'
import { ScenarioView } from './views/ScenarioView'
import { LoopsView } from './views/LoopsView'
import { JournalView } from './views/JournalView'

const views: View[] = ['shift', 'scenario', 'loops', 'journal']

function initialView(): View {
  const hash = window.location.hash.replace('#/', '').replace('#', '') as View
  return views.includes(hash) ? hash : 'shift'
}

class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error('Operator console error', error, info) }
  render() {
    if (this.state.failed) return <main className="fatal-state"><EmptyState title="Экран остановлен безопасно" detail="Произошла ошибка отображения. Технологические воздействия не выполнялись." state="critical" /><button className="primary" onClick={() => window.location.reload()}>Перезагрузить интерфейс</button></main>
    return this.props.children
  }
}

export function App() {
  const [view, setView] = useState<View>(initialView)
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [controls, setControls] = useState<Control[]>([])
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [q21Status, setQ21Status] = useState<Q21Status | null>(null)
  const [q21Runtime, setQ21Runtime] = useState<Q21Runtime | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [authRequired, setAuthRequired] = useState(false)
  const [apiKey, setApiKey] = useState('')

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const [nextSnapshot, controlResponse, decisionResponse, nextQ21Status, nextQ21Runtime] = await Promise.all([
        api.snapshot(),
        api.controls(),
        api.decisions().catch(caught => {
          if (caught instanceof ApiError && caught.status === 503) return { decisions: [], count: 0 }
          throw caught
        }),
        api.q21Status(),
        api.q21Runtime(),
      ])
      setSnapshot(nextSnapshot)
      setControls(controlResponse.controls)
      setDecisions(decisionResponse.decisions)
      setQ21Status(nextQ21Status)
      setQ21Runtime(nextQ21Runtime)
      setError(null)
      setAuthRequired(false)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'API недоступен')
      setAuthRequired(caught instanceof ApiError && caught.status === 401)
    } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(true), 15_000)
    return () => window.clearInterval(timer)
  }, [load])

  useEffect(() => {
    const onHash = () => setView(initialView())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const navigate = (next: View) => {
    window.location.hash = `/${next}`
    setView(next)
    window.scrollTo({ top: 0, behavior: 'auto' })
  }

  const authenticate = (event: FormEvent) => {
    event.preventDefault()
    window.sessionStorage.setItem('neftekod-api-key', apiKey.trim())
    void load()
  }

  if (loading && !snapshot) return <div className="boot-screen"><div className="logo"><span className="logo-mark">НК</span><span>НЕФТЕКОД<small>ЗАГРУЗКА ОПЕРАТИВНОГО СРЕЗА</small></span></div><Skeleton lines={4} /></div>
  if (!snapshot && authRequired) return <div className="boot-screen"><div className="logo"><span className="logo-mark">НК</span><span>НЕФТЕКОД<small>ЗАЩИЩЁННОЕ РАБОЧЕЕ МЕСТО</small></span></div><form className="auth-panel" onSubmit={authenticate}><label htmlFor="api-key">API-ключ оператора</label><input id="api-key" type="password" autoComplete="current-password" value={apiKey} onChange={event => setApiKey(event.target.value)} autoFocus /><p>Ключ хранится только в текущей вкладке браузера.</p><button className="primary" disabled={!apiKey.trim()}>Войти</button></form></div>
  if (!snapshot) return <div className="boot-screen"><EmptyState title="Нет связи с операторским API" detail={error ?? 'Проверьте состояние gateway и авторизацию.'} state="critical" /><button className="primary" onClick={() => void load()}><RefreshCw size={17} />Повторить</button></div>

  return <ErrorBoundary><Shell view={view} onNavigate={navigate} readiness={snapshot.readiness}>{error && <div className="connection-banner"><span>Обновление не выполнено: {error}. Показан последний полученный срез.</span><button onClick={() => void load()}><RefreshCw size={15} />Повторить</button></div>}{view === 'shift' && <ShiftView snapshot={snapshot} q21Status={q21Status} q21Runtime={q21Runtime} onScenario={() => navigate('scenario')} />}{view === 'scenario' && <ScenarioView controls={controls} readiness={snapshot.readiness} policy={snapshot.operating_policy} />}{view === 'loops' && <LoopsView controls={controls} />}{view === 'journal' && <JournalView decisions={decisions} />}</Shell></ErrorBoundary>
}
