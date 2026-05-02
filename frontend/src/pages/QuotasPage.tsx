import { useState, useEffect } from 'react'
import { api } from '../api/client'

type PlanData = Awaited<ReturnType<typeof api.getPlan>>

const PLAN_COLORS: Record<string, string> = {
  free: '#6888aa',
  pro: '#1a6fd8',
  team: '#c8dff4',
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`
  return String(n)
}

function UsageBar({ label, used, limit }: { label: string; used: number; limit: number }) {
  const unlimited = limit === -1
  const pct = unlimited ? 0 : Math.min(100, (used / Math.max(1, limit)) * 100)
  const warn = pct >= 80
  const crit = pct >= 95
  const color = crit ? '#ef4444' : warn ? '#f59e0b' : '#22c55e'

  return (
    <div style={{ marginBottom: '1rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: '0.85rem' }}>
        <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{label}</span>
        <span style={{ color: 'var(--text-secondary)' }}>
          {unlimited ? `${formatNumber(used)} / ∞` : `${formatNumber(used)} / ${formatNumber(limit)}`}
          {!unlimited && <span style={{ marginLeft: 8, color }}>{pct.toFixed(0)}%</span>}
        </span>
      </div>
      <div style={{
        height: 6, background: 'rgba(255,255,255,0.06)', borderRadius: 3, overflow: 'hidden',
      }}>
        <div style={{
          width: `${unlimited ? 0 : pct}%`, height: '100%', background: color,
          transition: 'width 0.3s ease',
        }} />
      </div>
    </div>
  )
}

export default function QuotasPage() {
  const [data, setData] = useState<PlanData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [stripeConfigured, setStripeConfigured] = useState(false)
  const [checkoutLoading, setCheckoutLoading] = useState<string | null>(null)

  useEffect(() => {
    api.getPlan()
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
    api.stripeConfig()
      .then(c => setStripeConfigured(c.configured))
      .catch(() => {/* silent */})

    // Handle ?paid=1 ou ?cancelled=1 dans l'URL apres redirect Stripe
    const params = new URLSearchParams(window.location.search)
    if (params.get('paid') === '1') {
      alert('✓ Paiement confirmé ! Ton plan sera mis à jour dans quelques secondes.')
      setTimeout(() => api.getPlan().then(setData), 2000)
    }
    if (params.get('cancelled') === '1') {
      alert('Paiement annulé.')
    }
  }, [])

  const upgradeToPlan = async (plan: 'pro' | 'team') => {
    setCheckoutLoading(plan)
    try {
      if (!stripeConfigured) {
        alert('⚠ Stripe pas encore configuré. Contacte l\'admin pour activer les paiements.')
        return
      }
      const r = await api.stripeCheckout(plan)
      if (r.ok && r.url) {
        window.location.href = r.url
      } else {
        alert(r.error || 'Checkout impossible')
      }
    } catch (e: any) {
      alert(e.message || 'Erreur')
    } finally {
      setCheckoutLoading(null)
    }
  }

  const openPortal = async () => {
    try {
      const r = await api.stripePortal()
      if (r.ok && r.url) {
        window.location.href = r.url
      } else {
        alert(r.error || 'Portal indisponible')
      }
    } catch (e: any) {
      alert(e.message || 'Erreur')
    }
  }

  if (loading) {
    return <div className="page animate-fade-in" style={{ padding: '2rem', color: 'var(--text-muted)' }}>Chargement...</div>
  }
  if (error || !data) {
    return <div className="page animate-fade-in" style={{ padding: '2rem', color: 'var(--danger)' }}>{error || 'Erreur'}</div>
  }

  const { plan, usage } = data
  const limits = plan.limits

  return (
    <div className="page animate-fade-in" style={{ padding: '2rem', maxWidth: 900, margin: '0 auto' }}>
      <h1 style={{ color: 'var(--text-primary)', marginBottom: '0.3rem' }}>Plan & Quotas</h1>
      <p style={{ color: 'var(--text-muted)', marginBottom: '2rem' }}>
        Gère ton abonnement et suis ta consommation mensuelle.
      </p>

      {/* Carte plan actuel */}
      <div style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: '1rem',
        padding: '1.5rem',
        marginBottom: '1.5rem',
        position: 'relative',
        overflow: 'hidden',
      }}>
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, height: 3,
          background: PLAN_COLORS[plan.name] || PLAN_COLORS.free,
        }} />
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
              Plan actuel
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 700, color: PLAN_COLORS[plan.name] || '#fff', marginTop: 4 }}>
              {plan.display_name}
            </div>
            <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginTop: 4 }}>
              {plan.price_usd === 0 ? 'Gratuit' : `$${plan.price_usd}/mois`}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {plan.name !== 'team' && (
              <button
                onClick={() => upgradeToPlan(plan.name === 'free' ? 'pro' : 'team')}
                disabled={checkoutLoading !== null}
                style={{
                  background: 'var(--accent-violet)',
                  color: '#fff',
                  border: 'none',
                  padding: '0.75rem 1.5rem',
                  borderRadius: '0.5rem',
                  fontWeight: 600,
                  cursor: checkoutLoading !== null ? 'wait' : 'pointer',
                  fontSize: '0.9rem',
                  opacity: checkoutLoading !== null ? 0.6 : 1,
                }}
              >
                {checkoutLoading ? 'Redirection…' : (plan.name === 'free' ? '⚡ Passer à Pro' : '🚀 Upgrade Team')}
              </button>
            )}
            {plan.name !== 'free' && (
              <button
                onClick={openPortal}
                style={{
                  background: 'transparent',
                  color: 'var(--text-primary)',
                  border: '1px solid var(--border)',
                  padding: '0.75rem 1.5rem',
                  borderRadius: '0.5rem',
                  fontWeight: 500,
                  cursor: 'pointer',
                  fontSize: '0.9rem',
                }}
              >
                Gérer mon abonnement
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Usage ce mois */}
      <div style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: '1rem',
        padding: '1.5rem',
        marginBottom: '1.5rem',
      }}>
        <h2 style={{ fontSize: '1rem', color: 'var(--text-primary)', marginBottom: 4 }}>
          Consommation de {usage.month_key}
        </h2>
        <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '1.5rem' }}>
          Reset le 1er de chaque mois.
        </p>

        <UsageBar label="Messages agent" used={usage.requests} limit={limits.tokens_per_month ? -1 : 0} />
        <UsageBar label="Tokens LLM" used={usage.tokens} limit={limits.tokens_per_month} />
        <UsageBar label="Uploads" used={usage.uploads} limit={limits.uploads_per_month} />
        <UsageBar label="Deep researches" used={usage.deep_researches} limit={limits.deep_researches_per_month} />
        <UsageBar label="Skills ClawHub installés" used={usage.skills_installed} limit={limits.skills_installed} />
        <UsageBar label="Crons actifs" used={usage.crons} limit={limits.crons} />
      </div>

      {/* Comparatif */}
      <div style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: '1rem',
        padding: '1.5rem',
      }}>
        <h2 style={{ fontSize: '1rem', color: 'var(--text-primary)', marginBottom: '1rem' }}>
          Comparaison des plans
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '1rem' }}>
          {['free', 'pro', 'team'].map(p => {
            const isCurrent = plan.name === p
            const canUpgrade = !isCurrent && p !== 'free' && (
              (plan.name === 'free') || (plan.name === 'pro' && p === 'team')
            )
            return (
              <div
                key={p}
                onClick={() => canUpgrade && upgradeToPlan(p as 'pro' | 'team')}
                style={{
                  border: `1px solid ${isCurrent ? PLAN_COLORS[p] : 'var(--border)'}`,
                  borderRadius: '0.75rem',
                  padding: '1rem',
                  background: isCurrent ? 'rgba(26,111,216,0.08)' : 'transparent',
                  position: 'relative',
                  cursor: canUpgrade ? 'pointer' : 'default',
                  transition: 'all 0.15s',
                }}
                onMouseEnter={e => { if (canUpgrade) e.currentTarget.style.background = 'rgba(26,111,216,0.05)' }}
                onMouseLeave={e => { if (canUpgrade) e.currentTarget.style.background = 'transparent' }}
              >
                {isCurrent && (
                  <div style={{
                    position: 'absolute', top: -10, right: 10,
                    background: PLAN_COLORS[p], color: '#fff',
                    fontSize: '0.7rem', padding: '2px 8px',
                    borderRadius: 10, fontWeight: 600,
                  }}>
                    Actuel
                  </div>
                )}
                <div style={{ fontWeight: 700, fontSize: '1.1rem', color: PLAN_COLORS[p] }}>
                  {p === 'free' ? 'Free' : p === 'pro' ? 'Pro' : 'Team'}
                </div>
                <div style={{ fontSize: '1.5rem', color: 'var(--text-primary)', margin: '0.5rem 0' }}>
                  {p === 'free' ? '$0' : p === 'pro' ? '$20' : '$50'}
                  <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>/mois</span>
                </div>
                <ul style={{ listStyle: 'none', padding: 0, fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: 1.8 }}>
                  <li>• {p === 'free' ? '100k' : p === 'pro' ? '1M' : '10M'} tokens/mois</li>
                  <li>• {p === 'free' ? '10' : p === 'pro' ? '50' : '∞'} skills ClawHub</li>
                  <li>• {p === 'free' ? '100' : p === 'pro' ? '1000' : '∞'} uploads</li>
                  <li>• {p === 'free' ? '10' : p === 'pro' ? '100' : '1000'} deep researches</li>
                  <li>• {p === 'team' ? '10 membres workspace' : 'Workspace perso'}</li>
                </ul>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
