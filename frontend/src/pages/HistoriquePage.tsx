// Page Historique — Liste des décisions passées

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../store/useStore'
import { api } from '../api/client'
import type { Decision } from '../types'

export function HistoriquePage() {
  const navigate = useNavigate()
  const profil = useStore((s) => s.profil)
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!profil) {
      navigate('/profil')
      return
    }
    api.getHistorique(30)
      .then(setDecisions)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [profil, navigate])

  const formatDate = (iso: string) => {
    const d = new Date(iso)
    return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' })
  }

  const formatImpact = (impact: number | null) => {
    if (impact === null) return '—'
    const sign = impact >= 0 ? '+' : ''
    return `${sign}${impact.toFixed(3)}%`
  }

  return (
    <div className="page animate-fade-in">
      <div className="container page-content">

        {/* En-tête */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '2rem' }}>
          <div>
            <h2 style={{ color: 'var(--accent-silver)', marginBottom: '0.375rem' }}>
              Historique des décisions
            </h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
              {decisions.length > 0
                ? `${decisions.length} décision${decisions.length > 1 ? 's' : ''} enregistrée${decisions.length > 1 ? 's' : ''}`
                : 'Aucune décision encore enregistrée'}
            </p>
          </div>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => navigate('/dilemme')}
          >
            + Nouveau dilemme
          </button>
        </div>

        {/* Chargement */}
        {loading && (
          <div className="loading-center">
            <div className="spinner" />
            <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>Chargement…</p>
          </div>
        )}

        {/* Erreur */}
        {error && (
          <div style={{ color: 'var(--danger)', padding: '1rem', background: 'var(--danger-dim)', borderRadius: 'var(--radius-md)' }}>
            ⚠ {error}
          </div>
        )}

        {/* Liste vide */}
        {!loading && !error && decisions.length === 0 && (
          <div
            className="card"
            style={{ textAlign: 'center', padding: '3rem', maxWidth: '480px', margin: '0 auto' }}
          >
            <div style={{ fontSize: '2.5rem', marginBottom: '1rem', opacity: 0.4 }}>◈</div>
            <h3 style={{ color: 'var(--text-secondary)', marginBottom: '0.5rem', fontSize: '1rem' }}>
              Aucune décision pour l'instant
            </h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', marginBottom: '1.5rem' }}>
              Soumettez votre premier dilemme pour que Syléa.AI vous aide à décider.
            </p>
            <button className="btn btn-primary btn-sm" onClick={() => navigate('/dilemme')}>
              Analyser un choix
            </button>
          </div>
        )}

        {/* Tableau */}
        {!loading && decisions.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {decisions.map((d) => {
              const impactPos = (d.impact_net ?? 0) >= 0
              return (
                <div
                  key={d.id}
                  className="card animate-fade-in"
                  style={{
                    borderLeft: `3px solid ${impactPos ? 'var(--success)' : 'var(--danger)'}`,
                    padding: '1.125rem 1.375rem',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>

                    {/* Contenu principal */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      {/* Question */}
                      <p
                        style={{
                          fontSize: '0.925rem',
                          fontWeight: 600,
                          color: 'var(--text-primary)',
                          marginBottom: '0.375rem',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {d.question}
                      </p>

                      {/* Option choisie */}
                      {d.option_choisie_description && (
                        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                          <span style={{ color: 'var(--text-muted)' }}>Choix : </span>
                          {d.option_choisie_description}
                        </p>
                      )}

                      {/* Métadonnées */}
                      <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                          {formatDate(d.cree_le)}
                        </span>
                        {d.probabilite_avant !== undefined && d.probabilite_apres !== null && (
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                            {d.probabilite_avant.toFixed(2)}% → {d.probabilite_apres?.toFixed(2)}%
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Badge impact */}
                    <div style={{ flexShrink: 0 }}>
                      <span
                        className={`badge ${impactPos ? 'badge-success' : 'badge-danger'}`}
                        style={{ fontSize: '0.875rem', fontFamily: 'var(--font-mono)', padding: '0.35rem 0.75rem' }}
                      >
                        {formatImpact(d.impact_net)}
                      </span>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* Statistiques sommaires */}
        {!loading && decisions.length > 0 && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
              gap: '1rem',
              marginTop: '2rem',
            }}
          >
            <StatCard
              label="Décisions prises"
              value={decisions.length.toString()}
              color="var(--accent-violet-light)"
            />
            <StatCard
              label="Impact total"
              value={formatImpact(decisions.reduce((sum, d) => sum + (d.impact_net ?? 0), 0))}
              color={decisions.reduce((sum, d) => sum + (d.impact_net ?? 0), 0) >= 0 ? 'var(--success)' : 'var(--danger)'}
            />
            <StatCard
              label="Décisions positives"
              value={`${decisions.filter((d) => (d.impact_net ?? 0) > 0).length}`}
              color="var(--success)"
            />
          </div>
        )}

      </div>
    </div>
  )
}

function StatCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div
      className="card"
      style={{
        textAlign: 'center',
        padding: '1.25rem',
        border: '1px solid var(--border)',
      }}
    >
      <p style={{ fontSize: '1.5rem', fontWeight: 700, color, marginBottom: '0.375rem', fontFamily: 'var(--font-mono)' }}>
        {value}
      </p>
      <p style={{ fontSize: '0.775rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        {label}
      </p>
    </div>
  )
}
