// Wrapper unifie pour les notifications OS :
//   - En desktop (Tauri) : utilise @tauri-apps/plugin-notification
//     (toast Windows Action Center, NSUserNotifications macOS)
//   - Sinon : Notification API du navigateur (fonctionne aussi pour PWA)
//
// Le wrapper detecte automatiquement le contexte. Aucune dependance Tauri
// n'est importee si l'app tourne en pur web (fallback dynamique).

declare global {
  interface Window {
    __TAURI__?: unknown
    __TAURI_INTERNALS__?: unknown
  }
}

interface TauriNotifModule {
  isPermissionGranted: () => Promise<boolean>
  requestPermission: () => Promise<string>
  sendNotification: (opts: { title: string; body: string }) => void
}

/** True si l'app tourne dans Tauri (desktop). */
export function isTauri(): boolean {
  if (typeof window === 'undefined') return false
  return !!(window.__TAURI__ || window.__TAURI_INTERNALS__)
}

export type NotificationPermission = 'granted' | 'denied' | 'default'

/**
 * Demande la permission de notifier. Idempotent.
 * En Tauri : appelle requestPermission de tauri-plugin-notification.
 * En web : appelle Notification.requestPermission.
 */
export async function requestNotificationPermission(): Promise<NotificationPermission> {
  if (isTauri()) {
    try {
      // Le package n'est pas dans frontend/node_modules (il est cote desktop),
      // Vite ne peut pas le resoudre au build. On construit le nom comme
      // expression pour bypasser l'analyse statique ; a runtime l'import
      // echoue gracieusement si on n'est pas dans Tauri.
      const PKG = ['@tauri-apps', 'plugin-notification'].join('/')
      const mod = await import(/* @vite-ignore */ PKG) as unknown as TauriNotifModule
      const granted = await mod.isPermissionGranted()
      if (granted) return 'granted'
      const result = await mod.requestPermission()
      return result === 'granted' ? 'granted' : result === 'denied' ? 'denied' : 'default'
    } catch {
      return 'denied'
    }
  }
  if (typeof Notification === 'undefined') return 'denied'
  if (Notification.permission === 'granted') return 'granted'
  if (Notification.permission === 'denied') return 'denied'
  try {
    const result = await Notification.requestPermission()
    return result
  } catch {
    return 'denied'
  }
}

/**
 * Lance une notification OS native.
 * Le caller est responsable d'avoir demande la permission au prealable
 * (sinon silent fail).
 */
export async function notify(title: string, body: string, opts: { icon?: string; tag?: string } = {}): Promise<void> {
  if (isTauri()) {
    try {
      const PKG = ['@tauri-apps', 'plugin-notification'].join('/')
      const mod = await import(/* @vite-ignore */ PKG) as unknown as TauriNotifModule
      const granted = await mod.isPermissionGranted()
      if (!granted) return
      mod.sendNotification({ title, body })
    } catch { /* swallow */ }
    return
  }
  if (typeof Notification === 'undefined') return
  if (Notification.permission !== 'granted') return
  try {
    new Notification(title, { body, icon: opts.icon, tag: opts.tag })
  } catch {
    // swallow
  }
}

/**
 * Notification "tracking période" RICHE avec actions cliquables (boutons
 * A/B/Aucun directement dans la notif). Passe par le service worker car
 * la constructeur Notification() basique ne supporte PAS les actions.
 *
 * Click sur une action -> le SW POST /respond + open /tracking.
 * Click sur le corps -> open /tracking.
 *
 * Fallback : si SW indisponible, on degrade vers notify() classique.
 */
export async function notifyTrackingPeriod(payload: {
  tracking_id: string
  periode_idx: number
  question: string
  actions: { id: string; label: string }[]  // [{id:'0', label:'Option A'}, ..., {id:'none', label:'Aucun des deux'}]
  is_retry: boolean
  token?: string
  csrf?: string
}): Promise<void> {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return

  // Tentative via service worker (= actions cliquables)
  if ('serviceWorker' in navigator) {
    try {
      const reg = await navigator.serviceWorker.getRegistration('/')
        || await navigator.serviceWorker.register('/sylea-sw.js', { scope: '/' })
      if (reg) {
        // Limit a 3 actions max (limite courante des navigateurs)
        const actions = payload.actions.slice(0, 3).map(a => ({
          action: a.id,
          title: a.label.length > 24 ? a.label.slice(0, 21) + '...' : a.label,
        }))
        await reg.showNotification(
          payload.is_retry ? 'Sylea — rappel période' : 'Sylea — une période à renseigner',
          {
            body: payload.question.slice(0, 120),
            icon: '/sylea-logo.svg',
            badge: '/sylea-logo.svg',
            tag: `sylea-tracking-${payload.tracking_id}-${payload.periode_idx}`,
            requireInteraction: true,
            data: {
              tracking_id: payload.tracking_id,
              periode_idx: payload.periode_idx,
              token: payload.token,
              csrf: payload.csrf,
              url: '/tracking',
            },
            actions,
          } as NotificationOptions & { actions?: { action: string; title: string }[] },
        )
        return
      }
    } catch { /* fallback ci-dessous */ }
  }

  // Fallback : notif simple sans actions
  await notify(
    payload.is_retry ? 'Sylea — rappel période' : 'Sylea — période à renseigner',
    payload.question.slice(0, 120),
    { icon: '/sylea-logo.svg', tag: `sylea-tracking-${payload.tracking_id}` },
  )
}
