import { X, AlertTriangle, AlertCircle, Info } from 'lucide-react'
import type { Alert } from '../hooks/useQ21WebSocket'

function AlertIcon({ severity }: { severity: string }) {
  switch (severity) {
    case 'critical':
      return <AlertTriangle size={20} />
    case 'warning':
      return <AlertCircle size={20} />
    default:
      return <Info size={20} />
  }
}

function AlertSeverityClass(severity: string): string {
  switch (severity) {
    case 'critical':
      return 'alert-critical'
    case 'warning':
      return 'alert-warning'
    default:
      return 'alert-info'
  }
}

export function AlertBanner({ alerts, onDismiss }: { alerts: Alert[]; onDismiss: (alert: Alert) => void }) {
  if (alerts.length === 0) return null

  return (
    <div className="alert-container">
      {alerts.map((alert, index) => (
        <div key={index} className={`alert-banner ${AlertSeverityClass(alert.severity)}`}>
          <div className="alert-icon">
            <AlertIcon severity={alert.severity} />
          </div>
          <div className="alert-content">
            <strong>{alert.type}</strong>
            <p>{alert.message}</p>
          </div>
          <button className="alert-close" onClick={() => onDismiss(alert)} aria-label="Закрыть">
            <X size={18} />
          </button>
        </div>
      ))}
    </div>
  )
}
