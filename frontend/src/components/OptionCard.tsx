// Carte d'analyse d'une option de dilemme
// L'impact est affiché en durée estimée (ex. "+45j", "-1a 3m", "+12h")

import type { AnalyseOption } from '../types'
import { deltaFromImpact } from '../utils/duration'

interface OptionCardProps {
  lettre:        string
  option:        AnalyseOption
  recommandee?:  boolean
  selected?:     boolean
  onSelect?:     () => void
  /** Probabilité actuelle du profil — nécessaire pour calculer le delta de durée */
  probActuelle?: number
}

export function OptionCard({
  lettre,
  option,
  recommandee,
  selected,
  onSelect,
  probActuelle,
}: OptionCardProps) {
  const impactPos = option.impact_probabilite >= 0

  // Affichage : durée si probActuelle fournie, sinon % en fallback
  const impactLabel =
    probActuelle !== undefined
      ? deltaFromImpact(probActuelle, option.impact_probabilite)
      : `${impactPos ? '+' : ''}${option.impact_probabilite.toFixed(3)}%`

  return (
    <div
      className={[
        'card',
        selected    ? 'card-selected' : '',
        recommandee ? 'card-gold'     : '',
        onSelect    ? 'card-clickable': '',
      ].filter(Boolean).join(' ')}
      onClick={onSelect}
      style={{
        cursor:    onSelect ? 'pointer' : 'default',
        border:    selected    ? '2px solid var(--accent-violet)'
                  : recommandee ? '1px solid var(--border-gold)'
                  : '1px solid var(--border)',
        transition: 'all 0.2s',
        transform:  selected ? 'scale(1.01)' : 'scale(1)',
        boxShadow:  selected    ? '0 0 24px rgba(124,58,237,0.35)'
                   : recommandee ? 'var(--shadow-gold)'
                   : 'var(--shadow-card)',
        flex:      1,
        minWidth:  0,
      }}
    >
      {/* ── En-tête ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {/* Pastille lettre */}
          <div
            style={{
              width: '2rem', height: '2rem',
              borderRadius: '50%',
              background: recommandee
                ? 'linear-gradient(135deg, var(--accent-gold), #b8860b)'
                : 'linear-gradient(135deg, var(--accent-violet), #5b21b6)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontWeight: 700, fontSize: '0.9rem',
              color: recommandee ? '#0d0d14' : 'white',
              flexShrink: 0,
            }}
          >
            {lettre}
          </div>
          <span style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)' }}>
            {option.description}
          </span>
        </div>

        {/* Badges : recommandé + impact durée */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.25rem' }}>
          {recommandee && (
            <span className="badge badge-gold" style={{ fontSize: '0.65rem' }}>★ Recommandé</span>
          )}
          {/* Badge impact en durée */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '2px' }}>
            <span
              className={`badge ${impactPos ? 'badge-success' : 'badge-danger'}`}
              style={{
                fontSize: '0.85rem',
                fontFamily: 'var(--font-mono)',
                letterSpacing: '0.04em',
                fontWeight: 700,
              }}
            >
              {impactLabel}
            </span>
            <span style={{ fontSize: '0.66rem', color: 'var(--text-muted)', letterSpacing: '0.04em' }}>
              {impactPos ? 'temps gagné' : 'temps perdu'}
            </span>
          </div>
        </div>
      </div>

      {/* ── Résumé ── */}
      <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '1rem', fontStyle: 'italic' }}>
        {option.resume}
      </p>

      {/* ── Pour ── */}
      {option.pros.length > 0 && (
        <div style={{ marginBottom: '0.75rem' }}>
          <p style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--success)', marginBottom: '0.375rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            ◆ Pour
          </p>
          <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
            {option.pros.map((pro, i) => (
              <li key={i} style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', paddingLeft: '0.75rem', borderLeft: '2px solid var(--success-dim)' }}>
                {pro}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Contre ── */}
      {option.cons.length > 0 && (
        <div>
          <p style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--danger)', marginBottom: '0.375rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            ◇ Contre
          </p>
          <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
            {option.cons.map((con, i) => (
              <li key={i} style={{ fontSize: '0.875rem', color: 'var(--text-muted)', paddingLeft: '0.75rem', borderLeft: '2px solid var(--danger-dim)' }}>
                {con}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
