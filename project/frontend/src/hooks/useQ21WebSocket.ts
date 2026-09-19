import { useEffect, useState } from 'react'

export interface Q21LiveData {
  q21_current: number
  q21_forecast_1h?: number
  exceedance_probability?: number
  risk_level: 'low' | 'medium' | 'high'
  shadow_mae?: number
  shadow_coverage?: number
}

export interface TimelineEvent {
  event_id: string
  timestamp: string
  event_type: string
  severity: 'info' | 'warning' | 'critical'
  title: string
  description: string
  data: Record<string, any>
}

export interface Alert {
  type: string
  severity: string
  message: string
  data: Record<string, any>
}

export function useQ21WebSocket(enabled: boolean = true) {
  const [data, setData] = useState<Q21LiveData | null>(null)
  const [events, setEvents] = useState<TimelineEvent[]>([])
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    if (!enabled) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/q21/live`)

    ws.onopen = () => {
      setConnected(true)
      console.log('[WebSocket] Connected to Q21 live feed')
    }

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data)

        switch (message.type) {
          case 'q21_update':
            setData(message.data)
            break

          case 'timeline_event':
            setEvents(prev => [message.event, ...prev].slice(0, 50))
            break

          case 'alert':
            setAlerts(prev => [message.alert, ...prev].slice(0, 10))
            // Auto-dismiss info alerts after 10 seconds
            if (message.alert.severity === 'info') {
              setTimeout(() => {
                setAlerts(prev => prev.filter(a => a !== message.alert))
              }, 10000)
            }
            break
        }
      } catch (err) {
        console.error('[WebSocket] Failed to parse message:', err)
      }
    }

    ws.onerror = (error) => {
      console.error('[WebSocket] Error:', error)
      setConnected(false)
    }

    ws.onclose = () => {
      setConnected(false)
      console.log('[WebSocket] Disconnected')
    }

    // Send ping every 30 seconds to keep connection alive
    const pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send('ping')
      }
    }, 30000)

    return () => {
      clearInterval(pingInterval)
      ws.close()
    }
  }, [enabled])

  return { data, events, alerts, connected }
}
