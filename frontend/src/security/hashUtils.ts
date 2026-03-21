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
  const lockType = localStorage.getItem('sylea-lock-type')
  if (!lockType) return 0
  if (lockType === 'pattern') return 60
  // password
  const strength = parseInt(localStorage.getItem('sylea-pwd-strength') || '0', 10)
  return Math.min(100, 40 + strength)  // 40 base + strength bonus
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
