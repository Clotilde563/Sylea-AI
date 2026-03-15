// Page Dilemme — Analyse IA d'un choix de vie (N options)

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { OptionCard } from '../components/OptionCard'
import { useStore } from '../store/useStore'
import { api } from '../api/client'
import type { AnalyseDilemme, Decision } from '../types'

type Phase = 'form' | 'loading' | 'result' | 'done'

// Regex pour detecter les indicateurs temporels dans la question
const TEMPORAL_PATTERN = /\b(aujourd'hui|ce soir|ce matin|cet apr[eè]s[- ]midi|demain|cette semaine|ce week[- ]?end|ce mois|cette ann[eé]e|dans (une? |quelques |(\d+) )?(heure|jour|semaine|mois|an)|d'ici|avant|apr[eè]s|prochaine?|bient[oô]t|tout [àa] l'heure|en ce moment|maintenant|derni[eè]re?|depuis|il y a|la semaine|le mois|l'ann[eé]e)\b/i

const MAX_OPTIONS = 5
const MIN_OPTIONS = 2

// Couleurs pour les pastilles d'options
const OPTION_COLORS = [
  'linear-gradient(135deg, var(--accent-violet), #5b21b6)',
  'linear-gradient(135deg, #d4a017, #b8860b)',
  'linear-gradient(135deg, #059669, #047857)',
  'linear-gradient(135deg, #dc2626, #b91c1c)',
  'linear-gradient(135deg, #2563eb, #1d4ed8)',
]
const OPTION_TEXT_COLORS = ['white', '#0d0d14', 'white', 'white', 'white']

