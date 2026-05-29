// Service Worker minimal pour Web Push (PWA mobile).
// Active uniquement si l'utilisateur s'abonne via /api/notifications/subscribe.
//
// Etapes :
//   1. Frontend : navigator.serviceWorker.register('/sylea-sw.js')
//   2. Frontend : registration.pushManager.subscribe({applicationServerKey})
//   3. POST /api/notifications/subscribe avec la PushSubscription
//   4. Backend envoie un push via pywebpush -> ce service worker recoit
//      l'event 'push' et affiche une notification OS

self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

self.addEventListener('push', (event) => {
  let payload = { title: 'Sylea', body: 'Vous avez une notification' }
  try {
    if (event.data) payload = event.data.json()
  } catch (e) {
    payload.body = (event.data && event.data.text()) || payload.body
  }
  const options = {
    body: payload.body,
    icon: payload.icon || '/sylea-logo.svg',
    badge: payload.badge || '/sylea-logo.svg',
    tag: payload.tag,
    data: payload.data || {},
    requireInteraction: payload.requireInteraction === true,
    vibrate: payload.vibrate || [200, 100, 200],
  }
  event.waitUntil(self.registration.showNotification(payload.title, options))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const data = event.notification.data || {}

  // Cas 1 : click sur une ACTION (bouton A/B/Aucun de la notif tracking)
  // -> POST /respond directement depuis le SW, puis navigate /tracking
  if (event.action && data.tracking_id && typeof data.periode_idx === 'number') {
    const url = '/tracking?notif=responded'
    event.waitUntil((async () => {
      try {
        const r = await fetch(`/api/dilemme/tracking/${data.tracking_id}/respond`, {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            ...(data.csrf ? { 'X-CSRF-Token': data.csrf } : {}),
            ...(data.token ? { Authorization: `Bearer ${data.token}` } : {}),
          },
          body: JSON.stringify({ periode_idx: data.periode_idx, choice: event.action }),
        })
        // confirmation toast (ne bloque pas si fail)
        if (r.ok) {
          self.registration.showNotification('Sylea — réponse enregistrée', {
            body: 'Votre choix a été pris en compte. Merci !',
            icon: '/sylea-logo.svg',
            tag: 'sylea-response-ack',
            silent: true,
          })
        }
      } catch (e) { /* swallow */ }
      // Open / focus app
      return openOrFocus(url)
    })())
    return
  }

  // Cas 2 : click sur le corps de la notif (pas d'action) -> juste open /tracking
  const url = data.url || '/tracking'
  event.waitUntil(openOrFocus(url))
})

async function openOrFocus(url) {
  const list = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
  for (const client of list) {
    if (client.url.includes(self.registration.scope) && 'focus' in client) {
      try { client.navigate(url) } catch (e) { /* fail silently */ }
      return client.focus()
    }
  }
  if (self.clients.openWindow) return self.clients.openWindow(url)
}
