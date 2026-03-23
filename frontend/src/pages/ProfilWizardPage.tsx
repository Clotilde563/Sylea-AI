// Page de création / modification du profil — 3 étapes
// Étape 1 : Identité + Objectif + Compétences
// Étape 2 : Questions personnalisées IA — saisie texte + vocale par question
// Étape 3 : Bien-être (scores + temps quotidien + analyse de journée)

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../store/useStore'
import { ConfirmProfilModal } from '../components/ConfirmProfilModal'
import { api } from '../api/client'
import { useDeviceContext } from '../contexts/DeviceContext'
import type { ProfilIn } from '../types'
import { SITUATIONS_FAMILIALES } from '../types'
import { useT } from '../i18n/LanguageContext'

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
  const t = useT()
  const { ctx: deviceCtx } = useDeviceContext()
  const { profil, setProfil, setProbCalculee } = useStore()

  // Mode creation (profil is null) vs edition (profil exists for this user)
  const isCreate = !profil

  const [step,   setStep]   = useState<Step>('identite')
  const [saving, setSaving] = useState(false)
  const [error,  setError]  = useState<string | null>(null)
  const [showObjectifWarning, setShowObjectifWarning] = useState(false)

  // ── Identité ───────────────────────────────────────────────────────────────
  // When creating a new profile, ALL fields start empty regardless of any stale store data
  const [nom,        setNom]        = useState(() => isCreate ? '' : (profil?.nom        ?? ''))
  const [age,        setAge]        = useState(() => isCreate ? '' : (profil ? String(profil.age) : ''))
  const [genre,      setGenre]      = useState(() => isCreate ? '' : (profil?.genre       ?? ''))
  const [profession, setProfession] = useState(() => isCreate ? '' : (profil?.profession  ?? ''))
  const [ville,      setVille]      = useState(() => isCreate ? '' : (profil?.ville       ?? ''))
  const [sitFam,     setSitFam]     = useState(() => isCreate ? '' : (profil?.situation_familiale ?? ''))

  // Objectif (description seule — sans catégorie ni deadline)
  const [objDesc, setObjDesc] = useState(() => {
    if (isCreate || !profil?.objectif) return ''
    const parts = profil.objectif.description.split('\n\n--- Contexte personnalisé ---\n')
    return parts[0]
  })

  // Tags
  const [competences, setCompetences] = useState<string[]>(() => isCreate ? [] : (profil?.competences ?? []))
  const [compInput,   setCompInput]   = useState('')
  const [diplomes,    setDiplomes]    = useState<string[]>(() => isCreate ? [] : (profil?.diplomes    ?? []))
  const [diplInput,   setDiplInput]   = useState('')
  const [langues,     setLangues]     = useState<string[]>(() => isCreate ? [] : (profil?.langues     ?? []))
  const [langInput,   setLangInput]   = useState('')

  // Champs financiers préservés (non affichés)
  const revenu     = isCreate ? 0    : (profil?.revenu_annuel      ?? 0)
  const patrimoine = isCreate ? 0    : (profil?.patrimoine_estime  ?? 0)
  const charges    = isCreate ? 0    : (profil?.charges_mensuelles ?? 0)
  const objFin     = isCreate ? null : (profil?.objectif_financier ?? null)

  // ── Questions ──────────────────────────────────────────────────────────────
  const [questionsGenerees,   setQuestionsGenerees]   = useState<string[]>([])
  const [generatingQuestions, setGeneratingQuestions] = useState(false)
  const [reponses,            setReponses]            = useState<Record<number, string>>({})
  const [questionsReadOnly,   setQuestionsReadOnly]   = useState(false)
  // Index de la question dont la saisie vocale est active (-1 = aucune)
  const [activeVoiceIdx, setActiveVoiceIdx] = useState<number>(-1)

  // ── Bien-être — scores ────────────────────────────────────────────────────
  const [sante,   setSante]   = useState(() => isCreate ? 7 : (profil?.niveau_sante   ?? 7))
  const [stress,  setStress]  = useState(() => isCreate ? 5 : (profil?.niveau_stress  ?? 5))
  const [energie, setEnergie] = useState(() => isCreate ? 7 : (profil?.niveau_energie ?? 7))
  const [bonheur, setBonheur] = useState(() => isCreate ? 7 : (profil?.niveau_bonheur ?? 7))

  // ── Bien-être — temps quotidien ───────────────────────────────────────────
  const [hTravail,   setHTravail]   = useState(() => isCreate ? 8 : (profil?.heures_travail   ?? 8))
  const [hSommeil,   setHSommeil]   = useState(() => isCreate ? 7 : (profil?.heures_sommeil   ?? 7))
  const [hLoisirs,   setHLoisirs]   = useState(() => isCreate ? 2 : (profil?.heures_loisirs   ?? 2))
  const [hTransport, setHTransport] = useState(() => isCreate ? 1 : (profil?.heures_transport ?? 1))
  const [hObjectif,  setHObjectif]  = useState(() => isCreate ? 1 : ((profil as any)?.heures_objectif ?? 1))

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
        setError(t('common.obligatoires'))
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
          // Des réponses existent → les afficher en lecture seule
          setQuestionsReadOnly(true)
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
          setStep('questions')
        } else {
          // Pas de contexte personnalisé → générer les questions (modifiables)
          setQuestionsReadOnly(false)
          setGeneratingQuestions(true)
          try {
            const questions = await api.genererQuestions(objDesc.trim(), deviceCtx ?? undefined)
            setQuestionsGenerees(questions)
            setReponses({})
          } catch {
            setQuestionsGenerees([])
          }
          setGeneratingQuestions(false)
          setStep('questions')
        }
      } else {
        // Objectif modifié ou nouveau profil : générer de nouvelles questions
        setQuestionsReadOnly(false)
        setGeneratingQuestions(true)
        try {
          const questions = await api.genererQuestions(objDesc.trim(), deviceCtx ?? undefined)
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
      const scores = await api.analyserJournee(descJournee, deviceCtx ?? undefined)
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
        genre:               genre,
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
        await api.recalculerProbabilite(deviceCtx ?? undefined)
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
    { key: 'identite',  label: t('profil.step_identite'),  n: 1 },
    { key: 'questions', label: t('profil.step_questions'), n: 2 },
    { key: 'bien-etre', label: t('profil.step_bienetre'), n: 3 },
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
          {t('common.retour_dashboard').replace('← ', '')}
        </button>

        {/* En-tête */}
        <div style={{ marginBottom: '2rem' }}>
          <h2 style={{ color: 'var(--accent-silver)', marginBottom: '0.375rem' }}>
            {profil ? t('profil.modifier_profil') : t('profil.creer_profil')}
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            {t('profil.analyse_description')}
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
                  ◈ {t('profil.infos_personnelles')}
                </p>
                <div className="input-group" style={{ marginBottom: '1rem' }}>
                  <label className="input-label">{t('settings.genre')} <span style={{ color: 'var(--accent-gold)' }}>*</span></label>
                  <select className="input" value={genre} onChange={e => setGenre(e.target.value)}>
                    <option value="">{t('common.selectionner')}</option>
                    <option value="Homme">{t('common.homme')}</option>
                    <option value="Femme">{t('common.femme')}</option>
                  </select>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  <div className="input-group">
                    <label className="input-label">{t('profil.nom_complet')} <span style={{ color: 'var(--accent-gold)' }}>*</span></label>
                    <input className="input" value={nom} onChange={e => setNom(e.target.value)} placeholder="Marie Dupont" />
                  </div>
                  <div className="input-group">
                    <label className="input-label">{t('settings.age')} <span style={{ color: 'var(--accent-gold)' }}>*</span></label>
                    <input className="input" type="number" min="1" max="120" value={age} onChange={e => setAge(e.target.value)} placeholder="35" />
                  </div>
                  <div className="input-group">
                    <label className="input-label">{t('settings.profession')} <span style={{ color: 'var(--accent-gold)' }}>*</span></label>
                    <input className="input" value={profession} onChange={e => setProfession(e.target.value)} placeholder="Ingénieure logiciel" />
                  </div>
                  <div className="input-group">
                    <label className="input-label">{t('settings.ville')}</label>
                    <input className="input" value={ville} onChange={e => setVille(e.target.value)} placeholder="Paris" />
                  </div>
                </div>
                <div className="input-group" style={{ marginTop: '1rem' }}>
                  <label className="input-label">{t('settings.situation')} <span style={{ color: 'var(--accent-gold)' }}>*</span></label>
                  <select className="input" value={sitFam} onChange={e => setSitFam(e.target.value)}>
                    <option value="">{t('common.selectionner')}</option>
                    {SITUATIONS_FAMILIALES.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
              </div>

              {/* Objectif de vie */}
              <div>
                <p style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--accent-gold)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '1rem' }}>
                  ◈ {t('profil.objectif_vie')}
                </p>
                <div className="input-group">
                  <label className="input-label">
                    {t('profil.description_objectif')} <span style={{ color: 'var(--accent-gold)' }}>*</span>
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
                  {t('profil.sylea_genere_questions')}
                </p>
              </div>

              {/* Compétences & formation */}
              <div>
                <p style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '1rem' }}>
                  ◈ {t('profil.competences_formation')}
                </p>
                {[
                  { label: t('profil.competences_label'), list: competences, setList: setCompetences, input: compInput, setInput: setCompInput, ph: 'Ex: Python, leadership…' },
                  { label: t('profil.diplomes_label'),    list: diplomes,    setList: setDiplomes,    input: diplInput, setInput: setDiplInput, ph: 'Ex: Master Finance…' },
                  { label: t('profil.langues_label'),     list: langues,     setList: setLangues,     input: langInput, setInput: setLangInput, ph: 'Ex: Anglais C1…' },
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
                        {t('profil.generation_questions')}
                      </span>
                    )
                    : t('common.suivant')
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
                  ◈ {t('profil.questions_objectif')}
                </p>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', lineHeight: '1.5' }}>
                  {questionsReadOnly
                    ? t('profil.questions_readonly')
                    : t('profil.questions_desc')}
                </p>
                {questionsReadOnly && (
                  <div style={{
                    display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
                    padding: '0.3rem 0.75rem', borderRadius: '999px', fontSize: '0.7rem', fontWeight: 600,
                    background: 'rgba(59,130,246,0.1)', color: '#60a5fa', border: '1px solid rgba(59,130,246,0.2)',
                    marginTop: '0.25rem',
                  }}>
                    <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}><rect x={3} y={11} width={18} height={11} rx={2}/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                    {t('profil.lecture_seule')}
                  </div>
                )}
              </div>

              {questionsGenerees.length === 0 ? (
                <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', fontStyle: 'italic', textAlign: 'center', padding: '1.5rem 0' }}>
                  {t('profil.aucune_question')}
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
                          onChange={e => { if (!questionsReadOnly) setReponses(prev => ({ ...prev, [i]: e.target.value })) }}
                          readOnly={questionsReadOnly}
                          placeholder={t('profil.votre_reponse')}
                          style={{
                            flex: 1, resize: questionsReadOnly ? 'none' : 'vertical',
                            opacity: questionsReadOnly ? 0.7 : 1,
                            cursor: questionsReadOnly ? 'default' : undefined,
                            background: questionsReadOnly ? 'rgba(255,255,255,0.02)' : undefined,
                          }}
                        />
                        {!questionsReadOnly && (
                        <button
                          type="button"
                          onClick={() => startVoiceQuestion(i)}
                          disabled={activeVoiceIdx !== -1 && !isListening}
                          title={isListening ? t('profil.ecoute_cours') : t('profil.repondre_voix')}
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
                        )}
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
                          {t('profil.ecoute_cours')}
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
                <button className="btn btn-outline" onClick={goPrev}>{t('common.precedent')}</button>
                <button className="btn btn-primary" onClick={goNext}>{t('common.suivant')}</button>
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
                  ◈ {t('profil.auto_evaluations')}
                </p>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                  {[
                    { label: t('profil.sante_physique'),      val: sante,   set: setSante,   invert: false, lo: t('profil.mauvaise'),      hi: t('profil.excellente') },
                    { label: t('profil.niveau_stress'),     val: stress,  set: setStress,  invert: true,  lo: t('profil.tres_calme'),    hi: t('profil.tres_stresse') },
                    { label: t('profil.energie_quotidienne'),  val: energie, set: setEnergie, invert: false, lo: t('profil.epuise'),     hi: t('profil.plein_energie') },
                    { label: t('profil.bonheur_general'),      val: bonheur, set: setBonheur, invert: false, lo: t('profil.tres_triste'),   hi: t('profil.tres_heureux') },
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
                  ◈ {t('profil.temps_quotidien')}
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.1rem' }}>
                  {[
                    { label: t('profil.travail'),                 val: hTravail,   set: setHTravail,   min: 0, max: 16, step: 0.5, gold: false },
                    { label: t('profil.sommeil'),                 val: hSommeil,   set: setHSommeil,   min: 3, max: 12, step: 0.5, gold: false },
                    { label: t('profil.loisirs'),                 val: hLoisirs,   set: setHLoisirs,   min: 0, max: 8,  step: 0.5, gold: false },
                    { label: t('profil.transport'),               val: hTransport, set: setHTransport, min: 0, max: 6,  step: 0.5, gold: false },
                    { label: t('profil.consacre_objectif'), val: hObjectif,  set: setHObjectif,  min: 0, max: 8,  step: 0.5, gold: true  },
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
                  ◈ {t('profil.racontez_journee')}
                </p>
                <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '0.75rem', lineHeight: '1.5' }}>
                  {t('profil.decrivez_journee')}
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
                    {voiceActive ? t('profil.vocal_ecoute') : t('profil.vocal_btn')}
                  </button>
                  <button
                    type="button" className="btn btn-outline btn-sm"
                    onClick={analyserJournee} disabled={!descJournee.trim() || analysing}
                    style={{ minWidth: '13rem' }}
                  >
                    {analysing ? t('profil.analyse_cours_profil') : t('profil.analyser_ia')}
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
                <button className="btn btn-outline" onClick={goPrev}>{t('common.precedent')}</button>
                <button className="btn btn-gold" onClick={handleSubmit} disabled={saving}>
                  {saving ? t('profil.enregistrement') : profil ? t('profil.mettre_a_jour') : t('profil.creer_mon_profil_btn')}
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
          <h3 style={{ marginBottom: '0.75rem' }}>{t('profil.objectif_modifie')}</h3>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.88rem', lineHeight: 1.6 }}>
            Votre historique de <span style={{ color: '#ef4444' }}>{t('profil.objectif_modifie_desc')}</span> {t('profil.objectif_modifie_msg')}
          </p>
          <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1.25rem' }}>
            <button className="btn" style={{ flex: 1 }} onClick={() => setShowObjectifWarning(false)}>{t('common.annuler')}</button>
            <button className="btn btn-primary" style={{ flex: 1 }} onClick={() => goNext()}>{t('profil.continuer')}</button>
          </div>
        </div>
      </div>
    )}
    </>
  )
}
