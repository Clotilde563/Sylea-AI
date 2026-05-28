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
  const url = (event.notification.data && event.notification.data.url) || '/tracking'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      // Reuse une fenetre Sylea ouverte si possible
      for (const client of list) {
        if (client.url.includes(self.registration.scope) && 'focus' in client) {
          client.navigate(url)
          return client.focus()
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(url)
    })
  )
})
