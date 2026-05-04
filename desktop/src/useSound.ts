/**
 * Hook sound design (Sprint 2 — feature 2.3)
 *
 * Tones courts UI synthetises via Web Audio API (pas de fichiers binaires
 * dans le bundle, son ultra leger + 100% offline).
 *
 *   click    — 880 Hz square 30 ms     (clic UI court et net)
 *   success  — 660→990 Hz triangle 150ms  (montee positive)
 *   error    — 220 Hz sawtooth 200ms      (gronde grave)
 *   notify   — 1320→880 Hz sine 250ms     (chime descendant)
 *
 * Toggle ON/OFF persiste dans localStorage('sylea_sound_enabled').
 * Si AudioContext est indisponible (ex: ssr), playSound() ne fait rien.
 */
import { useEffect, useRef, useState, useCallback } from 'react'

export type SoundType = 'click' | 'success' | 'error' | 'notify' | 'hover'

const STORAGE_KEY = 'sylea_sound_enabled'

interface ToneConfig {
  freq: number          // Hz (start)
  freqEnd?: number      // Hz (end, sweep)
  type: OscillatorType  // 'sine' | 'square' | 'triangle' | 'sawtooth'
  durMs: number
  gain: number          // 0..1
}

const TONES: Record<SoundType, ToneConfig> = {
  click:   { freq: 880,  type: 'square',   durMs: 30,  gain: 0.05 },
  hover:   { freq: 1240, type: 'sine',     durMs: 22,  gain: 0.025 },
  success: { freq: 660, freqEnd: 990, type: 'triangle', durMs: 150, gain: 0.06 },
  error:   { freq: 220,  type: 'sawtooth', durMs: 200, gain: 0.05 },
  notify:  { freq: 1320, freqEnd: 880, type: 'sine',  durMs: 250, gain: 0.07 },
}

// AudioContext partage — instancie au 1er play (lazy, evite warning autoplay).
let _ctx: AudioContext | null = null
function getCtx(): AudioContext | null {
  if (typeof window === 'undefined') return null
  if (_ctx) return _ctx
  try {
    const Ctor = window.AudioContext || (window as any).webkitAudioContext
    if (!Ctor) return null
    _ctx = new Ctor()
    return _ctx
  } catch {
    return null
  }
}

/** Joue un tone synthetise. No-op si sound desactive ou AudioContext indispo. */
export function playSound(kind: SoundType, enabled = true): void {
  if (!enabled) return
  const ctx = getCtx()
  if (!ctx) return
  // Resume si suspendu (auto-pause apres inactivite sur certains navigateurs)
  if (ctx.state === 'suspended') {
    try { ctx.resume() } catch {}
  }
  const cfg = TONES[kind]
  const now = ctx.currentTime
  const dur = cfg.durMs / 1000

  const osc = ctx.createOscillator()
  osc.type = cfg.type
  osc.frequency.setValueAtTime(cfg.freq, now)
  if (cfg.freqEnd !== undefined) {
    osc.frequency.exponentialRampToValueAtTime(cfg.freqEnd, now + dur)
  }

  // Enveloppe AR (attack 5ms / release jusqu'a la fin) — evite clics
  const gain = ctx.createGain()
  gain.gain.setValueAtTime(0, now)
  gain.gain.linearRampToValueAtTime(cfg.gain, now + Math.min(0.005, dur * 0.3))
  gain.gain.exponentialRampToValueAtTime(0.0001, now + dur)

  osc.connect(gain)
  gain.connect(ctx.destination)
  osc.start(now)
  osc.stop(now + dur + 0.02)
}

/** Hook React : retourne play() et toggle(), persiste dans localStorage. */
export function useSound() {
  const [enabled, setEnabled] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(STORAGE_KEY)
      return v === null ? true : v === '1'
    } catch { return true }
  })
  const enabledRef = useRef(enabled)
  useEffect(() => { enabledRef.current = enabled }, [enabled])

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, enabled ? '1' : '0') } catch {}
  }, [enabled])

  const play = useCallback((kind: SoundType) => {
    playSound(kind, enabledRef.current)
  }, [])

  const toggle = useCallback(() => {
    setEnabled(prev => !prev)
  }, [])

  return { enabled, play, toggle, setEnabled }
}
