// Hook qui ouvre une connexion WebSocket au backend pour recevoir
// les notifications tracking en temps reel (au lieu de poller toutes
// les 30s). Reconnect automatique avec backoff exponentiel.
//
// Les types d'evenements ecoutes :
//   - dilemme_tracking_period           (J+30, J+60... une periode est due)
//   - dilemme_tracking_validation_reminder (D+3 : recap a valider)
//   - dilemme_tracking_auto_validated    (D+7 : auto-validation)

import { useEffect, useRef } from 'react'

const WS_PATH = '/ws/agent'
const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30_000
const PING_INTERVAL_MS = 25_000  // < 30s qui est le timeout serveur typique

export type TrackingWsEvent =
  | { type: 'dilemme_tracking_period'; tracking_id: string; periode_idx: number; question: string; actions: { id: string; label: string }[]; is_retry: boolean; nb_periodes: number; timestamp: string }
  | { type: 'dilemme_tracking_validation_reminder'; tracking_id: string; question: string; timestamp: string }
  | { type: 'dilemme_tracking_auto_validated'; tracking_id: string; question: string; impact_jours_applique: number; delta_probabilite: number; timestamp: string }
  | { type: 'connected'; message: string }
  | { type: string; [k: string]: unknown } // catch-all pour autres events

interface UseTrackingWebSocketOptions {
  /** Token JWT pour s'authentifier. Si null, ne se connecte pas. */
  token: string | null
  /** Callback appele a chaque event tracking recu. */
  onEvent: (event: TrackingWsEvent) => void
  /** Si true, log les events dans la console (debug). */
  debug?: boolean
}

/**
 * Construit l'URL WebSocket a partir de l'URL HTTP courante.
 */
function buildWsUrl(token: string): string {
  // En dev : Vite proxy /ws -> http://127.0.0.1:8000/ws (cf. vite.config.ts).
  // Sinon on construit a partir de location.
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host  // ex: localhost:5173
  return `${proto}//${host}${WS_PATH}?token=${encodeURIComponent(token)}`
}

export function useTrackingWebSocket({ token, onEvent, debug = false }: UseTrackingWebSocketOptions): void {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const reconnectTimeoutRef = useRef<number | null>(null)
  const pingIntervalRef = useRef<number | null>(null)
  const shouldReconnectRef = useRef(true)
  // Conserve la derniere version de onEvent (evite reconnect si l'identite change)
  const onEventRef = useRef(onEvent)
  useEffect(() => { onEventRef.current = onEvent }, [onEvent])

  useEffect(() => {
    if (!token) return
    shouldReconnectRef.current = true

    const connect = () => {
      if (!shouldReconnectRef.current) return
      const url = buildWsUrl(token)
      if (debug) console.log('[tracking-ws] connecting to', url)
      try {
        const ws = new WebSocket(url)
        wsRef.current = ws

        ws.onopen = () => {
          if (debug) console.log('[tracking-ws] open')
          reconnectAttemptsRef.current = 0
          // Ping periodique (le backend repond pong)
          if (pingIntervalRef.current) window.clearInterval(pingIntervalRef.current)
          pingIntervalRef.current = window.setInterval(() => {
            try { ws.send('ping') } catch { /* swallow */ }
          }, PING_INTERVAL_MS)
        }

        ws.onmessage = (e) => {
          if (e.data === 'pong') return
          try {
            const event = JSON.parse(e.data) as TrackingWsEvent
            if (debug) console.log('[tracking-ws] event', event)
            onEventRef.current(event)
          } catch (err) {
            if (debug) console.warn('[tracking-ws] parse fail', err, e.data)
          }
        }

        ws.onerror = (err) => {
          if (debug) console.warn('[tracking-ws] error', err)
        }

        ws.onclose = (e) => {
          if (debug) console.log('[tracking-ws] closed', e.code, e.reason)
          if (pingIntervalRef.current) {
            window.clearInterval(pingIntervalRef.current)
            pingIntervalRef.current = null
          }
          wsRef.current = null
          if (!shouldReconnectRef.current) return
          if (e.code === 4001) {
            // Token invalide → ne pas reconnect
            if (debug) console.warn('[tracking-ws] auth failed, stop reconnecting')
            return
          }
          // Backoff exponentiel : 1s, 2s, 4s, ... max 30s
          const delay = Math.min(
            RECONNECT_MAX_MS,
            RECONNECT_BASE_MS * Math.pow(2, reconnectAttemptsRef.current),
          )
          reconnectAttemptsRef.current += 1
          if (debug) console.log(`[tracking-ws] reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current})`)
          reconnectTimeoutRef.current = window.setTimeout(connect, delay)
        }
      } catch (err) {
        if (debug) console.warn('[tracking-ws] new WebSocket() threw', err)
      }
    }

    connect()

    return () => {
      shouldReconnectRef.current = false
      if (reconnectTimeoutRef.current) {
        window.clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
      if (pingIntervalRef.current) {
        window.clearInterval(pingIntervalRef.current)
        pingIntervalRef.current = null
      }
      if (wsRef.current) {
        try { wsRef.current.close(1000, 'unmount') } catch { /* swallow */ }
        wsRef.current = null
      }
    }
  }, [token, debug])
}