export function DilemmePage() {
  const navigate = useNavigate()
  const { profil, analyse, setAnalyse, setProfil } = useStore()

  const [phase, setPhase] = useState<Phase>(analyse ? 'result' : 'form')
  const [question, setQuestion] = useState('')
  const [options, setOptions] = useState<string[]>(['', ''])
  const [choixSelectionne, setChoixSelectionne] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [sousObjectifImpacte, setSousObjectifImpacte] = useState<string | null>(null)

  if (!profil) {
    return (
      <div className="page">
        <div className="container page-content" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '1rem' }}>
          <p style={{ color: 'var(--text-muted)' }}>Vous devez créer un profil pour analyser un dilemme.</p>
          <button className="btn btn-primary" onClick={() => navigate('/profil')}>
            Créer mon profil
          </button>
        </div>
      </div>
    )
  }

  const handleAnalyser = async () => {
    if (!question.trim() || options.some(o => !o.trim())) {
      setError('Veuillez remplir tous les champs.')
      return
    }
    if (!TEMPORAL_PATTERN.test(question)) {
      setError('Veuillez préciser une échelle temporelle dans votre question (ex: "aujourd\'hui", "ce mois", "cette année", "dans 6 mois"...). Cela permet à l\'IA d\'affiner son analyse d\'impact.')
      return
    }
    setError(null)
    setPhase('loading')
    try {
      const result = await api.analyserDilemme({
        question: question.trim(),
        options: options.map(o => o.trim()),
      })
      setAnalyse(result)
      setPhase('result')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erreur lors de l\'analyse')
      setPhase('form')
    }
  }

  const handleChoisir = async () => {
    if (!analyse || !choixSelectionne) return
    setSubmitting(true)
    setError(null)
    try {
      const choixResult = await api.choisirOption({
        question: analyse.question,
        options: analyse.options,
        choix: choixSelectionne,
      })
      if (choixResult?.sous_objectif_impacte) {
        setSousObjectifImpacte(choixResult.sous_objectif_impacte)
      }
      // Recharger le profil pour la probabilité mise à jour
      const updated = await api.getProfil()
      setProfil(updated)
      setAnalyse(null)
      setPhase('done')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erreur lors de l\'enregistrement')
    } finally {
      setSubmitting(false)
    }
  }

  const handleReset = () => {
    setQuestion('')
    setOptions(['', ''])
    setChoixSelectionne(null)
    setAnalyse(null)
    setError(null)
    setSousObjectifImpacte(null)
    setPhase('form')
  }

  const addOption = () => {
    if (options.length < MAX_OPTIONS) {
      setOptions([...options, ''])
    }
  }

  const removeOption = (index: number) => {
    if (options.length > MIN_OPTIONS) {
      setOptions(options.filter((_, i) => i !== index))
    }
  }

  const updateOption = (index: number, value: string) => {
    const next = [...options]
    next[index] = value
    setOptions(next)
  }

  return (
    <div className="page animate-fade-in">
      <div className="container page-content">

        {/* En-tête */}
        <div style={{ marginBottom: '2rem' }}>
          <h2 style={{ color: 'var(--accent-silver)', marginBottom: '0.375rem' }}>
            Analyser un choix
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            Décrivez votre dilemme — Syléa.AI analyse vos options et leur impact sur votre probabilité de réussite.
          </p>
        </div>

        {/* Phase : Formulaire */}
        {phase === 'form' && (
          <div className="card animate-fade-in-scale" style={{ maxWidth: '680px', margin: '0 auto' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              <div className="input-group">
                <label className="input-label">
                  Votre question <span style={{ color: 'var(--accent-gold)' }}>*</span>
                </label>
                <textarea
                  className="input"
                  rows={3}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="Ex: Dois-je quitter mon CDI cette année pour lancer ma startup ?"
                />
                <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.375rem' }}>
                  Incluez une indication temporelle (ex: "cette année", "ce mois", "demain"...)
                </p>
              </div>

              {/* Options dynamiques */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {options.map((opt, i) => {
                  const lettre = String.fromCharCode(65 + i)
                  return (
                    <div key={i} className="input-group">
                      <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span
                          style={{
                            width: '20px',
                            height: '20px',
                            borderRadius: '50%',
                            background: OPTION_COLORS[i % OPTION_COLORS.length],
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: '0.7rem',
                            fontWeight: 700,
                            color: OPTION_TEXT_COLORS[i % OPTION_TEXT_COLORS.length],
                            flexShrink: 0,
                          }}
                        >
                          {lettre}
                        </span>
                        Option {lettre} <span style={{ color: 'var(--accent-gold)' }}>*</span>
                        {options.length > MIN_OPTIONS && (
                          <button
                            type="button"
                            onClick={() => removeOption(i)}
                            style={{
                              marginLeft: 'auto',
                              background: 'none',
                              border: '1px solid var(--border)',
                              borderRadius: '4px',
                              color: 'var(--text-muted)',
                              cursor: 'pointer',
                              fontSize: '0.75rem',
                              padding: '0.15rem 0.5rem',
                              transition: 'all 0.15s',
                            }}
                            title="Supprimer cette option"
                          >
                            ×
                          </button>
                        )}
                      </label>
                      <textarea
                        className="input"
                        rows={2}
                        value={opt}
                        onChange={(e) => updateOption(i, e.target.value)}
                        placeholder={`Ex: ${i === 0 ? 'Quitter mon CDI et lancer ma startup' : i === 1 ? 'Rester en CDI et développer en parallèle' : 'Une autre approche...'}`}
                      />
                    </div>
                  )
                })}
              </div>

              {/* Bouton ajouter option */}
              {options.length < MAX_OPTIONS && (
                <button
                  type="button"
                  onClick={addOption}
                  style={{
                    background: 'rgba(255,255,255,0.03)',
                    border: '1px dashed var(--border)',
                    borderRadius: 'var(--radius-md)',
                    padding: '0.75rem',
                    color: 'var(--text-muted)',
                    cursor: 'pointer',
                    fontSize: '0.875rem',
                    transition: 'all 0.15s',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '0.5rem',
                  }}
                >
                  <span style={{ fontSize: '1.2rem', fontWeight: 300 }}>+</span>
                  Ajouter une option ({options.length}/{MAX_OPTIONS})
                </button>
              )}

              {error && (
                <p style={{ color: 'var(--danger)', fontSize: '0.875rem' }}>⚠ {error}</p>
              )}

              <button
                className="btn btn-primary btn-full"
                onClick={handleAnalyser}
                disabled={!question || options.some(o => !o)}
              >
                ⟡ Lancer l'analyse IA
              </button>
            </div>
          </div>
        )}

        {/* Phase : Chargement */}
        {phase === 'loading' && (
          <div className="loading-center">
            <div
              style={{
                width: '64px',
                height: '64px',
                borderRadius: '50%',
                border: '3px solid var(--accent-violet-dim)',
                borderTop: '3px solid var(--accent-violet)',
                animation: 'spin 0.8s linear infinite',
              }}
            />
            <div style={{ textAlign: 'center' }}>
              <p style={{ color: 'var(--accent-silver)', fontWeight: 600, marginBottom: '0.375rem' }}>
                Syléa.AI analyse votre dilemme…
              </p>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
                Calcul de l'impact sur votre probabilité de réussite
              </p>
            </div>
          </div>
        )}

        {/* Phase : Résultat */}
        {phase === 'result' && analyse && (
          <div className="animate-fade-in">
            {/* Options */}
            <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
              {analyse.options.map((opt) => (
                <OptionCard
                  key={opt.lettre}
                  lettre={opt.lettre}
                  option={opt}
                  recommandee={analyse.option_recommandee === opt.lettre}
                  selected={choixSelectionne === opt.lettre}
                  onSelect={() => setChoixSelectionne(choixSelectionne === opt.lettre ? null : opt.lettre)}
                  probActuelle={(profil.objectif?.probabilite_calculee ?? 0) + profil.probabilite_actuelle}
                />
              ))}
            </div>

            {/* Verdict */}
            <div
              className="card"
              style={{
                background: 'linear-gradient(135deg, rgba(124,58,237,0.08), rgba(212,160,23,0.04))',
                border: '1px solid var(--accent-violet-dim)',
                marginBottom: '1.5rem',
              }}
            >
              <p style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--accent-violet-light)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.625rem' }}>
                ◈ Verdict Syléa.AI
              </p>
              <p style={{ color: 'var(--text-secondary)', lineHeight: '1.6', fontSize: '0.925rem' }}>
                {analyse.verdict}
              </p>
            </div>

            {error && (
              <p style={{ color: 'var(--danger)', fontSize: '0.875rem', marginBottom: '1rem' }}>⚠ {error}</p>
            )}

            {/* Actions */}
            <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
              <button className="btn btn-outline" onClick={handleReset}>
                ← Nouveau dilemme
              </button>
              <button
                className="btn btn-gold"
                onClick={handleChoisir}
                disabled={!choixSelectionne || submitting}
              >
                {submitting
                  ? 'Enregistrement…'
                  : choixSelectionne
                  ? `✓ Valider l'option ${choixSelectionne}`
                  : 'Sélectionnez une option'}
              </button>
            </div>
          </div>
        )}

        {/* Phase : Confirmation */}
        {phase === 'done' && (
          <div
            className="card animate-fade-in-scale"
            style={{
              maxWidth: '480px',
              margin: '0 auto',
              textAlign: 'center',
              padding: '2.5rem',
              border: '1px solid var(--success)',
              boxShadow: '0 0 32px rgba(34,197,94,0.15)',
            }}
          >
            <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>✓</div>
            <h3 style={{ color: 'var(--success)', marginBottom: '0.75rem' }}>Décision enregistrée !</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginBottom: '1rem', lineHeight: '1.5' }}>
              Votre choix a été sauvegardé et votre probabilité de réussite a été mise à jour.
            </p>
            {sousObjectifImpacte && (
              <div style={{ background: 'rgba(96,165,250,0.08)', border: '1px solid rgba(96,165,250,0.25)', borderRadius: 'var(--radius-md)', padding: '0.6rem 1rem', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ color: '#60a5fa', fontSize: '0.8rem' }}>{'↳'}</span>
                <span style={{ color: '#93c5fd', fontSize: '0.82rem' }}>Sous-objectif impacté : <strong>{sousObjectifImpacte}</strong></span>
              </div>
            )}
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center' }}>
              <button className="btn btn-outline btn-sm" onClick={handleReset}>
                Nouveau dilemme
              </button>
              <button className="btn btn-primary btn-sm" onClick={() => navigate('/')}>
                Tableau de bord
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}
