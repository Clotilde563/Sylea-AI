// Web Push (PWA mobile) : registration du service worker + souscription
// au push manager + POST /api/notifications/subscribe au backend.
//
// Le backend (api/routers/notifications.py) implemente deja l'endpoint
// /api/notifications/subscribe qui stocke la PushSubscription dans la
// table push_subscriptions. Il utilise pywebpush pour pousser les notifs
// avec VAPID (clef publique exposee via /api/notifications/vapid-public-key).

interface VapidKeyResp {
  publicKey: string
}

/**
 * Convertit une clef VAPID base64 url en Uint8Array (format attendu par
 * pushManager.subscribe).
 */
function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - base64String.length % 4) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = atob(base64)
  const arr = new Uint8Array(rawData.length)
  for (let i = 0; i < rawData.length; i++) arr[i] = rawData.charCodeAt(i)
  return arr
}

/**
 * Verifie si le navigateur supporte les push notifications.
 */
export function isPushSupported(): boolean {
  return (
    typeof window !== 'undefined'
    && 'serviceWorker' in navigator
    && 'PushManager' in window
    && 'Notification' in window
  )
}

/**
 * Enregistre le service worker. Idempotent.
 */
export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!isPushSupported()) return null
  try {
    const reg = await navigator.serviceWorker.register('/sylea-sw.js', { scope: '/' })
    // Attente que le SW soit actif
    if (reg.installing) {
      await new Promise<void>((resolve) => {
        const w = reg.installing!
        w.addEventListener('statechange', () => {
          if (w.state === 'activated') resolve()
        })
      })
    }
    return reg
  } catch (e) {
    console.warn('[webpush] register SW failed:', e)
    return null
  }
}

/**
 * Souscrit au push manager + POST au backend.
 * A appeler apres requestNotificationPermission().
 */
export async function subscribeWebPush(token: string): Promise<PushSubscription | null> {
  if (!isPushSupported()) return null
  if (Notification.permission !== 'granted') return null
  try {
    const reg = await registerServiceWorker()
    if (!reg) return null
    // Verifie si deja souscrit
    const existing = await reg.pushManager.getSubscription()
    if (existing) return existing
    // Recupere la clef VAPID publique
    const r = await fetch('/api/notifications/vapid-public-key', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!r.ok) {
      console.warn('[webpush] vapid key fetch failed:', r.status)
      return null
    }
    const { publicKey } = (await r.json()) as VapidKeyResp
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    })
    // Envoie au backend
    const csrf = decodeURIComponent((document.cookie.match(/sylea_csrf=([^;]+)/) || [])[1] || '')
    await fetch('/api/notifications/subscribe', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
      },
      body: JSON.stringify(sub.toJSON()),
      credentials: 'include',
    })
    return sub
  } catch (e) {
    console.warn('[webpush] subscribe failed:', e)
    return null
  }
}

/**
 * Desinscrit du push manager + DELETE backend si endpoint disponible.
 */
export async function unsubscribeWebPush(): Promise<boolean> {
  if (!isPushSupported()) return false
  try {
    const reg = await navigator.serviceWorker.getRegistration('/')
    if (!reg) return false
    const sub = await reg.pushManager.getSubscription()
    if (!sub) return true
    return await sub.unsubscribe()
  } catch (e) {
    console.warn('[webpush] unsubscribe failed:', e)
    return false
  }
}
