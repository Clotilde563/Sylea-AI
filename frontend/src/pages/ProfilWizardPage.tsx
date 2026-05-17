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

// Couleurs et libelles par categorie de question.
// `key` est l'identite stable utilisee pour deduper / matcher (plusieurs cats
// raw differentes peuvent partager la meme key, ex: `competences` + `experience`).
function categoryStyle(cat: string): { bg: string; color: string; border: string; label: string; key: string } {
  const c = (cat || '').toLowerCase()
  if (c.includes('budget') || c.includes('finance') || c.includes('argent'))
    return { bg: 'rgba(245,158,11,0.15)', color: '#fbbf24', border: 'rgba(245,158,11,0.3)', label: 'Budget', key: 'budget' }
  if (c.includes('temps') || c.includes('disponi'))
    return { bg: 'rgba(124,58,237,0.15)', color: '#a78bfa', border: 'rgba(124,58,237,0.3)', label: 'Temps', key: 'temps' }
  if (c.includes('comp') || c.includes('skill') || c.includes('experience'))
    return { bg: 'rgba(34,197,94,0.15)', color: '#4ade80', border: 'rgba(34,197,94,0.3)', label: 'Compétences', key: 'competences' }
  if (c.includes('contrainte') || c.includes('obstacle') || c.includes('block'))
    return { bg: 'rgba(239,68,68,0.15)', color: '#f87171', border: 'rgba(239,68,68,0.3)', label: 'Contraintes', key: 'contraintes' }
  if (c.includes('motiv') || c.includes('pourquoi'))
    return { bg: 'rgba(236,72,153,0.15)', color: '#f472b6', border: 'rgba(236,72,153,0.3)', label: 'Motivation', key: 'motivation' }
  if (c.includes('reseau') || c.includes('relation') || c.includes('entou'))
    return { bg: 'rgba(59,130,246,0.15)', color: '#60a5fa', border: 'rgba(59,130,246,0.3)', label: 'Réseau', key: 'reseau' }
  if (c.includes('ressource') || c.includes('outil') || c.includes('mater'))
    return { bg: 'rgba(20,184,166,0.15)', color: '#2dd4bf', border: 'rgba(20,184,166,0.3)', label: 'Ressources', key: 'ressources' }
  if (c.includes('plan') || c.includes('strat') || c.includes('etape'))
    return { bg: 'rgba(168,85,247,0.15)', color: '#c084fc', border: 'rgba(168,85,247,0.3)', label: 'Stratégie', key: 'strategie' }
  if (c.includes('environ'))
    return { bg: 'rgba(20,184,166,0.15)', color: '#2dd4bf', border: 'rgba(20,184,166,0.3)', label: 'Environnement', key: 'environnement' }
  if (c.includes('sante') || c.includes('santé') || c.includes('health'))
    return { bg: 'rgba(244,63,94,0.15)', color: '#fb7185', border: 'rgba(244,63,94,0.3)', label: 'Santé', key: 'sante' }
  // Default : utilise le raw cat comme key (chaque raw distinct = bucket distinct)
  const fallbackLabel = cat ? cat.charAt(0).toUpperCase() + cat.slice(1).toLowerCase() : 'Contexte'
  return { bg: 'rgba(148,163,184,0.15)', color: '#94a3b8', border: 'rgba(148,163,184,0.3)', label: fallbackLabel, key: c || 'general' }
}

