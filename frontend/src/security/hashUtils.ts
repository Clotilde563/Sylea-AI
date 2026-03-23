/**
 * Utilitaires de hachage SHA-256 via Web Crypto API.
 */

export async function hashString(input: string): Promise<string> {
  const data = new TextEncoder().encode(input)
  const buf = await crypto.subtle.digest('SHA-256', data)
  return Array.from(new Uint8Array(buf))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('')
}

export async function verifyHash(input: string, hash: string): Promise<boolean> {
  const h = await hashString(input)
  return h === hash
}

export function hashPattern(pattern: number[]): Promise<string> {
  return hashString(pattern.join('-'))
}

export function verifyPattern(pattern: number[], hash: string): Promise<boolean> {
  return verifyHash(pattern.join('-'), hash)
}

/** Calcule un score de securite 0-100 */
export function computeSecurityLevel(): number {
  let score = 0

  // +40% si connecté avec un compte email
  const authToken = localStorage.getItem('sylea_auth_token')
  if (authToken) score += 40

  const lockType = localStorage.getItem('sylea-lock-type')
  if (lockType === 'pattern') {
    score += 35  // schéma = +35%
  } else if (lockType === 'password') {
    const strength = parseInt(localStorage.getItem('sylea-pwd-strength') || '0', 10)
    score += 20 + Math.min(40, strength)  // mot de passe = 20 base + bonus force (max 40)
  }

  return Math.min(100, score)
}

/** Calcule la force d'un mot de passe (0-60 bonus) */
export function passwordStrength(pwd: string): number {
  let score = 0
  if (pwd.length >= 8) score += 15
  if (pwd.length >= 12) score += 10
  if (/[a-z]/.test(pwd) && /[A-Z]/.test(pwd)) score += 10
  if (/\d/.test(pwd)) score += 10
  if (/[^a-zA-Z0-9]/.test(pwd)) score += 15
  return score
}
