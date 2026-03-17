// Page de création / modification du profil — 3 étapes
// Étape 1 : Identité + Objectif + Compétences
// Étape 2 : Questions personnalisées IA — saisie texte + vocale par question
// Étape 3 : Bien-être (scores + temps quotidien + analyse de journée)

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../store/useStore'
import { ConfirmProfilModal } from '../components/ConfirmProfilModal'
import { api } from '../api/client'
import type { ProfilIn } from '../types'
import { SITUATIONS_FAMILIALES } from '../types'

type Step = 'identite' | 'questions' | 'bien-etre'

// ── Helpers visuels ────────────────────────────────────────────────────────

function fmt(h: number): string {
  const hh = Math.floor(h)
  const mm = Math.round((h - hh) * 60)
  return mm === 0 ? `${hh}h` : `${hh}h${mm.toString().padStart(2, '0')}`
}

function scoreCol(s: number, invert = false): string {
  const v = invert ? 11 - s : s
  if (v <= 3) return 'var(--danger)'
  if (v <= 6) return 'var(--accent-gold)'
  return 'var(--success)'
}

// ── Composant principal ────────────────────────────────────────────────────

export function ProfilWizardPage() {
  const navigate  = useNavigate()
  const { profil, setProfil, setProbCalculee } = useStore()

  const [step,   setStep]   = useState<Step>('identite')
  const [saving, setSaving] = useState(false)
  const [error,  setError]  = useState<string | null>(null)
  const [showObjectifWarning, setShowObjectifWarning] = useState(false)

  // ── Identité ───────────────────────────────────────────────────────────────
  const [nom,        setNom]        = useState(() => profil?.nom        ?? '')
  const [age,        setAge]        = useState(() => profil ? String(profil.age) : '')
  const [profession, setProfession] = useState(() => profil?.profession  ?? '')
  const [ville,      setVille]      = useState(() => profil?.ville       ?? '')
  const [sitFam,     setSitFam]     = useState(() => profil?.situation_familiale ?? '')

  // Objectif (description seule — sans catégorie ni deadline)
  const [objDesc, setObjDesc] = useState(() => {
    if (!profil?.objectif) return ''
    const parts = profil.objectif.description.split('\n\n--- Contexte personnalisé ---\n')
    return parts[0]
  })

  // Tags
  const [competences, setCompetences] = useState<string[]>(() => profil?.competences ?? [])
  const [compInput,   setCompInput]   = useState('')
  const [diplomes,    setDiplomes]    = useState<string[]>(() => profil?.diplomes    ?? [])
  const [diplInput,   setDiplInput]   = useState('')
  const [langues,     setLangues]     = useState<string[]>(() => profil?.langues     ?? [])
  const [langInput,   setLangInput]   = useState('')

  // Champs financiers préservés (non affichés)
  const revenu     = profil?.revenu_annuel      ?? 0
  const patrimoine = profil?.patrimoine_estime  ?? 0
  const charges    = profil?.charges_mensuelles ?? 0
  const objFin     = profil?.objectif_financier ?? null

  // ── Questions ──────────────────────────────────────────────────────────────
  const [questionsGenerees,   setQuestionsGenerees]   = useState<string[]>([])
  const [generatingQuestions, setGeneratingQuestions] = useState(false)
  const [reponses,            setReponses]            = useState<Record<number, string>>({})
  // Index de la question dont la saisie vocale est active (-1 = aucune)
  const [activeVoiceIdx, setActiveVoiceIdx] = useState<number>(-1)

  // ── Bien-être — scores ────────────────────────────────────────────────────
  const [sante,   setSante]   = useState(() => profil?.niveau_sante   ?? 7)
  const [stress,  setStress]  = useState(() => profil?.niveau_stress  ?? 5)
  const [energie, setEnergie] = useState(() => profil?.niveau_energie ?? 7)
  const [bonheur, setBonheur] = useState(() => profil?.niveau_bonheur ?? 7)

  // ── Bien-être — temps quotidien ───────────────────────────────────────────
  const [hTravail,   setHTravail]   = useState(() => profil?.heures_travail   ?? 8)
  const [hSommeil,   setHSommeil]   = useState(() => profil?.heures_sommeil   ?? 7)
  const [hLoisirs,   setHLoisirs]   = useState(() => profil?.heures_loisirs   ?? 2)
  const [hTransport, setHTransport] = useState(() => profil?.heures_transport ?? 1)
  const [hObjectif,  setHObjectif]  = useState(() => (profil as any)?.heures_objectif ?? 1)

  // ── Journée ────────────────────────────────────────────────────────────────
  const [descJournee, setDescJournee] = useState('')
  const [analysing,   setAnalysing]   = useState(false)
  const [voiceActive, setVoiceActive] = useState(false)
  const [voiceError,  setVoiceError]  = useState<string | null>(null)

  // ── Saisie vocale générique ───────────────────────────────────────────────
  const startVoiceFor = (
    onResult: (transcript: string) => void,
    onStart: () => void,
    onEnd: () => void,
  ) => {
    setVoiceError(null)

    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) {
      setVoiceError('Saisie vocale non supportée — utilisez Chrome ou Edge.')
      return
    }

    const r = new SR()
    r.lang           = 'fr-FR'
    r.continuous     = false
    r.interimResults = false

    r.onstart  = () => onStart()
    r.onend    = () => onEnd()
    r.onerror  = (e: any) => {
      onEnd()
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        setVoiceError('Accès micro refusé — autorisez le microphone dans votre navigateur.')
      } else if (e.error === 'no-speech') {
        setVoiceError('Aucun son détecté — parlez plus près du microphone et réessayez.')
      } else if (e.error === 'audio-capture') {
        setVoiceError('Aucun microphone détecté sur cet appareil.')
      } else if (e.error !== 'aborted') {
        setVoiceError(`Erreur vocale : ${e.error}`)
      }
    }
    r.onresult = (e: any) => {
      const t = e.results[0][0].transcript
      onResult(t)
      setVoiceError(null)
    }

    try {
      r.start()
    } catch (err: any) {
      onEnd()
      setVoiceError(`Impossible de démarrer : ${err.message}`)
    }
  }

  // Saisie vocale pour une question spécifique
  const startVoiceQuestion = (idx: number) => {
    if (activeVoiceIdx !== -1) return
    startVoiceFor(
      (t) => setReponses(prev => ({ ...prev, [idx]: prev[idx] ? `${prev[idx]} ${t}` : t })),
      () => setActiveVoiceIdx(idx),
      () => setActiveVoiceIdx(-1),
    )
  }

  // Saisie vocale pour la journée type
  const startVoiceJournee = () => {
    startVoiceFor(
      (t) => setDescJournee(prev => prev ? `${prev} ${t}` : t),
      () => setVoiceActive(true),
      () => setVoiceActive(false),
    )
  }

  // ── Navigation ─────────────────────────────────────────────────────────────
  const goNext = async () => {
    if (step === 'identite') {
      if (!nom.trim() || !age || !profession.trim() || !objDesc.trim()) {
        setError('Veuillez remplir les champs obligatoires (*).')
        return
      }
      // Vérifier si l'objectif de vie a changé → confirmation
      if (profil?.objectif) {
        const _descFull = profil.objectif.description
        const _sepIdx = _descFull.indexOf('--- Contexte personnalisé ---')
        const existingObj = _sepIdx >= 0 ? _descFull.substring(0, _sepIdx).trim() : _descFull.trim()
        if (objDesc.trim() !== existingObj && !showObjectifWarning) {
          setShowObjectifWarning(true)
          return
        }
      }
      setShowObjectifWarning(false)
      setError(null)

      // Vérifier si l'objectif a changé pour décider de regénérer les questions
      let objectifChanged = true
      if (profil?.objectif) {
        const _df = profil.objectif.description
        const _si = _df.indexOf('--- Contexte personnalisé ---')
        const _existObj = _si >= 0 ? _df.substring(0, _si).trim() : _df.trim()
        objectifChanged = objDesc.trim() !== _existObj
      }

      if (!objectifChanged && profil?.objectif) {
        // Objectif inchangé : récupérer les questions et réponses existantes
        const fullDesc = profil.objectif.description
        const sepIdx = fullDesc.indexOf('--- Contexte personnalisé ---')
        if (sepIdx >= 0) {
          const contextPart = fullDesc.substring(sepIdx + '--- Contexte personnalisé ---'.length).trim()
          const qaPairs = contextPart.split('\n\nQ: ').filter(Boolean)
          const existingQuestions: string[] = []
          const existingReponses: Record<number, string> = {}
          qaPairs.forEach((pair, idx) => {
            const cleanPair = idx === 0 && pair.startsWith('Q: ') ? pair.substring(3) : pair
            const parts = cleanPair.split('\nR: ')
            if (parts.length >= 2) {
              existingQuestions.push(parts[0].trim())
              existingReponses[idx] = parts.slice(1).join('\nR: ').trim()
            } else {
              existingQuestions.push(cleanPair.trim())
            }
          })
          setQuestionsGenerees(existingQuestions)
          setReponses(existingReponses)
        } else {
          setQuestionsGenerees([])
        }
        setStep('questions')
      } else {
        // Objectif modifié ou nouveau profil : générer de nouvelles questions
        setGeneratingQuestions(true)
        try {
          const questions = await api.genererQuestions(objDesc.trim())
          setQuestionsGenerees(questions)
          setReponses({})  // Reset des réponses pour les nouvelles questions
        } catch {
          setQuestionsGenerees([])
        }
        setGeneratingQuestions(false)
        setStep('questions')
      }
    } else if (step === 'questions') {
      setError(null)
      setStep('bien-etre')
    }
  }

  const goPrev = () => {
    setError(null)
    if (step === 'questions')      setStep('identite')
    else if (step === 'bien-etre') setStep('questions')
  }

  // ── Analyse IA de la journée ──────────────────────────────────────────────
  const analyserJournee = async () => {
    if (!descJournee.trim()) return
    setAnalysing(true)
    try {
      const scores = await api.analyserJournee(descJournee)
      setSante(scores.niveau_sante)
      setStress(scores.niveau_stress)
      setEnergie(scores.niveau_energie)
      setBonheur(scores.niveau_bonheur)
    } catch { /* silencieux */ }
    finally { setAnalysing(false) }
  }

  // ── Helpers tags ──────────────────────────────────────────────────────────
  const addTag = (
    list: string[],
    setList: (v: string[]) => void,
    input: string,
    clearInput: () => void,
  ) => {
    const val = input.trim()
    if (val && !list.includes(val)) setList([...list, val])
    clearInput()
  }
  const removeTag = (list: string[], setList: (v: string[]) => void, i: number) =>
    setList(list.filter((_, j) => j !== i))

  // ── Soumission finale ─────────────────────────────────────────────────────
  const handleSubmit = async () => {
    setSaving(true)
    setError(null)
    try {
      const qa = Object.entries(reponses)
        .filter(([, r]) => r.trim())
        .map(([i, r]) => `Q: ${questionsGenerees[+i] ?? ''}\nR: ${r.trim()}`)
      const fullDesc = qa.length > 0
        ? `${objDesc.trim()}\n\n--- Contexte personnalisé ---\n${qa.join('\n\n')}`
        : objDesc.trim()

      // Détection de changement d’objectif de vie
      const existingDesc = profil?.objectif?.description
        .split('\n\n--- Contexte personnalis\u00e9 ---\n')[0].trim() ?? ''
      const objectifChange = objDesc.trim() !== existingDesc
      const resetHistorique = !!profil && objectifChange

      const data: ProfilIn = {
        nom:                 nom.trim(),
        age:                 parseInt(age),
        profession:          profession.trim(),
        ville:               ville.trim(),
        situation_familiale: sitFam,
        revenu_annuel:       revenu,
        patrimoine_estime:   patrimoine,
        charges_mensuelles:  charges,
        objectif_financier:  objFin,
        heures_travail:      hTravail,
        heures_sommeil:      hSommeil,
        heures_loisirs:      hLoisirs,
        heures_transport:    hTransport,
        heures_objectif:     hObjectif,
        niveau_sante:        sante,
        niveau_stress:       stress,
        niveau_energie:      energie,
        niveau_bonheur:      bonheur,
        competences,
        diplomes,
        langues,
        objectif: {
          description:      fullDesc,
          categorie:        '',
          deadline:         null,
          probabilite_base: 0,
        },
        reset_historique: resetHistorique,
      }

      const saved = await api.upsertProfil(data)
      setProfil(saved)
      if (resetHistorique) setProbCalculee(false)  // Force recalcul apres reset
      try {
        await api.recalculerProbabilite()
        const updated = await api.getProfil()
        setProfil(updated)
      } catch { /* si IA indisponible */ }
      navigate('/')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erreur lors de la sauvegarde')
    } finally {
      setSaving(false)
    }
  }

  // ── Indicateur d'étapes ────────────────────────────────────────────────────
  const STEPS: { key: Step; label: string; n: number }[] = [
    { key: 'identite',  label: 'Identité',  n: 1 },
    { key: 'questions', label: 'Questions', n: 2 },
    { key: 'bien-etre', label: 'Bien-être', n: 3 },
  ]
  const currentIdx = STEPS.findIndex(s => s.key === step)

  // ── Rendu ─────────────────────────────────────────────────────────────────
  return (
    <>
    <div className="page animate-fade-in">
      <div className="container page-content">

        {/* Flèche retour */}
        <button
          onClick={() => navigate('/')}
          style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: 'var(--text-muted)', fontSize: '0.88rem', padding: '0.25rem 0',
            display: 'flex', alignItems: 'center', gap: '0.4rem',
            marginBottom: '0.75rem', transition: 'color 0.15s',
          }}
          onMouseEnter={e => (e.currentTarget.style.color = 'var(--text-primary)')}
          onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-muted)')}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
          Retour au tableau de bord
        </button>

        {/* En-tête */}
        <div style={{ marginBottom: '2rem' }}>
          <h2 style={{ color: 'var(--accent-silver)', marginBottom: '0.375rem' }}>
            {profil ? 'Modifier mon profil' : 'Créer mon profil'}
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            Syléa.AI analyse votre situation pour calculer votre probabilité de réussite.
          </p>
        </div>

        {/* Indicateur d'étapes */}
        <div style={{ display: 'flex', alignItems: 'flex-start', marginBottom: '2rem' }}>
          {STEPS.map((s, i) => {
            const done   = i < currentIdx
            const active = i === currentIdx
            return (
              <div key={s.key} style={{ display: 'flex', alignItems: 'flex-start', flex: i < STEPS.length - 1 ? 1 : 'none' }}>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.375rem' }}>
                  <div style={{
                    width: '2rem', height: '2rem',
                    borderRadius: '50%',
                    background: done ? 'var(--success)' : active ? 'var(--accent-violet)' : 'var(--bg-elevated)',
                    border: `2px solid ${done ? 'var(--success)' : active ? 'var(--accent-violet)' : 'var(--border)'}`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '0.8rem', fontWeight: 700,
                    color: done || active ? 'white' : 'var(--text-muted)',
                    transition: 'all 0.3s',
                    flexShrink: 0,
                  }}>
                    {done ? '✓' : s.n}
                  </div>
                  <span style={{
                    fontSize: '0.68rem',
                    color: active ? 'var(--accent-violet-light)' : 'var(--text-muted)',
                    letterSpacing: '0.06em',
                    whiteSpace: 'nowrap',
                    textTransform: 'uppercase',
                  }}>
                    {s.label}
                  </span>
                </div>
                {i < STEPS.length - 1 && (
                  <div style={{
                    flex: 1,
                    height: '2px',
                    background: done ? 'var(--success)' : 'var(--border)',
                    margin: '1rem 0.5rem 0',
                    transition: 'background 0.3s',
                  }} />
                )}
              </div>
            )
          })}
        </div>

        {/* ═══ ÉTAPE 1 — IDENTITÉ ══════════════════════════════════════════════ */}
        {step === 'identite' && (
          <div className="card animate-fade-in-scale">
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>

              {/* Informations personnelles */}
              <div>
                <p style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--accent-violet-light)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '1rem' }}>
                  ◈ Informations personnelles
                </p>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  <div className="input-group">
                    <label className="input-label">Nom complet <span style={{ color: 'var(--accent-gold)' }}>*</span></label>
                    <input className="input" value={nom} onChange={e => setNom(e.target.value)} placeholder="Marie Dupont" />
                  </div>
                  <div className="input-group">
                    <label className="input-label">Âge <span style={{ color: 'var(--accent-gold)' }}>*</span></label>
                    <input className="input" type="number" min="1" max="120" value={age} onChange={e => setAge(e.target.value)} placeholder="35" />
                  </div>
                  <div className="input-group">
                    <label className="input-label">Profession <span style={{ color: 'var(--accent-gold)' }}>*</span></label>
                    <input className="input" value={profession} onChange={e => setProfession(e.target.value)} placeholder="Ingénieure logiciel" />
                  </div>
                  <div className="input-group">
                    <label className="input-label">Ville</label>
                    <input className="input" value={ville} onChange={e => setVille(e.target.value)} placeholder="Paris" />
                  </div>
                </div>
                <div className="input-group" style={{ marginTop: '1rem' }}>
                  <label className="input-label">Situation familiale <span style={{ color: 'var(--accent-gold)' }}>*</span></label>
                  <select className="input" value={sitFam} onChange={e => setSitFam(e.target.value)}>
                    <option value="">— Sélectionner —</option>
                    {SITUATIONS_FAMILIALES.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
              </div>

              {/* Objectif de vie */}
              <div>
                <p style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--accent-gold)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '1rem' }}>
                  ◈ Votre objectif de vie
                </p>
                <div className="input-group">
                  <label className="input-label">
                    Description <span style={{ color: 'var(--accent-gold)' }}>*</span>
                  </label>
                  <textarea
                    className="input"
                    rows={3}
                    value={objDesc}
                    onChange={e => setObjDesc(e.target.value)}
                    placeholder="Ex: Lancer ma startup dans l'IA et atteindre 100 000 € de revenus annuels en 3 ans"
                  />
                </div>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.5rem', lineHeight: '1.5' }}>
                  ✦ Syléa.AI génèrera des questions personnalisées basées sur votre objectif à l'étape suivante.
                </p>
              </div>

              {/* Compétences & formation */}
              <div>
                <p style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '1rem' }}>
                  ◈ Compétences & formation (optionnel)
                </p>
                {[
                  { label: 'Compétences', list: competences, setList: setCompetences, input: compInput, setInput: setCompInput, ph: 'Ex: Python, leadership…' },
                  { label: 'Diplômes',    list: diplomes,    setList: setDiplomes,    input: diplInput, setInput: setDiplInput, ph: 'Ex: Master Finance…' },
                  { label: 'Langues',     list: langues,     setList: setLangues,     input: langInput, setInput: setLangInput, ph: 'Ex: Anglais C1…' },
                ].map(({ label, list, setList, input, setInput, ph }) => (
                  <div className="input-group" key={label}>
                    <label className="input-label">{label}</label>
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      <input
                        className="input"
                        value={input}
                        onChange={e => setInput(e.target.value)}
                        placeholder={ph}
                        onKeyDown={e => {
                          if (e.key === 'Enter') { e.preventDefault(); addTag(list, setList, input, () => setInput('')) }
                        }}
                        style={{ flex: 1 }}
                      />
                      <button type="button" className="btn btn-outline btn-sm"
                        onClick={() => addTag(list, setList, input, () => setInput(''))}>+</button>
                    </div>
                    {list.length > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.375rem', marginTop: '0.5rem' }}>
                        {list.map((item, i) => (
                          <span key={i} className="badge" style={{
                            background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                            display: 'flex', alignItems: 'center', gap: '0.375rem',
                          }}>
                            {item}
                            <span onClick={() => removeTag(list, setList, i)}
                              style={{ color: 'var(--danger)', fontWeight: 700, cursor: 'pointer' }}>×</span>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {error && <p style={{ color: 'var(--danger)', fontSize: '0.875rem' }}>⚠ {error}</p>}

              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button className="btn btn-primary" onClick={goNext} disabled={generatingQuestions}>
                  {generatingQuestions
                    ? (
                      <span style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
                        <span style={{
                          width: '14px', height: '14px', borderRadius: '50%',
                          border: '2px solid rgba(255,255,255,0.3)', borderTop: '2px solid white',
                          animation: 'spin 0.7s linear infinite', display: 'inline-block',
                        }} />
                        Génération des questions…
                      </span>
                    )
                    : 'Étape suivante →'
                  }
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ═══ ÉTAPE 2 — QUESTIONS ═════════════════════════════════════════════ */}
        {step === 'questions' && (
          <div className="card animate-fade-in-scale">
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

              <div>
                <p style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--accent-violet-light)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.5rem' }}>
                  ◈ Questions sur votre objectif
                </p>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', lineHeight: '1.5' }}>
                  Ces questions ont été générées par Syléa.AI spécifiquement pour votre objectif. Répondez librement, par écrit ou à voix haute.
                </p>
              </div>

              {questionsGenerees.length === 0 ? (
                <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', fontStyle: 'italic', textAlign: 'center', padding: '1.5rem 0' }}>
                  Aucune question générée. Vous pouvez passer directement à l'étape suivante.
                </p>
              ) : (
                questionsGenerees.map((q, i) => {
                  const isListening = activeVoiceIdx === i
                  return (
                    <div className="input-group" key={i}>
                      <label className="input-label" style={{
                        color: 'var(--text-secondary)', display: 'flex', gap: '0.625rem', alignItems: 'flex-start',
                      }}>
                        <span style={{
                          color: 'var(--accent-gold)', fontFamily: 'var(--font-mono)',
                          fontSize: '0.75rem', flexShrink: 0, paddingTop: '0.1rem',
                        }}>
                          {(i + 1).toString().padStart(2, '0')}
                        </span>
                        <span>{q}</span>
                      </label>
                      <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.375rem', alignItems: 'flex-start' }}>
                        <textarea
                          className="input"
                          rows={2}
                          value={reponses[i] ?? ''}
                          onChange={e => setReponses(prev => ({ ...prev, [i]: e.target.value }))}
                          placeholder="Votre réponse…"
                          style={{ flex: 1, resize: 'vertical' }}
                        />
                        <button
                          type="button"
                          onClick={() => startVoiceQuestion(i)}
                          disabled={activeVoiceIdx !== -1 && !isListening}
                          title={isListening ? 'Écoute en cours…' : 'Répondre à voix haute'}
                          style={{
                            flexShrink: 0,
                            width: '36px',
                            height: '36px',
                            borderRadius: '8px',
                            border: `1px solid ${isListening ? 'var(--accent-violet)' : 'var(--border)'}`,
                            background: isListening ? 'rgba(124,58,237,0.2)' : 'var(--bg-elevated)',
                            color: isListening ? 'var(--accent-violet-light)' : 'var(--text-muted)',
                            cursor: activeVoiceIdx !== -1 && !isListening ? 'not-allowed' : 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: '1rem',
                            opacity: activeVoiceIdx !== -1 && !isListening ? 0.4 : 1,
                            transition: 'all 0.2s',
                            animation: isListening ? 'pulse 1s ease-in-out infinite' : 'none',
                          }}
                        >
                          🎤
                        </button>
                      </div>
                      {isListening && (
                        <p style={{
                          fontSize: '0.75rem',
                          color: 'var(--accent-violet-light)',
                          marginTop: '0.25rem',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.375rem',
                        }}>
                          <span style={{
                            width: '6px', height: '6px', borderRadius: '50%',
                            background: 'var(--accent-violet)',
                            animation: 'pulse 0.8s ease-in-out infinite',
                            display: 'inline-block',
                          }} />
                          Écoute en cours…
                        </p>
                      )}
                    </div>
                  )
                })
              )}

              {voiceError && (
                <p style={{ color: 'var(--accent-gold)', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                  ⚠ {voiceError}
                </p>
              )}

              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '0.5rem' }}>
                <button className="btn btn-outline" onClick={goPrev}>← Précédent</button>
                <button className="btn btn-primary" onClick={goNext}>Étape suivante →</button>
              </div>
            </div>
          </div>
        )}

        {/* ═══ ÉTAPE 3 — BIEN-ÊTRE ═════════════════════════════════════════════ */}
        {step === 'bien-etre' && (
          <div className="card animate-fade-in-scale">
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>

              {/* Auto-évaluations */}
              <div>
                <p style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--accent-violet-light)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '1.25rem' }}>
                  ◈ Auto-évaluations (1 – 10)
                </p>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                  {[
                    { label: 'Santé physique',      val: sante,   set: setSante,   invert: false, lo: 'Mauvaise',      hi: 'Excellente' },
                    { label: 'Niveau de stress',     val: stress,  set: setStress,  invert: true,  lo: 'Très calme',    hi: 'Très stressé' },
                    { label: 'Énergie quotidienne',  val: energie, set: setEnergie, invert: false, lo: 'Épuisé(e)',     hi: "Plein d'énergie" },
                    { label: 'Bonheur général',      val: bonheur, set: setBonheur, invert: false, lo: 'Très triste',   hi: 'Très heureux/se' },
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
                  ◈ Temps quotidien
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.1rem' }}>
                  {[
                    { label: 'Travail',                 val: hTravail,   set: setHTravail,   min: 0, max: 16, step: 0.5, gold: false },
                    { label: 'Sommeil',                 val: hSommeil,   set: setHSommeil,   min: 3, max: 12, step: 0.5, gold: false },
                    { label: 'Loisirs',                 val: hLoisirs,   set: setHLoisirs,   min: 0, max: 8,  step: 0.5, gold: false },
                    { label: 'Transport',               val: hTransport, set: setHTransport, min: 0, max: 6,  step: 0.5, gold: false },
                    { label: 'Consacré à mon objectif', val: hObjectif,  set: setHObjectif,  min: 0, max: 8,  step: 0.5, gold: true  },
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
                  ◈ Racontez votre journée type (optionnel)
                </p>
                <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '0.75rem', lineHeight: '1.5' }}>
                  Décrivez librement votre journée — Syléa.AI analysera votre texte et remplira automatiquement les scores ci-dessus.
                </p>
                <textarea
                  className="input" rows={4}
                  value={descJournee}
                  onChange={e => setDescJournee(e.target.value)}
                  placeholder="Ex : Je me suis levé à 7h, bien dormi. La réunion du matin était stressante mais j'ai été très productif l'après-midi. Je me sens fatigué mais satisfait…"
                />
                <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.75rem', justifyContent: 'flex-end' }}>
                  <button
                    type="button" className="btn btn-outline btn-sm"
                    onClick={startVoiceJournee} disabled={voiceActive}
                    title="Saisie vocale (français)" style={{ minWidth: '7.5rem' }}
                  >
                    {voiceActive ? '⏺ Écoute…' : '🎤 Vocal'}
                  </button>
                  <button
                    type="button" className="btn btn-outline btn-sm"
                    onClick={analyserJournee} disabled={!descJournee.trim() || analysing}
                    style={{ minWidth: '13rem' }}
                  >
                    {analysing ? 'Analyse en cours…' : "⟡ Analyser avec l'IA"}
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
                <button className="btn btn-outline" onClick={goPrev}>← Précédent</button>
                <button className="btn btn-gold" onClick={handleSubmit} disabled={saving}>
                  {saving ? 'Enregistrement…' : profil ? '✓ Mettre à jour' : '✓ Créer mon profil'}
                </button>
              </div>
            </div>
          </div>
        )}

      </div>
    </div>

    {/* Modale confirmation changement d'objectif */}
    {showObjectifWarning && (
      <div style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <div className="card" style={{ maxWidth: 420, padding: '2rem', textAlign: 'center' }}>
          <div style={{ fontSize: '2.5rem', marginBottom: '0.75rem' }}>⚠️</div>
          <h3 style={{ marginBottom: '0.75rem' }}>Objectif de vie modifié</h3>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.88rem', lineHeight: 1.6 }}>
            Votre historique de <span style={{ color: '#ef4444' }}>décisions, sous-objectifs et tâches</span> sera
            réinitialisé. Voulez-vous continuer ?
          </p>
          <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1.25rem' }}>
            <button className="btn" style={{ flex: 1 }} onClick={() => setShowObjectifWarning(false)}>Annuler</button>
            <button className="btn btn-primary" style={{ flex: 1 }} onClick={() => goNext()}>Continuer</button>
          </div>
        </div>
      </div>
    )}
    </>
  )
}
