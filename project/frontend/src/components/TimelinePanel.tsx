import { Clock, AlertTriangle, Info, TrendingUp } from 'lucide-react'
import { formatAge } from './ui'
import type { TimelineEvent } from '../hooks/useQ21WebSocket'

function EventIcon({ type }: { type: string }) {
  switch (type) {
    case 'forecast_generated':
      return <TrendingUp size={16} />
    case 'threshold_crossed':
    case 'alert_triggered':
      return <AlertTriangle size={16} />
    default:
      return <Info size={16} />
  }
}

function EventSeverityClass(severity: string): string {
  switch (severity) {
    case 'critical':
      return 'event-critical'
    case 'warning':
      return 'event-warning'
    default:
      return 'event-info'
  }
}

export function TimelinePanel({ events }: { events: TimelineEvent[] }) {
  if (events.length === 0) {
    return (
      <section className="panel timeline-panel">
        <div className="panel-heading">
          <h2>Лента событий</h2>
          <Clock size={20} />
        </div>
        <div className="timeline-empty">
          <p>События появятся здесь в реальном времени</p>
        </div>
      </section>
    )
  }

  return (
    <section className="panel timeline-panel">
      <div className="panel-heading">
        <h2>Лента событий</h2>
        <Clock size={20} />
      </div>
      <div className="timeline-list">
        {events.map((event) => (
          <div key={event.event_id} className={`timeline-event ${EventSeverityClass(event.severity)}`}>
            <div className="event-icon">
              <EventIcon type={event.event_type} />
            </div>
            <div className="event-content">
              <div className="event-header">
                <strong>{event.title}</strong>
                <span className="event-time">{formatAge((Date.now() - Date.parse(event.timestamp)) / 60000)}</span>
              </div>
              <p className="event-description">{event.description}</p>
              {event.data.q21 != null && event.data.forecast != null && (
                <div className="event-data">
                  Q21: {event.data.q21.toFixed(2)} → {event.data.forecast.toFixed(2)} ppm
                  {event.data.change != null && (
                    <span className={event.data.change > 0 ? 'change-up' : 'change-down'}>
                      {event.data.change > 0 ? '↑' : '↓'} {Math.abs(event.data.change).toFixed(2)}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
