/**
 * EcouteActive — Vue desktop pour l'enregistrement long de cours
 * (universite/prepa). Sprint 1 (audio uniquement).
 *
 * Flow :
 *  1. Pre-flight : choix matiere + titre + formation (MPSI/ECG/...)
 *  2. Recording : timer, waveform live (canvas), level meter, pause/stop
 *  3. Stop -> resume avec chemin du dossier de session (chunks WAV)
 *
 * Le wrapper Rust (audio_capture.rs) gere :
 *  - cpal capture cross-platform
 *  - resample 16 kHz mono 16-bit (format Whisper)
 *  - chunks 30s sur disque (~/Documents/Sylea/cours/<session>/chunk_NNNN.wav)
 *  - Wake lock Windows
 *
 * Sprint 2 ajoutera : transcription faster-whisper, live transcript,
 * generation de fiche par matiere.
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import { invoke } from '@tauri-apps/api/core'

const SY = {
  cyan:    '#00c8ff',
  cyanSoft:'#7ad9ff',
  red:     '#ef4444',
  redLight:'#f87171',
  text:    '#e6f0ff',
  textMute:'rgba(230,240,255,0.60)',
  textDim: 'rgba(230,240,255,0.35)',
  border:  'rgba(0,200,255,0.12)',
  borderHi:'rgba(0,200,255,0.25)',
  surface: 'rgba(0,200,255,0.03)',
  bg:      '#050810',
  success: '#10b981',
  warn:    '#f59e0b',
  mono:    '"JetBrains Mono","Fira Code",monospace',
}

const MATIERES = [
  { id: 'maths',    label: 'Mathematiques',     emoji: '𝛴' },
  { id: 'physique', label: 'Physique-Chimie',   emoji: 'Φ' },
  { id: 'philo',    label: 'Philosophie',       emoji: '⚖' },
  { id: 'ses',      label: 'SES / Economie',    emoji: '€' },
  { id: 'anglais',  label: 'Anglais / LV',      emoji: 'EN' },
  { id: 'histoire', label: 'Histoire-Geo',      emoji: '📜' },
  { id: 'autre',    label: 'Autre / Auto-detect', emoji: '?' },
]

const FORMATIONS = [
  'MPSI', 'PCSI', 'PTSI', 'BCPST',
  'MP', 'PC', 'PSI',
  'ECG1', 'ECG2',
  'Hypokhagne', 'Khagne',
  'Licence', 'Master',
  'Autre',
]

interface RecordingStatus {
  is_active: boolean
  is_paused: boolean
  elapsed_ms: number
  chunks_count: number
  level_rms: number
  session_id: string | null
  session_dir: string | null
}

interface Props {
  onClose: () => void
}

type Phase = 'preflight' | 'recording' | 'stopped'

export function EcouteActive({ onClose }: Props) {
  const [phase, setPhase] = useState<Phase>('preflight')

  // Pre-flight form
  const [matiere, setMatiere] = useState<string>('autre')
  const [titre, setTitre] = useState<string>('')
  const [formation, setFormation] = useState<string>('Autre')

  // Recording state
  const [status, setStatus] = useState<RecordingStatus>({
    is_active: false, is_paused: false, elapsed_ms: 0, chunks_count: 0,
    level_rms: 0, session_id: null, session_dir: null,
  })
  const [error, setError] = useState<string | null>(null)
  const [stopResult, setStopResult] = useState<{
    session_dir: string; duration_ms: number; chunks_count: number
  } | null>(null)

  // Waveform canvas
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const levelHistoryRef = useRef<number[]>([])

  // Polling status toutes les 200ms quand on enregistre
  useEffect(() => {
    if (phase !== 'recording') return
    const id = setInterval(async () => {
      try {
        const s = await invoke<RecordingStatus>('get_recording_status')
        setStatus(s)
        // Push level dans l'historique pour la waveform (max 120 points)
        levelHistoryRef.current.push(s.level_rms)
        if (levelHistoryRef.current.length > 120) levelHistoryRef.current.shift()
      } catch {}
    }, 200)
    return () => clearInterval(id)
  }, [phase])

  // Render waveform
  useEffect(() => {
    if (phase !== 'recording') return
    const c = canvasRef.current
    if (!c) return
    const ctx = c.getContext('2d')
    if (!ctx) return
    const dpr = window.devicePixelRatio || 1
    c.width = c.offsetWidth * dpr
    c.height = c.offsetHeight * dpr
    ctx.scale(dpr, dpr)

    const w = c.offsetWidth
    const h = c.offsetHeight
    const history = levelHistoryRef.current
    ctx.clearRect(0, 0, w, h)

    // Bg grille
    ctx.strokeStyle = 'rgba(0,200,255,0.06)'
    ctx.lineWidth = 1
    for (let i = 0; i < 5; i++) {
      const y = (h / 4) * i
      ctx.beginPath()
      ctx.moveTo(0, y)
      ctx.lineTo(w, y)
      ctx.stroke()
    }

    // Bars
    const barW = w / 120
    const cx = h / 2
    for (let i = 0; i < history.length; i++) {
      const v = history[i]
      const amp = Math.min(1, v * 4) // amplifie un peu pour la lisibilite
      const barH = amp * (h * 0.85)
      const x = i * barW
      const grad = ctx.createLinearGradient(0, cx - barH / 2, 0, cx + barH / 2)
      grad.addColorStop(0, status.is_paused ? SY.warn : SY.cyan)
      grad.addColorStop(0.5, status.is_paused ? '#ffd180' : SY.cyanSoft)
      grad.addColorStop(1, status.is_paused ? SY.warn : SY.cyan)
      ctx.fillStyle = grad
      ctx.fillRect(x, cx - barH / 2, Math.max(1, barW - 1), barH)
    }
  }, [status, phase])

  // ── Actions ──────────────────────────────────────────────────────────────

  const startRecording = useCallback(async () => {
    setError(null)
    levelHistoryRef.current = []
    const session_id = `lec_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
    try {
      await invoke('start_recording', {
        sessionId: session_id,
        matiere: matiere === 'autre' ? null : matiere,
        titre: titre.trim() || null,
        formation: formation === 'Autre' ? null : formation,
      })
      setPhase('recording')
    } catch (e: any) {
      setError(typeof e === 'string' ? e : (e?.message || 'Erreur micro'))
    }
  }, [matiere, titre, formation])

  const stopRecording = useCallback(async () => {
    try {
      const r = await invoke<typeof stopResult>('stop_recording')
      setStopResult(r)
      setPhase('stopped')
    } catch (e: any) {
      setError(typeof e === 'string' ? e : (e?.message || 'Erreur arret'))
    }
  }, [])

  const togglePause = useCallback(async () => {
    try {
      if (status.is_paused) await invoke('resume_recording')
      else                   await invoke('pause_recording')
    } catch (e) { console.error(e) }
  }, [status.is_paused])

  // ── Helpers UI ───────────────────────────────────────────────────────────

  const fmtTime = (ms: number) => {
    const s = Math.floor(ms / 1000)
    const h = Math.floor(s / 3600)
    const m = Math.floor((s % 3600) / 60)
    const ss = s % 60
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
    return `${m}:${String(ss).padStart(2, '0')}`
  }

  // ─── Render PREFLIGHT ────────────────────────────────────────────────────

  if (phase === 'preflight') {
    return (
      <div style={{
        position: 'fixed', inset: 0, zIndex: 5000,
        background: 'rgba(5,8,16,0.92)', backdropFilter: 'blur(8px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <div style={{
          width: '90%', maxWidth: 560, maxHeight: '90vh', overflowY: 'auto',
          background: SY.bg, border: `1px solid ${SY.borderHi}`,
          borderRadius: 12, padding: 28, position: 'relative',
        }}>
          {/* Close */}
          <button onClick={onClose} aria-label="Fermer" style={{
            position: 'absolute', top: 12, right: 12,
            background: 'transparent', border: 'none', color: SY.textMute,
            cursor: 'pointer', fontSize: 20, padding: 6,
          }}>×</button>

          {/* Title */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
            <div style={{
              width: 44, height: 44, borderRadius: 10,
              background: 'linear-gradient(135deg, #ef4444, #f87171)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: '0 0 18px rgba(239,68,68,0.35)',
            }}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                <line x1="12" y1="19" x2="12" y2="23"/>
                <line x1="8" y1="23" x2="16" y2="23"/>
              </svg>
            </div>
            <div>
              <div style={{ fontSize: 18, fontWeight: 700, color: SY.text, letterSpacing: '0.02em' }}>
                Ecoute active
              </div>
              <div style={{ fontSize: 12, color: SY.textMute, fontFamily: SY.mono, letterSpacing: '0.06em' }}>
                Enregistre ton cours, l'agent en fait la fiche
              </div>
            </div>
          </div>

          {/* Matiere */}
          <Section label="Matiere">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
              {MATIERES.map(m => (
                <button key={m.id}
                  onClick={() => setMatiere(m.id)}
                  style={{
                    padding: '10px 12px', borderRadius: 7,
                    background: matiere === m.id ? 'rgba(239,68,68,0.10)' : SY.surface,
                    border: `1px solid ${matiere === m.id ? 'rgba(239,68,68,0.45)' : SY.border}`,
                    color: matiere === m.id ? SY.redLight : SY.text,
                    cursor: 'pointer', textAlign: 'left',
                    display: 'flex', alignItems: 'center', gap: 9,
                    fontSize: 13, transition: 'all 0.15s',
                  }}>
                  <span style={{ fontFamily: SY.mono, width: 22, textAlign: 'center', opacity: 0.85 }}>
                    {m.emoji}
                  </span>
                  {m.label}
                </button>
              ))}
            </div>
          </Section>

          {/* Titre */}
          <Section label="Titre du cours (optionnel)">
            <input
              value={titre}
              onChange={e => setTitre(e.target.value)}
              placeholder="ex: Mecanique du point - Cinematique"
              maxLength={120}
              style={{
                width: '100%', padding: '11px 13px', borderRadius: 7,
                border: `1px solid ${SY.border}`,
                background: 'rgba(5,8,16,0.6)', color: SY.text,
                fontSize: 13, fontFamily: 'inherit',
                outline: 'none',
              }}
              onFocus={e => { e.currentTarget.style.borderColor = SY.cyan }}
              onBlur={e => { e.currentTarget.style.borderColor = SY.border }}
            />
          </Section>

          {/* Formation */}
          <Section label="Formation (pour adapter le style de fiche)">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {FORMATIONS.map(f => (
                <button key={f}
                  onClick={() => setFormation(f)}
                  style={{
                    padding: '5px 11px', borderRadius: 999,
                    background: formation === f ? 'rgba(0,200,255,0.10)' : 'transparent',
                    border: `1px solid ${formation === f ? SY.borderHi : SY.border}`,
                    color: formation === f ? SY.cyanSoft : SY.textMute,
                    cursor: 'pointer', fontSize: 11, fontFamily: SY.mono,
                    letterSpacing: '0.04em', transition: 'all 0.15s',
                  }}>
                  {f}
                </button>
              ))}
            </div>
          </Section>

          {/* Privacy notice */}
          <div style={{
            marginTop: 16, padding: '10px 12px', borderRadius: 6,
            background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.25)',
            fontSize: 11, color: SY.text, lineHeight: 1.55,
          }}>
            <div style={{ color: SY.success, fontWeight: 700, marginBottom: 4, fontFamily: SY.mono, letterSpacing: '0.08em' }}>
              ▸ 100% LOCAL
            </div>
            L'audio reste sur ton ordinateur (~/Documents/Sylea/cours/). La transcription utilisera faster-whisper en local — aucune donnee n'est envoyee a un serveur tiers.
          </div>

          {error && (
            <div style={{
              marginTop: 12, padding: '8px 12px', borderRadius: 6,
              background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
              fontSize: 12, color: '#fca5a5',
            }}>
              ✗ {error}
            </div>
          )}

          {/* Start button */}
          <button onClick={startRecording} style={{
            marginTop: 22, width: '100%',
            padding: '13px 16px', borderRadius: 8,
            background: 'linear-gradient(135deg, #ef4444 0%, #f87171 100%)',
            color: '#fff', border: 'none',
            fontSize: 14, fontWeight: 700, letterSpacing: '0.08em',
            textTransform: 'uppercase', cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            boxShadow: '0 4px 16px rgba(239,68,68,0.3)',
            fontFamily: SY.mono,
          }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#fff', animation: 'sy-pulse 1.4s ease-in-out infinite' }} />
            ▸ Demarrer l'enregistrement
          </button>
        </div>
      </div>
    )
  }

  // ─── Render RECORDING ────────────────────────────────────────────────────

  if (phase === 'recording') {
    return (
      <div style={{
        position: 'fixed', inset: 0, zIndex: 5000,
        background: 'rgba(5,8,16,0.92)', backdropFilter: 'blur(8px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <div style={{
          width: '90%', maxWidth: 720, padding: 28,
          background: SY.bg, border: `1px solid ${status.is_paused ? 'rgba(245,158,11,0.4)' : 'rgba(239,68,68,0.4)'}`,
          borderRadius: 14, position: 'relative',
          boxShadow: status.is_paused
            ? '0 0 32px rgba(245,158,11,0.18)'
            : '0 0 32px rgba(239,68,68,0.22)',
        }}>
          {/* Header : statut + matiere */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18 }}>
            <span style={{
              width: 14, height: 14, borderRadius: '50%',
              background: status.is_paused ? SY.warn : SY.red,
              boxShadow: `0 0 14px ${status.is_paused ? SY.warn : SY.red}`,
              animation: status.is_paused ? 'none' : 'sy-pulse 1.2s ease-in-out infinite',
              flexShrink: 0,
            }} />
            <div style={{ flex: 1 }}>
              <div style={{
                fontSize: 11, color: status.is_paused ? SY.warn : SY.redLight,
                fontFamily: SY.mono, letterSpacing: '0.18em', textTransform: 'uppercase',
                fontWeight: 700,
              }}>
                {status.is_paused ? '◐ EN PAUSE' : '● ENREGISTREMENT EN COURS'}
              </div>
              <div style={{ fontSize: 15, color: SY.text, fontWeight: 600, marginTop: 2 }}>
                {titre || (matiere === 'autre' ? 'Cours sans titre' : MATIERES.find(m => m.id === matiere)?.label || 'Cours')}
                {formation !== 'Autre' && (
                  <span style={{ marginLeft: 8, fontSize: 11, color: SY.cyanSoft, fontFamily: SY.mono }}>
                    [{formation}]
                  </span>
                )}
              </div>
            </div>
            <button onClick={onClose} aria-label="Reduire" style={{
              background: 'transparent', border: `1px solid ${SY.border}`,
              color: SY.textMute, cursor: 'pointer', padding: '6px 10px',
              borderRadius: 6, fontSize: 11, fontFamily: SY.mono, letterSpacing: '0.06em',
            }}>← Reduire</button>
          </div>

          {/* Big timer */}
          <div style={{
            fontFamily: SY.mono, fontSize: 56, fontWeight: 700,
            color: SY.text, textAlign: 'center', letterSpacing: '0.04em',
            margin: '12px 0 18px',
            fontVariantNumeric: 'tabular-nums',
            textShadow: status.is_paused ? 'none' : `0 0 18px ${SY.red}40`,
          }}>
            {fmtTime(status.elapsed_ms)}
          </div>

          {/* Waveform canvas */}
          <div style={{
            width: '100%', height: 100, borderRadius: 8,
            background: 'rgba(0,0,0,0.4)',
            border: `1px solid ${SY.border}`,
            overflow: 'hidden', position: 'relative',
          }}>
            <canvas ref={canvasRef} style={{ width: '100%', height: '100%' }} />
            {/* Level indicator (right side bar) */}
            <div style={{
              position: 'absolute', right: 8, top: 8, bottom: 8, width: 4,
              background: 'rgba(255,255,255,0.06)', borderRadius: 2, overflow: 'hidden',
            }}>
              <div style={{
                position: 'absolute', left: 0, right: 0, bottom: 0,
                height: `${Math.min(100, status.level_rms * 400)}%`,
                background: status.level_rms > 0.6
                  ? `linear-gradient(180deg, ${SY.warn}, ${SY.red})`
                  : `linear-gradient(180deg, ${SY.cyanSoft}, ${SY.cyan})`,
                transition: 'height 0.1s ease-out',
              }} />
            </div>
          </div>

          {/* Stats */}
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8,
            margin: '14px 0',
          }}>
            <Stat label="CHUNKS" value={status.chunks_count.toString()} />
            <Stat label="DUREE EST." value={`${(status.chunks_count * 30 / 60).toFixed(1)} min`} />
            <Stat label="TAILLE EST." value={`${(status.chunks_count * 0.96).toFixed(1)} MB`} />
          </div>

          {/* Controls */}
          <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
            <button onClick={togglePause} style={{
              flex: 1, padding: '13px 16px', borderRadius: 8,
              background: status.is_paused ? 'rgba(16,185,129,0.12)' : 'rgba(245,158,11,0.12)',
              border: `1px solid ${status.is_paused ? 'rgba(16,185,129,0.4)' : 'rgba(245,158,11,0.4)'}`,
              color: status.is_paused ? SY.success : SY.warn,
              fontSize: 13, fontWeight: 700, letterSpacing: '0.1em',
              textTransform: 'uppercase', cursor: 'pointer', fontFamily: SY.mono,
              transition: 'all 0.15s',
            }}>
              {status.is_paused ? '▸ Reprendre' : '⏸ Pause'}
            </button>
            <button onClick={stopRecording} style={{
              flex: 1, padding: '13px 16px', borderRadius: 8,
              background: 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)',
              border: 'none', color: '#fff',
              fontSize: 13, fontWeight: 700, letterSpacing: '0.1em',
              textTransform: 'uppercase', cursor: 'pointer', fontFamily: SY.mono,
              boxShadow: '0 4px 14px rgba(239,68,68,0.35)',
            }}>
              ◼ Stop & Resumer
            </button>
          </div>

          {/* Footer info */}
          <div style={{
            marginTop: 16, padding: '8px 12px', borderRadius: 6,
            fontSize: 10, color: SY.textMute, fontFamily: SY.mono,
            letterSpacing: '0.06em', textAlign: 'center',
            background: SY.surface,
          }}>
            ▸ Veille systeme empechee · Sauvegarde auto sur disque toutes les 30s
          </div>
        </div>
      </div>
    )
  }

  // ─── Render STOPPED ──────────────────────────────────────────────────────

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 5000,
      background: 'rgba(5,8,16,0.92)', backdropFilter: 'blur(8px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        width: '90%', maxWidth: 540, padding: 28,
        background: SY.bg, border: `1px solid rgba(16,185,129,0.4)`,
        borderRadius: 12, textAlign: 'center',
      }}>
        <div style={{
          width: 64, height: 64, borderRadius: '50%',
          background: 'rgba(16,185,129,0.15)',
          border: '1px solid rgba(16,185,129,0.4)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          margin: '0 auto 18px',
        }}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke={SY.success} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </div>
        <div style={{ fontSize: 18, fontWeight: 700, color: SY.text, marginBottom: 4 }}>
          Enregistrement termine
        </div>
        <div style={{ fontSize: 12, color: SY.textMute, marginBottom: 20 }}>
          Duree : <strong style={{ color: SY.text }}>{fmtTime(stopResult?.duration_ms || 0)}</strong>
          {' · '}
          {stopResult?.chunks_count || 0} chunks WAV
        </div>

        {stopResult?.session_dir && (
          <div style={{
            padding: '10px 12px', borderRadius: 6, background: SY.surface,
            border: `1px solid ${SY.border}`, fontSize: 10,
            color: SY.textMute, fontFamily: SY.mono, letterSpacing: '0.04em',
            marginBottom: 16, wordBreak: 'break-all', textAlign: 'left',
          }}>
            <div style={{ color: SY.cyan, marginBottom: 4 }}>▸ Audio sauvegarde :</div>
            {stopResult.session_dir}
          </div>
        )}

        <div style={{
          padding: '10px 12px', borderRadius: 6,
          background: 'rgba(245,158,11,0.06)', border: '1px solid rgba(245,158,11,0.25)',
          fontSize: 11, color: SY.warn, marginBottom: 16, lineHeight: 1.5,
        }}>
          ⚠ Sprint 2 (a venir) : transcription auto faster-whisper + generation de fiche par matiere.
          Pour l'instant, l'audio est sauvegarde localement.
        </div>

        <button onClick={onClose} style={{
          width: '100%', padding: '12px 16px', borderRadius: 8,
          background: 'linear-gradient(135deg, #00c8ff, #0090e0)',
          border: 'none', color: '#fff',
          fontSize: 13, fontWeight: 700, letterSpacing: '0.1em',
          textTransform: 'uppercase', cursor: 'pointer', fontFamily: SY.mono,
        }}>
          Fermer
        </button>
      </div>
    </div>
  )
}

// ── Sub-components ──────────────────────────────────────────────────────────

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{
        fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.16em',
        color: SY.textMute, marginBottom: 7, textTransform: 'uppercase',
      }}>
        <span style={{ color: SY.cyan }}>▸</span> {label}
      </div>
      {children}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      padding: '10px 12px', borderRadius: 7,
      background: SY.surface, border: `1px solid ${SY.border}`,
      textAlign: 'center',
    }}>
      <div style={{
        fontSize: 9, fontFamily: SY.mono, letterSpacing: '0.16em',
        color: SY.textDim, marginBottom: 3, textTransform: 'uppercase',
      }}>
        {label}
      </div>
      <div style={{ fontSize: 16, fontWeight: 700, color: SY.text, fontFamily: SY.mono }}>
        {value}
      </div>
    </div>
  )
}

export default EcouteActive
