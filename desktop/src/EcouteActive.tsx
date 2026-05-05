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
  /** Token JWT pour authentifier les uploads de chunks vers le backend */
  authToken?: string
  /** Base URL du backend (default localhost:8000) */
  apiBase?: string
}

interface TranscriptChunk {
  index: number
  text: string
  language: string
  duration_s: number
  status: 'uploading' | 'done' | 'error'
  segments?: Array<{ start: number; end: number; text: string }>
}

type Phase = 'preflight' | 'recording' | 'stopped' | 'generating' | 'fiche'

interface FicheResult {
  matiere: string
  matiere_auto_detected: boolean
  fiche_markdown: string
  fallback_used: boolean
}

export function EcouteActive({
  onClose,
  authToken,
  apiBase = 'http://localhost:8000',
}: Props) {
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

  // Sprint 2 — Live transcript : tableau de chunks transcribed.
  // Each chunk index est sauvegarde sur disque par Rust, on detecte l'arrivee
  // d'un nouveau chunk via chunks_count, on upload via fetch multipart.
  const [transcript, setTranscript] = useState<TranscriptChunk[]>([])
  const lastUploadedChunkRef = useRef<number>(-1)
  const transcriptEndRef = useRef<HTMLDivElement>(null)

  // Sprint 3 — Fiche generee (markdown + meta)
  const [fiche, setFiche] = useState<FicheResult | null>(null)
  const [ficheError, setFicheError] = useState<string | null>(null)
  const [ankiBusy, setAnkiBusy] = useState(false)
  const [ankiLastResult, setAnkiLastResult] = useState<string | null>(null)

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

  // ── Sprint 2 — Detection + upload des chunks transcrits ────────────────────
  //
  // Le Rust audio_capture finalise chunk_NNNN.wav toutes les 30s. Quand
  // status.chunks_count augmente, on lit le fichier le plus recent
  // (tous ceux pas encore uploades) et on POST au backend pour transcription.
  //
  // Note : status.chunks_count = nombre de chunks COMPLETES. Donc si
  // chunks_count = 3, les fichiers chunk_0000, chunk_0001, chunk_0002 sont
  // finalises sur disque.
  useEffect(() => {
    if (phase !== 'recording') return
    if (!status.session_dir) return
    if (!authToken) return

    const completedChunks = status.chunks_count
    const nextToUpload = lastUploadedChunkRef.current + 1
    if (nextToUpload >= completedChunks) return

    // Upload tous les chunks pas encore traites (rare backlog si l'upload
    // du chunk N a ete plus lent que la duree d'un chunk).
    const uploadChunk = async (idx: number) => {
      const chunkPath = `${status.session_dir}/chunk_${String(idx).padStart(4, '0')}.wav`
      // Marque uploading
      setTranscript(prev => [
        ...prev,
        { index: idx, text: '', language: '', duration_s: 0, status: 'uploading' },
      ])
      try {
        // 1) Lecture du fichier WAV depuis le disque (commande Rust existante)
        const b64 = await invoke<string>('read_file_binary', { path: chunkPath })
        // 2) Decode base64 -> Uint8Array -> Blob
        const binary = atob(b64)
        const bytes = new Uint8Array(binary.length)
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
        const blob = new Blob([bytes], { type: 'audio/wav' })
        // 3) POST multipart au backend
        const formData = new FormData()
        formData.append('audio', blob, `chunk_${idx}.wav`)
        formData.append('session_id', status.session_id || '')
        formData.append('chunk_index', String(idx))
        // Si l'utilisateur a precise la matiere "anglais", on aide la detection
        if (matiere === 'anglais') formData.append('language', 'en')
        else                       formData.append('language', 'fr')

        const r = await fetch(`${apiBase}/api/lecture/transcribe-chunk`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${authToken}` },
          body: formData,
        })
        const data = await r.json()
        if (data?.ok) {
          setTranscript(prev => prev.map(c => c.index === idx ? {
            index: idx,
            text: data.text || '',
            language: data.language || '',
            duration_s: data.duration_s || 0,
            status: 'done',
            segments: data.segments,
          } : c))
        } else {
          setTranscript(prev => prev.map(c => c.index === idx
            ? { ...c, status: 'error', text: `[Erreur : ${data?.error || 'inconnue'}]` }
            : c))
        }
      } catch (e) {
        setTranscript(prev => prev.map(c => c.index === idx
          ? { ...c, status: 'error', text: `[Erreur upload : ${e}]` }
          : c))
      }
    }

    // Upload sequentiel pour eviter de surcharger faster-whisper si plusieurs
    // chunks accumules. La derniere reference dispo = nextToUpload.
    ;(async () => {
      for (let i = nextToUpload; i < completedChunks; i++) {
        lastUploadedChunkRef.current = i
        await uploadChunk(i)
      }
    })()
  }, [status.chunks_count, status.session_dir, status.session_id, authToken, apiBase, phase, matiere])

  // Auto-scroll du transcript vers le bas a chaque nouveau chunk
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [transcript])

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
    setTranscript([])
    lastUploadedChunkRef.current = -1
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

  // ── Sprint 3 : Generation de fiche depuis le transcript complet ──────────

  const generateFiche = useCallback(async () => {
    if (!authToken) {
      setFicheError('Token manquant')
      return
    }
    const fullText = transcript.filter(c => c.status === 'done').map(c => c.text).join(' ').trim()
    if (!fullText) {
      setFicheError('Transcript vide — rien a resumer')
      return
    }
    setPhase('generating')
    setFicheError(null)
    try {
      const lang = matiere === 'anglais' ? 'en' : 'fr'
      const r = await fetch(`${apiBase}/api/lecture/generate-fiche`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${authToken}` },
        body: JSON.stringify({
          transcript: fullText,
          matiere: matiere === 'autre' ? null : matiere,
          titre: titre || null,
          formation: formation === 'Autre' ? null : formation,
          language: lang,
        }),
      })
      const data = await r.json()
      if (data?.ok) {
        setFiche({
          matiere: data.matiere,
          matiere_auto_detected: data.matiere_auto_detected,
          fiche_markdown: data.fiche_markdown,
          fallback_used: data.fallback_used,
        })
        setPhase('fiche')
      } else {
        setFicheError(data?.error || 'Erreur inconnue')
        setPhase('stopped')
      }
    } catch (e: any) {
      setFicheError(typeof e === 'string' ? e : (e?.message || 'Erreur reseau'))
      setPhase('stopped')
    }
  }, [authToken, apiBase, transcript, matiere, titre, formation])

  // Telecharge la fiche markdown sur le disque (via Tauri write_file)
  const downloadMarkdown = useCallback(async () => {
    if (!fiche) return
    try {
      const docs = await invoke<string>('get_documents_dir')
      const safeTitle = (titre || 'cours').replace(/[^\w\s-]/g, '_').slice(0, 60)
      const fname = `${fiche.matiere}_${safeTitle.replace(/\s+/g, '_')}_${Date.now()}.md`
      const target = `${docs}/Sylea/fiches/${fname}`
      await invoke('create_directory', { path: `${docs}/Sylea/fiches` })
      const header = `<!-- Genere par Sylea Agent — ${new Date().toLocaleString('fr-FR')} -->\n` +
                     `<!-- Matiere : ${fiche.matiere}${fiche.matiere_auto_detected ? ' (auto-detect)' : ''} -->\n` +
                     (formation !== 'Autre' ? `<!-- Formation : ${formation} -->\n` : '') + '\n'
      await invoke('write_file', { path: target, content: header + fiche.fiche_markdown })
      setAnkiLastResult(`Fiche sauvegardee : ${target}`)
    } catch (e: any) {
      setFicheError(typeof e === 'string' ? e : (e?.message || 'Erreur sauvegarde'))
    }
  }, [fiche, titre, formation])

  // Genere puis ecrit le .apkg Anki sur le disque
  const downloadAnki = useCallback(async () => {
    if (!fiche || !authToken) return
    setAnkiBusy(true)
    setAnkiLastResult(null)
    try {
      const r = await fetch(`${apiBase}/api/lecture/export-anki`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${authToken}` },
        body: JSON.stringify({
          fiche_markdown: fiche.fiche_markdown,
          titre: titre || 'Cours',
          matiere: fiche.matiere,
        }),
      })
      const data = await r.json()
      if (!data?.ok) {
        setFicheError(data?.error === 'no_cards_extracted'
          ? 'Aucune carte n\'a pu etre extraite (fiche trop sommaire ?)'
          : (data?.error || 'Erreur Anki'))
        return
      }
      // Ecrit le .apkg dans Documents/Sylea/anki/
      const docs = await invoke<string>('get_documents_dir')
      const target = `${docs}/Sylea/anki/${data.filename}`
      await invoke('create_directory', { path: `${docs}/Sylea/anki` })
      await invoke('write_file_binary', { path: target, dataBase64: data.data_base64 })
      setAnkiLastResult(`Deck Anki cree : ${data.card_count} cartes — ${target}`)
    } catch (e: any) {
      setFicheError(typeof e === 'string' ? e : (e?.message || 'Erreur reseau'))
    } finally {
      setAnkiBusy(false)
    }
  }, [fiche, authToken, apiBase, titre])

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

          {/* ── Sprint 2 — Live transcript ──────────────────────────────── */}
          <div style={{
            marginTop: 6, marginBottom: 10,
            background: 'rgba(0,0,0,0.4)', border: `1px solid ${SY.border}`,
            borderRadius: 8, overflow: 'hidden',
          }}>
            <div style={{
              padding: '8px 12px',
              borderBottom: `1px solid ${SY.border}`,
              display: 'flex', alignItems: 'center', gap: 8,
              fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.16em',
              textTransform: 'uppercase', color: SY.cyanSoft,
            }}>
              <span style={{
                width: 6, height: 6, borderRadius: '50%',
                background: SY.cyan, boxShadow: `0 0 6px ${SY.cyan}`,
                animation: 'sy-pulse 1.6s ease-in-out infinite',
              }} />
              <span>▸ Transcript live</span>
              <div style={{ flex: 1 }} />
              <span style={{ color: SY.textDim }}>
                {transcript.filter(c => c.status === 'done').length} / {transcript.length} chunks
              </span>
            </div>
            <div style={{
              maxHeight: 180, minHeight: 110, overflowY: 'auto',
              padding: '10px 14px',
              fontSize: 13, lineHeight: 1.55, color: SY.text,
            }}>
              {transcript.length === 0 && (
                <div style={{
                  color: SY.textDim, fontFamily: SY.mono, fontSize: 11,
                  letterSpacing: '0.06em', textAlign: 'center', padding: '24px 0',
                }}>
                  ◌ Premiere transcription dans ~30s (fin du 1er chunk)…
                </div>
              )}
              {transcript.map(c => (
                <div key={c.index} style={{
                  marginBottom: 8, paddingLeft: 14,
                  borderLeft: `2px solid ${
                    c.status === 'done'      ? SY.success :
                    c.status === 'error'     ? SY.red :
                                               SY.warn
                  }`,
                  opacity: c.status === 'uploading' ? 0.6 : 1,
                }}>
                  <div style={{
                    fontSize: 9, fontFamily: SY.mono, color: SY.textDim,
                    letterSpacing: '0.08em', marginBottom: 3,
                    display: 'flex', alignItems: 'center', gap: 6,
                  }}>
                    <span>#{String(c.index).padStart(4, '0')}</span>
                    <span>·</span>
                    <span>{fmtTime(c.index * 30 * 1000)}</span>
                    {c.status === 'uploading' && (
                      <span style={{ color: SY.warn }}>
                        · transcription en cours…
                      </span>
                    )}
                    {c.status === 'done' && c.language && (
                      <span style={{ color: SY.cyanSoft, opacity: 0.8 }}>
                        · {c.language}
                      </span>
                    )}
                  </div>
                  <div style={{
                    color: c.status === 'error' ? SY.redLight : SY.text,
                    fontStyle: c.status === 'uploading' ? 'italic' : 'normal',
                  }}>
                    {c.status === 'uploading' && !c.text ? '…' : c.text}
                  </div>
                </div>
              ))}
              <div ref={transcriptEndRef} />
            </div>
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

  if (phase === 'stopped') return (
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

        {/* Stats : nombre de chunks transcrits */}
        {transcript.length > 0 && (
          <div style={{
            padding: '10px 12px', borderRadius: 6, background: SY.surface,
            border: `1px solid ${SY.border}`, fontSize: 11,
            color: SY.text, marginBottom: 16, textAlign: 'left',
            lineHeight: 1.55,
          }}>
            <div style={{ color: SY.cyan, marginBottom: 4, fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.12em' }}>
              ▸ TRANSCRIPT
            </div>
            {transcript.filter(c => c.status === 'done').length} / {transcript.length} chunks transcrits
            {transcript.filter(c => c.status === 'done').length > 0 && (
              <span style={{ color: SY.textMute, marginLeft: 8, fontFamily: SY.mono, fontSize: 10 }}>
                (~{transcript.filter(c => c.status === 'done').reduce((acc, c) => acc + c.text.length, 0)} caracteres)
              </span>
            )}
          </div>
        )}

        {ficheError && (
          <div style={{
            padding: '8px 12px', borderRadius: 6, marginBottom: 12,
            background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
            fontSize: 11, color: SY.redLight,
          }}>
            ✗ {ficheError}
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* Genere la fiche (gros bouton CTA) */}
          <button
            onClick={generateFiche}
            disabled={transcript.filter(c => c.status === 'done').length === 0}
            style={{
              width: '100%', padding: '14px 16px', borderRadius: 8,
              background: transcript.filter(c => c.status === 'done').length === 0
                ? 'rgba(0,200,255,0.1)'
                : 'linear-gradient(135deg, #00c8ff, #0090e0)',
              border: 'none', color: '#fff',
              fontSize: 13, fontWeight: 700, letterSpacing: '0.1em',
              textTransform: 'uppercase',
              cursor: transcript.filter(c => c.status === 'done').length === 0 ? 'not-allowed' : 'pointer',
              opacity: transcript.filter(c => c.status === 'done').length === 0 ? 0.4 : 1,
              fontFamily: SY.mono,
              boxShadow: '0 4px 14px rgba(0,200,255,0.3)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="9" y1="13" x2="15" y2="13"/>
              <line x1="9" y1="17" x2="15" y2="17"/>
            </svg>
            ▸ Generer la fiche
          </button>

          {/* Fermer (sauter la fiche, on quitte) */}
          <button onClick={onClose} style={{
            width: '100%', padding: '10px 16px', borderRadius: 8,
            background: 'transparent', border: `1px solid ${SY.border}`,
            color: SY.textMute, fontSize: 11, fontWeight: 600, letterSpacing: '0.1em',
            textTransform: 'uppercase', cursor: 'pointer', fontFamily: SY.mono,
          }}>
            Fermer sans fiche
          </button>
        </div>
      </div>
    </div>
  )

  // ─── Render GENERATING (loader) ──────────────────────────────────────────

  if (phase === 'generating') return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 5000,
      background: 'rgba(5,8,16,0.92)', backdropFilter: 'blur(8px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        width: '90%', maxWidth: 460, padding: 32, textAlign: 'center',
        background: SY.bg, border: `1px solid ${SY.borderHi}`, borderRadius: 12,
      }}>
        <div style={{
          width: 64, height: 64, margin: '0 auto 18px', position: 'relative',
        }}>
          <div style={{
            position: 'absolute', inset: 0, borderRadius: '50%',
            border: `3px solid ${SY.border}`,
            borderTopColor: SY.cyan,
            borderRightColor: SY.cyanSoft,
            animation: 'sy-spin 1s linear infinite',
          }} />
        </div>
        <div style={{ fontSize: 16, fontWeight: 700, color: SY.text, marginBottom: 6 }}>
          Generation de la fiche…
        </div>
        <div style={{ fontSize: 11, color: SY.textMute, fontFamily: SY.mono, lineHeight: 1.5 }}>
          ▸ Detection de la matiere<br/>
          ▸ Structuration selon le template{matiere !== 'autre' ? ` (${matiere})` : ''}<br/>
          ▸ Mise en forme markdown + LaTeX
        </div>
      </div>
    </div>
  )

  // ─── Render FICHE (markdown rendered + downloads) ────────────────────────

  if (phase === 'fiche' && fiche) return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 5000,
      background: 'rgba(5,8,16,0.95)', backdropFilter: 'blur(8px)',
      display: 'flex', flexDirection: 'column',
      padding: 20,
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14,
        padding: '12px 16px', borderRadius: 10,
        background: SY.surface, border: `1px solid ${SY.borderHi}`,
      }}>
        <div style={{
          width: 40, height: 40, borderRadius: 8,
          background: 'linear-gradient(135deg, #00c8ff, #0090e0)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: SY.text }}>
            Fiche generee — {titre || 'Cours'}
          </div>
          <div style={{ fontSize: 10, color: SY.textMute, fontFamily: SY.mono, letterSpacing: '0.06em', marginTop: 2 }}>
            <span style={{ color: SY.cyan }}>{fiche.matiere.toUpperCase()}</span>
            {fiche.matiere_auto_detected && <span style={{ color: SY.warn }}> · auto-detect</span>}
            {fiche.fallback_used && <span style={{ color: SY.warn }}> · MODE DEGRADE (LLM indispo)</span>}
            {formation !== 'Autre' && <span> · {formation}</span>}
          </div>
        </div>
        <button onClick={onClose} style={{
          padding: '8px 14px', borderRadius: 6, background: 'transparent',
          border: `1px solid ${SY.border}`, color: SY.textMute,
          fontSize: 11, fontFamily: SY.mono, letterSpacing: '0.08em',
          cursor: 'pointer', textTransform: 'uppercase',
        }}>Fermer</button>
      </div>

      {/* Toolbar : downloads */}
      <div style={{
        display: 'flex', gap: 8, marginBottom: 14,
        padding: '8px 12px', borderRadius: 8,
        background: 'rgba(0,200,255,0.04)', border: `1px solid ${SY.border}`,
      }}>
        <button onClick={downloadMarkdown} style={dlBtnStyle(SY.cyan)}>
          ▾ Markdown (.md)
        </button>
        <button onClick={downloadAnki} disabled={ankiBusy} style={dlBtnStyle(SY.success)}>
          {ankiBusy ? '… Anki' : '▾ Anki (.apkg)'}
        </button>
        <div style={{ flex: 1 }} />
        {ankiLastResult && (
          <span style={{
            fontSize: 10, color: SY.success, fontFamily: SY.mono,
            display: 'flex', alignItems: 'center', maxWidth: '60%',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            ✓ {ankiLastResult}
          </span>
        )}
      </div>

      {ficheError && (
        <div style={{
          padding: '10px 14px', borderRadius: 6, marginBottom: 10,
          background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)',
          fontSize: 12, color: SY.redLight,
        }}>
          ✗ {ficheError}
        </div>
      )}

      {/* Markdown body */}
      <div style={{
        flex: 1, overflowY: 'auto',
        padding: '24px 32px', borderRadius: 10,
        background: 'rgba(7,12,26,0.6)', border: `1px solid ${SY.border}`,
        color: SY.text, fontSize: 14, lineHeight: 1.7,
      }}>
        <MarkdownRender source={fiche.fiche_markdown} />
      </div>
    </div>
  )

  // Fallback : ne devrait jamais arriver
  return null
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

function dlBtnStyle(color: string): React.CSSProperties {
  return {
    padding: '7px 14px', borderRadius: 6,
    background: 'transparent', border: `1px solid ${color}55`,
    color, fontSize: 11, fontFamily: '"JetBrains Mono",monospace',
    fontWeight: 700, letterSpacing: '0.06em', cursor: 'pointer',
    transition: 'all 0.15s',
  }
}

/**
 * Mini markdown renderer : pas de dep externe, suffisant pour le markdown
 * structure que faster-whisper + LLM produisent. Gere :
 *  - # / ## / ### / #### titres
 *  - **gras** *italique*
 *  - listes -, *, 1.
 *  - blockquote >
 *  - code inline `code`
 *  - LaTeX inline $...$ (rendu en italique mono — l'integration KaTeX
 *    sera ajoutee si besoin, pour Sprint 3 ca reste lisible)
 */
function MarkdownRender({ source }: { source: string }) {
  // Process inline (gras/italique/code/latex) sur une chaine
  const inline = (txt: string): React.ReactNode[] => {
    const out: React.ReactNode[] = []
    // Pattern : **bold** | `code` | $latex$ | *italic*
    const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\$[^$]+\$|\*[^*]+\*)/g
    let lastIdx = 0
    let key = 0
    let m: RegExpExecArray | null
    while ((m = pattern.exec(txt)) !== null) {
      if (m.index > lastIdx) out.push(txt.slice(lastIdx, m.index))
      const tok = m[0]
      key++
      if (tok.startsWith('**')) {
        out.push(<strong key={key} style={{ color: '#7ad9ff' }}>{tok.slice(2, -2)}</strong>)
      } else if (tok.startsWith('`')) {
        out.push(<code key={key} style={{
          fontFamily: '"JetBrains Mono",monospace', fontSize: '0.9em',
          padding: '1px 5px', borderRadius: 3,
          background: 'rgba(0,200,255,0.10)', color: '#7ad9ff',
        }}>{tok.slice(1, -1)}</code>)
      } else if (tok.startsWith('$')) {
        out.push(<span key={key} style={{
          fontFamily: '"JetBrains Mono","Fira Code",serif',
          fontStyle: 'italic', color: '#a5b4fc',
          background: 'rgba(165,180,252,0.06)', padding: '1px 4px',
          borderRadius: 3,
        }}>{tok.slice(1, -1)}</span>)
      } else if (tok.startsWith('*')) {
        out.push(<em key={key}>{tok.slice(1, -1)}</em>)
      }
      lastIdx = m.index + tok.length
    }
    if (lastIdx < txt.length) out.push(txt.slice(lastIdx))
    return out
  }

  const lines = source.split('\n')
  const elements: React.ReactNode[] = []
  let i = 0
  let key = 0

  while (i < lines.length) {
    const ln = lines[i]
    key++

    // Block LaTeX : $$...$$
    const blockMath = ln.trim().match(/^\$\$(.+)\$\$\s*$/)
    if (blockMath) {
      elements.push(
        <div key={key} style={{
          margin: '14px 0', padding: '10px 16px', borderRadius: 6,
          background: 'rgba(165,180,252,0.06)',
          border: '1px solid rgba(165,180,252,0.18)',
          fontFamily: '"JetBrains Mono",serif', fontStyle: 'italic',
          color: '#c4b5fd', textAlign: 'center', fontSize: 14,
        }}>{blockMath[1]}</div>
      )
      i++; continue
    }

    // Heading
    const h = ln.match(/^(#{1,6})\s+(.+)$/)
    if (h) {
      const level = h[1].length
      const text = h[2]
      const sizes = ['2.0em', '1.5em', '1.25em', '1.1em', '1em', '1em']
      const colors = ['#00c8ff', '#7ad9ff', '#a5b4fc', '#e6f0ff', '#e6f0ff', '#e6f0ff']
      elements.push(
        <div key={key} style={{
          fontSize: sizes[level - 1], color: colors[level - 1],
          fontWeight: 700, letterSpacing: level <= 2 ? '0.02em' : '0.01em',
          marginTop: level === 1 ? 0 : (level === 2 ? 22 : 14),
          marginBottom: 8,
          paddingBottom: level === 1 ? 8 : 4,
          borderBottom: level === 1 ? '2px solid rgba(0,200,255,0.25)' : 'none',
        }}>{inline(text)}</div>
      )
      i++; continue
    }

    // Blockquote
    if (ln.startsWith('>')) {
      const block: string[] = []
      while (i < lines.length && lines[i].startsWith('>')) {
        block.push(lines[i].replace(/^>\s?/, ''))
        i++
      }
      elements.push(
        <blockquote key={key} style={{
          margin: '12px 0', padding: '8px 14px',
          borderLeft: '3px solid #7ad9ff',
          background: 'rgba(122,217,255,0.05)',
          borderRadius: '0 6px 6px 0',
          color: '#c4b5fd',
        }}>
          {block.map((b, idx) => <div key={idx}>{inline(b)}</div>)}
        </blockquote>
      )
      continue
    }

    // List item
    if (/^\s*[-*]\s+/.test(ln) || /^\s*\d+\.\s+/.test(ln)) {
      const items: string[] = []
      const ordered = /^\s*\d+\.\s+/.test(ln)
      while (i < lines.length && (
        /^\s*[-*]\s+/.test(lines[i]) || /^\s*\d+\.\s+/.test(lines[i])
      )) {
        items.push(lines[i].replace(/^\s*(?:[-*]|\d+\.)\s+/, ''))
        i++
      }
      const Tag = ordered ? 'ol' : 'ul'
      elements.push(
        <Tag key={key} style={{ margin: '8px 0', paddingLeft: 24, lineHeight: 1.7 }}>
          {items.map((it, idx) => <li key={idx}>{inline(it)}</li>)}
        </Tag>
      )
      continue
    }

    // Empty line -> spacer
    if (!ln.trim()) {
      elements.push(<div key={key} style={{ height: 8 }} />)
      i++; continue
    }

    // Paragraph
    elements.push(
      <p key={key} style={{ margin: '6px 0', lineHeight: 1.7 }}>
        {inline(ln)}
      </p>
    )
    i++
  }

  return <>{elements}</>
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
