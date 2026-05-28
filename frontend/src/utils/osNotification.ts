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
      // Le package n'est pas dans frontend/node_modules (il est cote desktop),
      // Vite ne peut pas le resoudre au build. On construit le nom comme
      // expression pour bypasser l'analyse statique ; a runtime l'import
      // echoue gracieusement si on n'est pas dans Tauri.
      const PKG = ['@tauri-apps', 'plugin-notification'].join('/')
      const mod = await import(/* @vite-ignore */ PKG) as unknown as TauriNotifModule
      const granted = await mod.isPermissionGranted()
      if (!granted) return
      mod.sendNotification({ title, body })
    } catch {
      // swallow
    }
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
