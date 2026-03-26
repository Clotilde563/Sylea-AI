// Page Bilan quotidien — Check-in bien-être journalier

import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../store/useStore'
import { api } from '../api/client'
import { useDeviceContext } from '../contexts/DeviceContext'
import { useT } from '../i18n/LanguageContext'

// Couleur dynamique pour les scores 1-10
function scoreCol(val: number, invert = false): string {
  const v = invert ? 11 - val : val
  if (v <= 3) return '#ef4444'
  if (v <= 5) return '#f59e0b'
  if (v <= 7) return '#22c55e'
  return '#10b981'
}

// Format heures
function fmt(h: number): string {
  const full = Math.floor(h)
  const min  = Math.round((h - full) * 60)
  return min > 0 ? `${full}h${min.toString().padStart(2, '0')}` : `${full}h`
}

export function BilanPage() {
  const navigate = useNavigate()
  const t = useT()
  const { ctx: deviceCtx } = useDeviceContext()
  const { profil, setProfil } = useStore()

  // Scores bien-être
  const [sante,  setSante]  = useState(profil?.niveau_sante  ?? 7)
  const [stress, setStress] = useState(profil?.niveau_stress ?? 5)
  const [energie, setEnergie] = useState(profil?.niveau_energie ?? 7)
  const [bonheur, setBonheur] = useState(profil?.niveau_bonheur ?? 7)

  // Temps quotidien
  const [hTravail,   setHTravail]   = useState(profil?.heures_travail   ?? 8)
  const [hSommeil,   setHSommeil]   = useState(profil?.heures_sommeil   ?? 7)
  const [hLoisirs,   setHLoisirs]   = useState(profil?.heures_loisirs   ?? 2)
  const [hTransport, setHTransport] = useState(profil?.heures_transport ?? 1)
  const [hObjectif,  setHObjectif]  = useState(profil?.heures_objectif  ?? 1)

  // Description + IA
  const [descJournee, setDescJournee] = useState('')
  const [analysing, setAnalysing]     = useState(false)
  const [saving, setSaving]           = useState(false)
  const [error, setError]             = useState<string | null>(null)
  const [done, setDone]               = useState(false)

  // Voice
  const [voiceActive, setVoiceActive] = useState(false)
  const [voiceError, setVoiceError]   = useState<string | null>(null)
  const recognitionRef = useRef<any>(null)

  useEffect(() => {
    if (!profil) {
      api.getProfil().then(setProfil).catch(() => navigate('/profil'))
    }
  }, [])

  // Vérifier si le bilan existe déjà
  useEffect(() => {
    api.checkBilanAujourdhui().then(res => {
      if (res.exists) setDone(true)
    }).catch(() => {})
  }, [])

  const toggleVoice = () => {
    if (voiceActive && recognitionRef.current) {
      recognitionRef.current.stop()
      setVoiceActive(false)
      return
    }
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) { setVoiceError(t('bilan.vocal_incompatible')); return }
    const r = new SR()
    r.lang = 'fr-FR'
    r.continuous = true
    r.interimResults = true
    recognitionRef.current = r
    let finalText = descJournee
    r.onresult = (ev: any) => {
      let interim = ''
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        if (ev.results[i].isFinal) {
          finalText += (finalText ? ' ' : '') + ev.results[i][0].transcript
          setDescJournee(finalText)
        } else {
          interim += ev.results[i][0].transcript
        }
      }
    }
    r.onerror = (ev: any) => { setVoiceError(`${t('bilan.erreur_vocale')} ${ev.error}`); setVoiceActive(false) }
    r.onend = () => setVoiceActive(false)
    r.start()
    setVoiceActive(true)
    setVoiceError(null)
  }

  const analyserJournee = async () => {
    if (!descJournee.trim()) return
    setAnalysing(true)
    setError(null)
    try {
      const scores = await api.analyserJournee(descJournee, deviceCtx ?? undefined)
      setSante(scores.niveau_sante)
      setStress(scores.niveau_stress)
      setEnergie(scores.niveau_energie)
      setBonheur(scores.niveau_bonheur)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t('bilan.erreur_analyse'))
    } finally {
      setAnalysing(false)
    }
  }

  const handleSubmit = async () => {
    setSaving(true)
    setError(null)
    try {
      await api.creerBilan({
        niveau_sante: sante,
        niveau_stress: stress,
        niveau_energie: energie,
        niveau_bonheur: bonheur,
        heures_travail: hTravail,
        heures_sommeil: hSommeil,
        heures_loisirs: hLoisirs,
        heures_transport: hTransport,
        heures_objectif: hObjectif,
        description: descJournee,
      })
      // Save today's date so the daily check-in reminder won't fire again
      localStorage.setItem('sylea_last_checkin_date', new Date().toISOString().split('T')[0])
      // Recharger le profil (scores mis à jour)
      const updated = await api.getProfil()
      setProfil(updated)
      setDone(true)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t('bilan.erreur_enregistrement'))
    } finally {
      setSaving(false)
    }
  }

  if (!profil) {
    return (
      <div className="loading-center">
        <div className="spinner" />
        <p style={{ color: 'var(--text-muted)' }}>{t('bilan.chargement')}</p>
      </div>
    )
  }

  if (done) {
    return (
      <div className="page animate-fade-in">
        <div className="container page-content" style={{ display: 'flex', justifyContent: 'center' }}>
          <div
            className="card animate-fade-in-scale"
            style={{
              maxWidth: '480px',
              textAlign: 'center',
              padding: '2.5rem',
              border: '1px solid var(--success)',
              boxShadow: '0 0 32px rgba(34,197,94,0.15)',
            }}
          >
            <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>✓</div>
            <h3 style={{ color: 'var(--success)', marginBottom: '0.75rem' }}>{t('bilan.bilan_enregistre')}</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginBottom: '1.5rem', lineHeight: '1.5' }}>
              {t('bilan.bilan_sauvegarde')}
            </p>
            <button className="btn btn-primary btn-sm" onClick={() => navigate('/')}>
              {t('bilan.retour_dashboard')}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="page animate-fade-in">
      <div className="container page-content">

        {/* En-tête */}
        <div style={{ marginBottom: '2rem' }}>
          <h2 style={{ color: 'var(--accent-silver)', marginBottom: '0.375rem' }}>
            {t('bilan.titre_page')}
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            {t('bilan.subtitle')}
          </p>
        </div>

        <div className="card animate-fade-in-scale" style={{ maxWidth: '680px', margin: '0 auto' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>

            {/* Auto-évaluations */}
            <div>
              <p style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--accent-violet-light)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '1.25rem' }}>
                {t('bilan.auto_evaluations')}
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                {[
                  { label: t('bilan.sante_physique'),      val: sante,   set: setSante,   invert: false, lo: t('bilan.mauvaise'),      hi: t('bilan.excellente') },
                  { label: t('bilan.niveau_stress'),       val: stress,  set: setStress,  invert: true,  lo: t('bilan.tres_calme'),     hi: t('bilan.tres_stresse') },
                  { label: t('bilan.energie_quotidienne'), val: energie, set: setEnergie, invert: false, lo: t('bilan.epuise'),         hi: t('bilan.plein_energie') },
                  { label: t('bilan.bonheur_general'),     val: bonheur, set: setBonheur, invert: false, lo: t('bilan.tres_triste'),    hi: t('bilan.tres_heureux') },
                ].map(({ label, val, set, invert, lo, hi }) => (
                  <div key={label}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                      <label style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>{label}</label>
                      <span style={{ fontSize: '1rem', fontWeight: 800, color: scoreCol(val, invert), fontFamily: 'var(--font-mono)' }}>
                        {val}<span style={{ fontSize: '0.65rem', opacity: 0.5, fontWeight: 400 }}>/10</span>
                      </span>
                    </div>
                    <input
                      type="range" min="1" max="10" step="1" value={val}
                      onChange={e => set(parseInt(e.target.value))}
                      style={{ width: '100%', accentColor: scoreCol(val, invert) }}
                    />
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                      <span>{lo}</span><span>{hi}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Temps quotidien */}
            <div>
              <p style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--accent-gold)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '1.25rem' }}>
                {t('bilan.temps_quotidien')}
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1.1rem' }}>
                {[
                  { label: t('bilan.travail'),            val: hTravail,   set: setHTravail,   min: 0, max: 16, step: 0.5, gold: false },
                  { label: t('bilan.sommeil'),            val: hSommeil,   set: setHSommeil,   min: 3, max: 12, step: 0.5, gold: false },
                  { label: t('bilan.loisirs'),            val: hLoisirs,   set: setHLoisirs,   min: 0, max: 8,  step: 0.5, gold: false },
                  { label: t('bilan.transport'),          val: hTransport, set: setHTransport, min: 0, max: 6,  step: 0.5, gold: false },
                  { label: t('bilan.consacre_objectif'),  val: hObjectif,  set: setHObjectif,  min: 0, max: 8,  step: 0.5, gold: true  },
                ].map(({ label, val, set, min, max, step, gold }) => (
                  <div key={label}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.375rem' }}>
                      <label style={{ fontSize: '0.875rem', color: gold ? 'var(--accent-gold)' : 'var(--text-muted)', fontWeight: gold ? 600 : 400 }}>
                        {label}
                      </label>
                      <span style={{ fontSize: '0.9rem', fontWeight: 700, color: gold ? 'var(--accent-gold)' : 'var(--accent-silver)', fontFamily: 'var(--font-mono)' }}>
                        {fmt(val)}
                      </span>
                    </div>
                    <input
                      type="range" min={min} max={max} step={step} value={val}
                      onChange={e => set(parseFloat(e.target.value))}
                      style={{ width: '100%', accentColor: gold ? 'var(--accent-gold)' : 'var(--accent-violet)' }}
                    />
                  </div>
                ))}
              </div>
            </div>

            {/* Journée type */}
            <div>
              <p style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.625rem' }}>
                {t('bilan.raconter_journee')}
              </p>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '0.75rem', lineHeight: '1.5' }}>
                {t('bilan.raconter_desc')}
              </p>
              <textarea
                className="input" rows={4}
                value={descJournee}
                onChange={e => setDescJournee(e.target.value)}
                placeholder={t('bilan.description_placeholder')}
              />
              <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.75rem', justifyContent: 'flex-end' }}>
                <button
                  type="button" className="btn btn-outline btn-sm"
                  onClick={toggleVoice}
                  title="Saisie vocale" style={{ minWidth: '7.5rem' }}
                >
                  {voiceActive ? t('bilan.ecoute') : t('bilan.vocal')}
                </button>
                <button
                  type="button" className="btn btn-outline btn-sm"
                  onClick={analyserJournee} disabled={!descJournee.trim() || analysing}
                  style={{ minWidth: '13rem' }}
                >
                  {analysing ? t('bilan.analyse_cours') : t('bilan.analyser_ia')}
                </button>
              </div>
              {voiceError && (
                <p style={{ color: 'var(--accent-gold)', fontSize: '0.8rem', marginTop: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                  ⚠ {voiceError}
                </p>
              )}
            </div>

            {error && <p style={{ color: 'var(--danger)', fontSize: '0.875rem' }}>⚠ {error}</p>}

            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <button className="btn btn-outline" onClick={() => navigate('/')}>
                {t('bilan.retour')}
              </button>
              <button className="btn btn-gold" onClick={handleSubmit} disabled={saving}>
                {saving ? t('bilan.enregistrement') : t('bilan.enregistrer_bilan')}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