// Helper : retourne la key stable d'une categorie pour deduper / matcher
function catKey(rawCat: string | null | undefined): string {
  return categoryStyle((rawCat || '').toLowerCase()).key
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
  // Refonte UX : nombre VARIABLE 3-15 + metadata (category, why_it_matters,
  // expected_format) + validation coherence par IA + animations gamifiees.
  type QuestionMeta = {
    question: string
    category: string
    why_it_matters: string
    expected_format: string
  }
  const [questionsGenerees,   setQuestionsGenerees]   = useState<string[]>([])
  const [questionsMeta,       setQuestionsMeta]       = useState<QuestionMeta[]>([])
  const [generatingQuestions, setGeneratingQuestions] = useState(false)
  const [reponses,            setReponses]            = useState<Record<number, string>>({})
  const [questionsReadOnly,   setQuestionsReadOnly]   = useState(false)
  // Index de la question dont la saisie vocale est active (-1 = aucune)
  const [activeVoiceIdx, setActiveVoiceIdx] = useState<number>(-1)
  // Coherence validation
  const [validatingCoherence, setValidatingCoherence] = useState(false)
  const [coherenceIssues,     setCoherenceIssues]     = useState<Array<{ question_idx: number; issue: string; suggestion: string }>>([])
  // Hints "Why it matters" expansibles
  const [expandedHints,       setExpandedHints]       = useState<Set<number>>(new Set())
  // Index de la categorie courante dans le flow par chapitres (0 = premiere)
  const [currentCategoryIdx,  setCurrentCategoryIdx]  = useState(0)

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
          setQuestionsMeta([])
          setReponses(existingReponses)
          setCoherenceIssues([])
          setCurrentCategoryIdx(0)
          setStep('questions')
        } else {
          // Pas de contexte personnalisé → générer les questions enrichies (modifiables)
          setQuestionsReadOnly(false)
          setGeneratingQuestions(true)
          try {
            const enriched = await api.genererQuestionsEnriched(objDesc.trim(), deviceCtx ?? undefined)
            setQuestionsMeta(enriched)
            setQuestionsGenerees(enriched.map(q => q.question))
            setReponses({})
            setCoherenceIssues([])
            setCurrentCategoryIdx(0)
          } catch {
            setQuestionsGenerees([])
            setQuestionsMeta([])
          }
          setGeneratingQuestions(false)
          setStep('questions')
        }
      } else {
        // Objectif modifié ou nouveau profil : générer de nouvelles questions enrichies
        setQuestionsReadOnly(false)
        setGeneratingQuestions(true)
        try {
          const enriched = await api.genererQuestionsEnriched(objDesc.trim(), deviceCtx ?? undefined)
          setQuestionsMeta(enriched)
          setQuestionsGenerees(enriched.map(q => q.question))
          setReponses({})
          setCoherenceIssues([])
        } catch {
          setQuestionsGenerees([])
          setQuestionsMeta([])
        }
        setGeneratingQuestions(false)
        setStep('questions')
      }
    } else if (step === 'questions') {
      setError(null)
      // En lecture seule (objectif inchange), pas de validation coherence
      if (questionsReadOnly) {
        setStep('bien-etre')
        return
      }

      // ── Flow par chapitres : navigation entre categories ───────────────────
      // Calcul de la liste ordonnee unique de categories (ordre d'apparition).
      // On dedupe par KEY canonique (categoryStyle), pas par raw string : sinon
      // `competences` + `experience` apparaissent comme 2 buckets distincts
      // alors qu'ils ont le meme libelle visuel.
      const orderedCats: string[] = []
      const seenCats = new Set<string>()
      for (const meta of questionsMeta) {
        const k = catKey(meta?.category)
        if (!seenCats.has(k)) { seenCats.add(k); orderedCats.push(k) }
      }

      // Si on a un flow multi-categories ET qu'on n'est PAS sur la derniere
      // → simple navigation interne (pas de validation coherence encore).
      if (orderedCats.length > 1 && currentCategoryIdx < orderedCats.length - 1) {
        // Verifier qu'au moins une question de la categorie courante a une reponse
        const currentKey = orderedCats[currentCategoryIdx]
        const idxInCat = questionsMeta
          .map((m, i) => ({ i, k: catKey(m?.category) }))
          .filter(x => x.k === currentKey)
          .map(x => x.i)
        const filledInCat = idxInCat.filter(i => (reponses[i] ?? '').trim().length > 0).length
        if (filledInCat === 0) {
          setError(t('profil.repondre_au_moins_une_cat') ||
            'Repondez a au moins une question de cette categorie pour continuer.')
          return
        }
        setCurrentCategoryIdx(currentCategoryIdx + 1)
        // Scroll en haut de la card
        setTimeout(() => {
          window.scrollTo({ top: 0, behavior: 'smooth' })
        }, 50)
        return
      }

      // Derniere categorie (ou pas de meta = pas de flow par chapitres) :
      // validation coherence + transition vers bien-etre.
      const reponses_array = questionsGenerees.map((_, i) => (reponses[i] ?? '').trim())
      const filled = reponses_array.filter(r => r.length > 0).length
      if (filled === 0) {
        setError(t('profil.repondre_au_moins_une') || 'Repondez au moins a une question pour continuer.')
        return
      }
      // Validation coherence par IA
      setValidatingCoherence(true)
      setCoherenceIssues([])
      try {
        const result = await api.validerCoherence(objDesc.trim(), questionsGenerees, reponses_array)
        if (!result.coherent && result.issues.length > 0) {
          setCoherenceIssues(result.issues)
          setError(
            t('profil.coherence_a_corriger') ||
            `${result.issues.length} reponse(s) a corriger : verifiez les questions surlignees en rouge ci-dessous.`,
          )
          setValidatingCoherence(false)
          // Si on est en mode multi-categories, retourner sur la categorie de
          // la premiere question problematique.
          if (orderedCats.length > 1) {
            const firstIssueIdx = result.issues[0].question_idx
            const issueKey = catKey(questionsMeta[firstIssueIdx]?.category)
            const targetCatIdx = orderedCats.indexOf(issueKey)
            if (targetCatIdx >= 0) setCurrentCategoryIdx(targetCatIdx)
          }
          // Scroll vers la premiere question problematique
          setTimeout(() => {
            const firstIssueIdx = result.issues[0].question_idx
            const el = document.getElementById(`question-${firstIssueIdx}`)
            el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
          }, 200)
          return
        }
        // Tout coherent → on passe
        setStep('bien-etre')
      } catch {
        // En cas d'erreur reseau/IA : on laisse passer (mode degrade)
        setStep('bien-etre')
      } finally {
        setValidatingCoherence(false)
      }
    }
  }

  const goPrev = () => {
    setError(null)
    if (step === 'questions') {
      // Si on est dans un flow par chapitres et pas sur le 1er, reculer d'une categorie.
      // Sinon, retour a l'etape identite.
      const orderedCats: string[] = []
      const seenCats = new Set<string>()
      for (const meta of questionsMeta) {
        const k = catKey(meta?.category)
        if (!seenCats.has(k)) { seenCats.add(k); orderedCats.push(k) }
      }
      if (orderedCats.length > 1 && currentCategoryIdx > 0) {
        setCurrentCategoryIdx(currentCategoryIdx - 1)
        setTimeout(() => window.scrollTo({ top: 0, behavior: 'smooth' }), 50)
        return
      }
      setStep('identite')
    }
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

        {/* En-tête — Linear style hero */}
        <div style={{ marginBottom: 'var(--space-8)' }}>
          <h1 style={{
            fontSize: 'var(--fs-3xl)',
            fontWeight: 700,
            letterSpacing: 'var(--tracking-tight)',
            color: 'var(--text-primary)',
            marginBottom: 'var(--space-2)',
            lineHeight: 1.15,
          }}>
            {profil ? t('profil.modifier_profil') : t('profil.creer_profil')}
          </h1>
          <p style={{
            color: 'var(--text-muted)',
            fontSize: 'var(--fs-md)',
            lineHeight: 1.55,
            maxWidth: 600,
          }}>
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
                    width: 28, height: 28,
                    borderRadius: '50%',
                    background: done
                      ? 'var(--success)'
                      : active
                        ? 'var(--sylea-gradient)'
                        : 'var(--bg-elevated)',
                    border: `1px solid ${done ? 'var(--success)' : active ? 'transparent' : 'var(--border)'}`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 'var(--fs-xs)', fontWeight: 600,
                    color: done || active ? 'white' : 'var(--text-muted)',
                    transition: 'all var(--duration-base) var(--ease-out)',
                    flexShrink: 0,
                    boxShadow: active ? 'var(--shadow-blue-glow)' : 'none',
                  }}>
                    {done ? '✓' : s.n}
                  </div>
                  <span style={{
                    fontSize: 'var(--fs-xs)',
                    fontWeight: active ? 600 : 500,
                    color: active ? 'var(--text-primary)' : 'var(--text-muted)',
                    letterSpacing: 'var(--tracking-wide)',
                    whiteSpace: 'nowrap',
                    textTransform: 'uppercase',
                    transition: 'color var(--duration-fast) var(--ease-out)',
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

        {/* ═══ ÉTAPE 2 — QUESTIONS PERSONNALISÉES (UX par chapitres) ═════════ */}
        {step === 'questions' && (() => {
          // Calcul progression GLOBALE : nombre de reponses non vides / total
          const totalQuestions = questionsGenerees.length
          const answeredAll = questionsGenerees.filter((_, i) => (reponses[i] ?? '').trim().length > 0).length
          const progressPctAll = totalQuestions > 0 ? Math.round((answeredAll / totalQuestions) * 100) : 0
          const allAnswered = totalQuestions > 0 && answeredAll === totalQuestions
          const issuesByIdx = new Map(coherenceIssues.map(iss => [iss.question_idx, iss]))

          // Calcul des categories ordonnees (par KEY canonique pour deduper).
          const orderedCats: string[] = []
          const seenCats = new Set<string>()
          for (const meta of questionsMeta) {
            const k = catKey(meta?.category)
            if (!seenCats.has(k)) { seenCats.add(k); orderedCats.push(k) }
          }

          // Mode flow par chapitres (multi-categories ET pas readonly).
          // En readonly OU sans meta : tout afficher d'un coup.
          const useChapters = !questionsReadOnly && orderedCats.length > 1
          const currentKey = useChapters ? orderedCats[currentCategoryIdx] : null
          const isLastCat = useChapters && currentCategoryIdx === orderedCats.length - 1

          // Indices des questions a afficher dans le rendu courant
          const visibleIndices = useChapters
            ? questionsMeta
                .map((m, i) => ({ i, k: catKey(m?.category) }))
                .filter(x => x.k === currentKey)
                .map(x => x.i)
            : questionsGenerees.map((_, i) => i)

          // Progression par categorie (pour la barre + sentiment de progression)
          const answeredInCat = visibleIndices.filter(i => (reponses[i] ?? '').trim().length > 0).length
          const totalInCat = visibleIndices.length
          const progressPctCat = totalInCat > 0 ? Math.round((answeredInCat / totalInCat) * 100) : 0
          const catFullyAnswered = totalInCat > 0 && answeredInCat === totalInCat

          // Une categorie est "completee" quand au moins 1 reponse non vide
          const catCompleted = (key: string): boolean => {
            const idxs = questionsMeta
              .map((m, i) => ({ i, k: catKey(m?.category) }))
              .filter(x => x.k === key)
              .map(x => x.i)
            return idxs.some(i => (reponses[i] ?? '').trim().length > 0)
          }

          return (
          <div className="card animate-fade-in-scale">
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

              {/* Entête + chapitre courant + progression */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem', gap: '1rem', flexWrap: 'wrap' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--accent-violet-light)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.5rem' }}>
                      ◈ {useChapters && currentKey ? categoryStyle(currentKey).label : t('profil.questions_objectif')}
                    </p>
                    <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', lineHeight: '1.5', margin: 0 }}>
                      {questionsReadOnly
                        ? t('profil.questions_readonly')
                        : useChapters
                          ? (t('profil.chapitre_desc') || `Chapitre ${currentCategoryIdx + 1} sur ${orderedCats.length} — répondez aux questions de cette section avant de passer à la suivante.`)
                          : t('profil.questions_desc')}
                    </p>
                  </div>
                  {!questionsReadOnly && totalQuestions > 0 && (
                    <div style={{
                      display: 'flex', flexDirection: 'column', alignItems: 'flex-end',
                      gap: '0.25rem', flexShrink: 0,
                    }}>
                      <span style={{
                        fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em',
                      }}>
                        {t('profil.progression') || 'Progression'}
                      </span>
                      <span style={{
                        fontFamily: 'var(--font-mono)', fontSize: '1.25rem', fontWeight: 700,
                        color: allAnswered ? 'var(--success)' : 'var(--accent-violet-light)',
                        transition: 'color 0.3s',
                      }}>
                        {answeredAll}<span style={{ opacity: 0.4, fontSize: '0.95rem' }}>/{totalQuestions}</span>
                      </span>
                    </div>
                  )}
                </div>

                {questionsReadOnly && (
                  <div style={{
                    display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
                    padding: '0.3rem 0.75rem', borderRadius: '999px', fontSize: '0.7rem', fontWeight: 600,
                    background: 'rgba(59,130,246,0.1)', color: '#60a5fa', border: '1px solid rgba(59,130,246,0.2)',
                    marginTop: '0.5rem',
                  }}>
                    <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}><rect x={3} y={11} width={18} height={11} rx={2}/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                    {t('profil.lecture_seule')}
                  </div>
                )}

                {/* Stepper de chapitres (categories) */}
                {useChapters && (
                  <div style={{
                    marginTop: '0.875rem',
                    display: 'flex', alignItems: 'center', gap: '0.375rem',
                    flexWrap: 'wrap',
                  }}>
                    {orderedCats.map((key, idx) => {
                      const s = categoryStyle(key)
                      const isActive = idx === currentCategoryIdx
                      const isDone = idx < currentCategoryIdx && catCompleted(key)
                      const isPast = idx < currentCategoryIdx
                      const clickable = isPast || isActive
                      return (
                        <button
                          key={key}
                          type="button"
                          onClick={() => {
                            if (!clickable) return
                            setError(null)
                            setCurrentCategoryIdx(idx)
                          }}
                          disabled={!clickable}
                          style={{
                            display: 'inline-flex', alignItems: 'center', gap: '0.35rem',
                            padding: '0.35rem 0.7rem', borderRadius: '999px',
                            fontSize: '0.7rem', fontWeight: 600,
                            background: isActive ? s.bg : 'transparent',
                            color: isActive ? s.color : isDone ? '#4ade80' : 'var(--text-muted)',
                            border: `1px solid ${isActive ? s.border : isDone ? 'rgba(34,197,94,0.3)' : 'var(--border)'}`,
                            cursor: clickable ? 'pointer' : 'not-allowed',
                            opacity: clickable ? 1 : 0.55,
                            textTransform: 'uppercase', letterSpacing: '0.04em',
                            transition: 'all 0.2s',
                          }}
                        >
                          {isDone ? (
                            <svg width={11} height={11} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}>
                              <polyline points="20 6 9 17 4 12"/>
                            </svg>
                          ) : (
                            <span style={{
                              width: 16, height: 16, borderRadius: '50%',
                              background: isActive ? s.color : 'transparent',
                              border: `1px solid ${isActive ? s.color : 'var(--border)'}`,
                              color: isActive ? '#000' : 'var(--text-muted)',
                              fontSize: '0.6rem', fontWeight: 700,
                              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                            }}>
                              {idx + 1}
                            </span>
                          )}
                          {s.label}
                        </button>
                      )
                    })}
                  </div>
                )}

                {/* Barre de progression (categorie courante en chapitres, sinon globale) */}
                {!questionsReadOnly && totalQuestions > 0 && (
                  <div style={{
                    marginTop: '0.875rem',
                    width: '100%', height: '8px',
                    background: 'rgba(148,163,184,0.15)',
                    borderRadius: '999px',
                    overflow: 'hidden',
                    position: 'relative',
                  }}>
                    <div style={{
                      width: `${useChapters ? progressPctCat : progressPctAll}%`, height: '100%',
                      background: (useChapters ? catFullyAnswered : allAnswered)
                        ? 'linear-gradient(90deg, var(--success), #34d399)'
                        : 'linear-gradient(90deg, var(--accent-violet), var(--accent-violet-light))',
                      borderRadius: '999px',
                      transition: 'width 0.5s cubic-bezier(0.4, 0, 0.2, 1), background 0.3s',
                      boxShadow: (useChapters ? catFullyAnswered : allAnswered) ? '0 0 12px rgba(34,197,94,0.5)' : 'none',
                    }} />
                  </div>
                )}
              </div>

              {/* Banniere coherence */}
              {coherenceIssues.length > 0 && (
                <div style={{
                  padding: '0.875rem 1rem',
                  background: 'rgba(239,68,68,0.08)',
                  border: '1px solid rgba(239,68,68,0.3)',
                  borderRadius: '0.625rem',
                  display: 'flex', alignItems: 'flex-start', gap: '0.625rem',
                }}>
                  <span style={{ fontSize: '1.1rem', flexShrink: 0 }}>⚠</span>
                  <div style={{ flex: 1 }}>
                    <p style={{ fontSize: '0.85rem', fontWeight: 600, color: '#f87171', margin: 0, marginBottom: '0.25rem' }}>
                      {t('profil.coherence_titre') || `${coherenceIssues.length} reponse(s) a corriger`}
                    </p>
                    <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.5 }}>
                      {t('profil.coherence_desc') || 'L\'IA a detecte des incoherences entre votre objectif et certaines reponses. Corrigez les questions surlignees pour continuer.'}
                    </p>
                  </div>
                </div>
              )}

              {totalQuestions === 0 ? (
                <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', fontStyle: 'italic', textAlign: 'center', padding: '1.5rem 0' }}>
                  {t('profil.aucune_question')}
                </p>
              ) : (
                visibleIndices.map((i, displayPos) => {
                  const q = questionsGenerees[i]
                  void displayPos
                  const isListening = activeVoiceIdx === i
                  const meta = questionsMeta[i]
                  const filled = (reponses[i] ?? '').trim().length > 0
                  const issue = issuesByIdx.get(i)
                  const hasIssue = Boolean(issue)
                  const expanded = expandedHints.has(i)

                  const cardBorder = hasIssue
                    ? '1px solid rgba(239,68,68,0.45)'
                    : filled
                      ? '1px solid rgba(34,197,94,0.3)'
                      : '1px solid var(--border)'
                  const cardBg = hasIssue
                    ? 'rgba(239,68,68,0.04)'
                    : filled
                      ? 'rgba(34,197,94,0.03)'
                      : 'transparent'

                  return (
                    <div
                      id={`question-${i}`}
                      key={i}
                      style={{
                        padding: '0.875rem 1rem',
                        border: cardBorder,
                        background: cardBg,
                        borderRadius: '0.625rem',
                        transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                      }}
                    >
                      {/* En-tete : badge categorie + numero + checkmark */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem', flexWrap: 'wrap' }}>
                        <span style={{
                          color: 'var(--accent-gold)', fontFamily: 'var(--font-mono)',
                          fontSize: '0.7rem', flexShrink: 0,
                        }}>
                          {(i + 1).toString().padStart(2, '0')}
                        </span>
                        {meta && meta.category && (() => {
                          const s = categoryStyle(meta.category)
                          return (
                            <span style={{
                              display: 'inline-flex', alignItems: 'center',
                              padding: '0.2rem 0.55rem', borderRadius: '999px',
                              fontSize: '0.65rem', fontWeight: 600,
                              background: s.bg, color: s.color, border: `1px solid ${s.border}`,
                              textTransform: 'uppercase', letterSpacing: '0.04em',
                            }}>
                              {s.label}
                            </span>
                          )
                        })()}
                        {filled && !hasIssue && (
                          <span
                            className="animate-fade-in-scale"
                            style={{
                              display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
                              padding: '0.2rem 0.5rem', borderRadius: '999px',
                              fontSize: '0.65rem', fontWeight: 600,
                              background: 'rgba(34,197,94,0.15)', color: '#4ade80',
                              border: '1px solid rgba(34,197,94,0.3)',
                            }}
                          >
                            <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}>
                              <polyline points="20 6 9 17 4 12"/>
                            </svg>
                            OK
                          </span>
                        )}
                        {hasIssue && (
                          <span style={{
                            display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
                            padding: '0.2rem 0.5rem', borderRadius: '999px',
                            fontSize: '0.65rem', fontWeight: 600,
                            background: 'rgba(239,68,68,0.15)', color: '#f87171',
                            border: '1px solid rgba(239,68,68,0.3)',
                          }}>
                            ⚠ A corriger
                          </span>
                        )}
                      </div>

                      {/* Question */}
                      <p style={{
                        color: 'var(--text-secondary)',
                        fontSize: '0.9rem',
                        lineHeight: 1.5,
                        margin: 0,
                        marginBottom: meta?.why_it_matters ? '0.375rem' : '0.625rem',
                        fontWeight: 500,
                      }}>
                        {q}
                      </p>

                      {/* Pourquoi cette question (expansible) */}
                      {meta?.why_it_matters && !questionsReadOnly && (
                        <div style={{ marginBottom: '0.625rem' }}>
                          <button
                            type="button"
                            onClick={() => setExpandedHints(prev => {
                              const next = new Set(prev)
                              if (next.has(i)) next.delete(i)
                              else next.add(i)
                              return next
                            })}
                            style={{
                              background: 'transparent', border: 'none',
                              padding: 0, color: 'var(--accent-violet-light)',
                              fontSize: '0.72rem', cursor: 'pointer',
                              display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
                              fontWeight: 500,
                              opacity: 0.85,
                              transition: 'opacity 0.15s',
                            }}
                            onMouseEnter={e => (e.currentTarget.style.opacity = '1')}
                            onMouseLeave={e => (e.currentTarget.style.opacity = '0.85')}
                          >
                            <svg
                              width={11} height={11} viewBox="0 0 24 24"
                              fill="none" stroke="currentColor" strokeWidth={2}
                              style={{ transition: 'transform 0.2s', transform: expanded ? 'rotate(90deg)' : 'rotate(0)' }}
                            >
                              <polyline points="9 18 15 12 9 6"/>
                            </svg>
                            {t('profil.pourquoi_question') || 'Pourquoi cette question ?'}
                          </button>
                          {expanded && (
                            <div className="animate-fade-in" style={{
                              marginTop: '0.4rem',
                              padding: '0.625rem 0.75rem',
                              background: 'rgba(124,58,237,0.06)',
                              border: '1px solid rgba(124,58,237,0.2)',
                              borderRadius: '0.5rem',
                              fontSize: '0.78rem', color: 'var(--text-muted)',
                              lineHeight: 1.55,
                            }}>
                              {meta.why_it_matters}
                              {meta.expected_format && (
                                <p style={{
                                  margin: 0, marginTop: '0.4rem',
                                  fontStyle: 'italic', opacity: 0.85,
                                  fontSize: '0.74rem',
                                }}>
                                  💡 <strong>{t('profil.exemple_format') || 'Exemple de format'}:</strong> {meta.expected_format}
                                </p>
                              )}
                            </div>
                          )}
                        </div>
                      )}

                      {/* Champ reponse */}
                      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start' }}>
                        <textarea
                          className="input"
                          rows={2}
                          value={reponses[i] ?? ''}
                          onChange={e => {
                            if (questionsReadOnly) return
                            setReponses(prev => ({ ...prev, [i]: e.target.value }))
                            // Reset issue pour cette question des qu'on edite
                            if (hasIssue) {
                              setCoherenceIssues(prev => prev.filter(iss => iss.question_idx !== i))
                            }
                          }}
                          readOnly={questionsReadOnly}
                          placeholder={meta?.expected_format && !questionsReadOnly
                            ? meta.expected_format
                            : t('profil.votre_reponse')}
                          style={{
                            flex: 1, resize: questionsReadOnly ? 'none' : 'vertical',
                            opacity: questionsReadOnly ? 0.7 : 1,
                            cursor: questionsReadOnly ? 'default' : undefined,
                            background: questionsReadOnly ? 'rgba(255,255,255,0.02)' : undefined,
                            borderColor: hasIssue ? 'rgba(239,68,68,0.4)' : undefined,
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
                            width: '36px', height: '36px',
                            borderRadius: '8px',
                            border: `1px solid ${isListening ? 'var(--accent-violet)' : 'var(--border)'}`,
                            background: isListening ? 'rgba(124,58,237,0.2)' : 'var(--bg-elevated)',
                            color: isListening ? 'var(--accent-violet-light)' : 'var(--text-muted)',
                            cursor: activeVoiceIdx !== -1 && !isListening ? 'not-allowed' : 'pointer',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
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
                          display: 'flex', alignItems: 'center', gap: '0.375rem',
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

                      {/* Issue de coherence : message + suggestion IA */}
                      {hasIssue && issue && (
                        <div className="animate-fade-in" style={{
                          marginTop: '0.625rem',
                          padding: '0.625rem 0.75rem',
                          background: 'rgba(239,68,68,0.08)',
                          border: '1px solid rgba(239,68,68,0.25)',
                          borderRadius: '0.5rem',
                          fontSize: '0.78rem', lineHeight: 1.55,
                        }}>
                          <p style={{ margin: 0, color: '#f87171', fontWeight: 600 }}>
                            ⚠ {issue.issue}
                          </p>
                          {issue.suggestion && (
                            <p style={{ margin: 0, marginTop: '0.3rem', color: 'var(--text-muted)' }}>
                              💡 <strong>{t('profil.suggestion') || 'Suggestion'}:</strong> {issue.suggestion}
                            </p>
                          )}
                        </div>
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

              {error && <p style={{ color: 'var(--danger)', fontSize: '0.875rem', margin: 0 }}>⚠ {error}</p>}

              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '0.5rem' }}>
                <button className="btn btn-outline" onClick={goPrev} disabled={validatingCoherence}>{t('common.precedent')}</button>
                <button className="btn btn-primary" onClick={goNext} disabled={validatingCoherence}>
                  {validatingCoherence ? (
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
                      <span style={{
                        width: '14px', height: '14px', borderRadius: '50%',
                        border: '2px solid rgba(255,255,255,0.3)', borderTop: '2px solid white',
                        animation: 'spin 0.7s linear infinite', display: 'inline-block',
                      }} />
                      {t('profil.verification_coherence') || 'Verification...'}
                    </span>
                  ) : useChapters && !isLastCat
                      ? (t('profil.chapitre_suivant') || `Chapitre suivant : ${categoryStyle(orderedCats[currentCategoryIdx + 1]).label} →`)
                      : useChapters && isLastCat
                        ? (t('profil.terminer_questions') || 'Continuer →')
                        : t('common.suivant')}
                </button>
              </div>
            </div>
          </div>
          )
        })()}

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
