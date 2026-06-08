// Wrapper HTTP unifié pour le desktop Tauri.
//
// Gère automatiquement :
//   1. credentials: 'include'  → propage les cookies cross-origin
//      (la webview Tauri et le backend FastAPI sont sur des origines
//      différentes ; sans 'include' le cookie CSRF n'arrive jamais)
//   2. X-CSRF-Token header     → lit le cookie sylea_csrf posé par le
//      backend sur les GET, et le renvoie en header sur les POST/PUT/
//      PATCH/DELETE (pattern double-submit imposé par CSRFMiddleware
//      depuis le commit b2fe000 "sécurité niveau pro").
//   3. ensureCsrfCookie()      → au premier appel mutant, déclenche un
//      GET /api/health préalable pour que le backend pose le cookie
//      sylea_csrf si l'app n'en a pas encore.
//
// Sans ce wrapper, tous les POST du desktop (login, chat, reminders,
// emails, etc.) renvoient 403 csrf_missing.
//
// Symétrique au frontend/src/api/client.ts. Si tu modifies la logique
// CSRF côté web, applique le même changement ici.

const CSRF_COOKIE_NAME = 'sylea_csrf'
const CSRF_HEADER_NAME = 'X-CSRF-Token'
const CSRF_LOCALSTORAGE_KEY = 'sylea_csrf_token'
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

/**
 * Lit le token CSRF côté client.
 *
 * Deux sources possibles (tentées dans l'ordre) :
 *   1. Cookie sylea_csrf (mode double-submit standard web)
 *   2. localStorage sylea_csrf_token (mode signed-token natif Tauri)
 *
 * En desktop Tauri, le cookie cross-origin (tauri:// → http://localhost:8000)
 * n'est généralement pas propagé par WebView2 sur Windows. On bascule
 * alors sur le mode signed-token où on récupère un token via
 * GET /api/auth/csrf-token et on le stocke en localStorage.
 */
function getCsrfToken(): string {
  // 1. Tentative cookie (web standard)
  try {
    const match = document.cookie
      .split('; ')
      .find((c) => c.startsWith(`${CSRF_COOKIE_NAME}=`))
    if (match) return match.split('=')[1]
  } catch {
    /* document.cookie inaccessible */
  }
  // 2. Fallback localStorage (mode natif Tauri)
  try {
    return localStorage.getItem(CSRF_LOCALSTORAGE_KEY) || ''
  } catch {
    return ''
  }
}

/**
 * Garantit qu'on a un token CSRF avant la première requête mutante.
 *
 * Stratégie :
 *   1. Si on a déjà un token (cookie ou localStorage) → no-op
 *   2. Sinon : GET /api/auth/csrf-token qui retourne un token signé
 *      en JSON ET pose le cookie. On stocke le token retourné en
 *      localStorage pour le mode signed-token.
 *
 * Cette approche fonctionne dans LES DEUX modes (web cookie + native
 * signed-token) sans branchement spécifique.
 */
let _csrfReady = false
async function ensureCsrfCookie(apiBase: string): Promise<void> {
  if (_csrfReady) return
  if (getCsrfToken()) {
    _csrfReady = true
    return
  }
  try {
    const res = await fetch(`${apiBase}/api/auth/csrf-token`, {
      credentials: 'include',
    })
    if (res.ok) {
      const data = await res.json()
      if (data?.csrf_token) {
        try {
          localStorage.setItem(CSRF_LOCALSTORAGE_KEY, data.csrf_token)
        } catch {
          /* quota localStorage */
        }
      }
    }
    _csrfReady = true
  } catch {
    // Backend down ou réseau cassé — on laisse le fetch principal
    // remonter l'erreur réelle plutôt que de bloquer ici.
  }
}

/**
 * Construit les headers d'une requête en injectant Authorization Bearer
 * + X-CSRF-Token si la méthode est mutante.
 *
 * Si l'appelant passe ses propres headers, ils sont MERGÉS (les nôtres
 * peuvent être écrasés par l'appelant). C'est intentionnel pour pouvoir
 * surcharger Content-Type ou Authorization si besoin (ex: multipart).
 */
export function buildHeaders(
  method: string,
  extraHeaders: Record<string, string> = {},
  options: { withAuth?: boolean; withContentType?: boolean } = {},
): Record<string, string> {
  const { withAuth = true, withContentType = true } = options
  const headers: Record<string, string> = {}

  if (withContentType) {
    headers['Content-Type'] = 'application/json'
  }

  // Bearer token (auth utilisateur connecté)
  if (withAuth) {
    const token = localStorage.getItem('sylea_auth_token')
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
  }

  // CSRF token sur les méthodes mutantes
  if (UNSAFE_METHODS.has(method.toUpperCase())) {
    const csrf = getCsrfToken()
    if (csrf) {
      headers[CSRF_HEADER_NAME] = csrf
    }
  }

  // Override par l'appelant (priorité maximale)
  return { ...headers, ...extraHeaders }
}

/**
 * Wrapper fetch() qui applique automatiquement :
 *   - credentials: 'include'
 *   - Bearer token Authorization
 *   - X-CSRF-Token sur POST/PUT/PATCH/DELETE
 *   - ensureCsrfCookie() avant les mutations
 *
 * Usage identique à fetch() natif. Pour les cas spéciaux (upload multipart,
 * pas d'auth, etc.) tu peux passer `init.options` qui sera fusionné avec
 * les valeurs par défaut.
 */
export async function apiFetch(
  apiBase: string,
  path: string,
  init: RequestInit = {},
  callerOptions: { withAuth?: boolean; withContentType?: boolean } = {},
): Promise<Response> {
  const method = (init.method || 'GET').toUpperCase()

  // Avant chaque mutation : s'assurer que le cookie CSRF est posé
  if (UNSAFE_METHODS.has(method)) {
    await ensureCsrfCookie(apiBase)
  }

  const extraHeaders = (init.headers as Record<string, string>) || {}
  const finalHeaders = buildHeaders(method, extraHeaders, callerOptions)

  // URL absolue si path commence par http(s), sinon préfixe apiBase
  const url = /^https?:\/\//.test(path) ? path : `${apiBase}${path}`

  return fetch(url, {
    ...init,
    headers: finalHeaders,
    credentials: 'include',
  })
}

/**
 * Helper : POST JSON avec gestion d'erreurs intégrée.
 *
 * Throw une Error contenant le message du serveur si !res.ok.
 * Renvoie le body JSON parsé sinon.
 */
export async function apiPost<T = unknown>(
  apiBase: string,
  path: string,
  body: unknown,
  callerOptions: { withAuth?: boolean } = {},
): Promise<T> {
  const res = await apiFetch(apiBase, path, {
    method: 'POST',
    body: JSON.stringify(body),
  }, callerOptions)

  if (!res.ok) {
    let detail = ''
    try {
      const err = await res.json()
      detail = err.detail || JSON.stringify(err)
    } catch {
      detail = res.statusText
    }
    throw new Error(`HTTP ${res.status} : ${detail}`)
  }

  return res.json() as Promise<T>
}

/**
 * Helper : GET JSON simple.
 */
export async function apiGet<T = unknown>(
  apiBase: string,
  path: string,
  callerOptions: { withAuth?: boolean } = {},
): Promise<T> {
  const res = await apiFetch(apiBase, path, { method: 'GET' }, callerOptions)

  if (!res.ok) {
    throw new Error(`HTTP ${res.status} : ${res.statusText}`)
  }
  return res.json() as Promise<T>
}
