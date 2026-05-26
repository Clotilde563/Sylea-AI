import { useState, useEffect } from 'react'
import { api } from '../api/client'

type PlanData = Awaited<ReturnType<typeof api.getPlan>>

const ADVANCED_PRICE_EUR = '19,99'

// Une feature dans la liste : check vert / cross gris / horloge "a venir"
type FeatureState = 'included' | 'excluded' | 'coming'

function FeatureItem({ label, state }: { label: string; state: FeatureState }) {
  const icon = state === 'included' ? '✓' : state === 'excluded' ? '✕' : '⏳'
  const bg = state === 'included'
    ? 'linear-gradient(135deg, rgba(124,58,237,0.25), rgba(212,160,23,0.25))'
    : state === 'coming'
      ? 'rgba(245,158,11,0.10)'
      : 'rgba(255,255,255,0.04)'
  const border = state === 'included'
    ? '1px solid rgba(212,160,23,0.4)'
    : state === 'coming'
      ? '1px solid rgba(245,158,11,0.25)'
      : '1px solid rgba(255,255,255,0.08)'
  const labelColor = state === 'included'
    ? 'var(--text-primary)'
    : state === 'coming'
      ? '#fbbf24'
      : 'var(--text-muted)'
  const labelOpacity = state === 'excluded' ? 0.5 : 1
  const decoration = state === 'excluded' ? 'line-through' : 'none'

  return (
    <li style={{
      display: 'flex', alignItems: 'center', gap: '0.625rem',
      padding: '0.55rem 0.75rem', borderRadius: '0.5rem',
      background: state === 'included' ? 'rgba(255,255,255,0.02)' : 'transparent',
    }}>
      <span style={{
        flexShrink: 0, width: 22, height: 22, borderRadius: '50%',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        background: bg, border, fontSize: 11, fontWeight: 700,
      }}>
        {icon}
      </span>
      <span style={{
        fontSize: '0.86rem', color: labelColor,
        textDecoration: decoration, opacity: labelOpacity,
        lineHeight: 1.4,
      }}>
        {label}
        {state === 'coming' && (
          <span style={{
            marginLeft: '0.5rem',
            fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.05em',
            padding: '0.1rem 0.45rem', borderRadius: 999,
            background: 'rgba(245,158,11,0.15)', color: '#fbbf24',
            border: '1px solid rgba(245,158,11,0.3)',
            textTransform: 'uppercase',
          }}>
            À venir
          </span>
        )}
      </span>
    </li>
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

    const params = new URLSearchParams(window.location.search)
    if (params.get('paid') === '1') {
      alert('✓ Paiement confirmé ! Ton plan sera mis à jour dans quelques secondes.')
      setTimeout(() => api.getPlan().then(setData), 2000)
    }
    if (params.get('cancelled') === '1') {
      alert('Paiement annulé.')
    }
  }, [])

  const upgradeToAdvanced = async () => {
    setCheckoutLoading('advanced')
    try {
      if (!stripeConfigured) {
        alert('⚠ Les paiements ne sont pas encore activés. Contacte-nous pour démarrer.')
        return
      }
      const r = await api.stripeCheckout('advanced')
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
    return (
      <div className="page animate-fade-in" style={{ padding: '2rem', color: 'var(--text-muted)', textAlign: 'center' }}>
        Chargement…
      </div>
    )
  }
  if (error || !data) {
    return (
      <div className="page animate-fade-in" style={{ padding: '2rem', color: 'var(--danger)' }}>
        {error || 'Erreur'}
      </div>
    )
  }

  const { plan } = data
  const isFree = plan.name === 'free'
  const isAdvanced = !isFree

  // ── Feature lists (validees avec utilisateur) ──────────────────────────
  const FREE_FEATURES: Array<{ label: string; state: FeatureState }> = [
    { label: 'Agent Syléa 1 (compagnon personnel)', state: 'included' },
    { label: 'Profil personnalisé + objectif de vie', state: 'included' },
    { label: 'Analyse de choix, évènements et messages Agent 1 — limité à 10 actions / jour', state: 'included' },
    { label: 'Suivi de progression simplifié', state: 'included' },
    { label: '« Que faire ? » — plan d\'action IA quotidien', state: 'excluded' },
    { label: 'Agent Syléa 2 (assistant exécutant)', state: 'excluded' },
    { label: 'Syléa Desktop (mails, calendrier, notes…)', state: 'excluded' },
    { label: 'Intégrations', state: 'excluded' },
  ]

  const ADVANCED_FEATURES: Array<{ label: string; state: FeatureState }> = [
    { label: 'Agent Syléa 1 + Agent Syléa 2 (assistant exécutant)', state: 'included' },
    { label: '« Que faire ? » — plan d\'action IA quotidien', state: 'included' },
    { label: 'Syléa Desktop (mails, calendrier, notes, prise de cours…)', state: 'included' },
    { label: 'Analyses, évènements et messages — limité à 30 actions / jour', state: 'included' },
    { label: 'Statistiques avancées + courbes de progression', state: 'included' },
    { label: 'Notifications intelligentes & vérifications de tâches', state: 'included' },
    { label: 'Intégrations', state: 'excluded' },
  ]

  return (
    <div className="page animate-fade-in" style={{ minHeight: '100vh', position: 'relative', overflow: 'hidden' }}>
      <style>{`
        @keyframes shimmer-gold {
          0%, 100% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
        }
        @keyframes pulse-glow {
          0%, 100% { box-shadow: 0 0 0 0 rgba(212,160,23,0.4), 0 8px 32px rgba(124,58,237,0.25); }
          50% { box-shadow: 0 0 0 8px rgba(212,160,23,0), 0 12px 40px rgba(212,160,23,0.35); }
        }
        @keyframes float-up {
          from { opacity: 0; transform: translateY(16px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .gold-shimmer-text {
          background: linear-gradient(90deg, #fbbf24, #fde68a, #fbbf24, #d4a017, #fbbf24);
          background-size: 200% 100%;
          -webkit-background-clip: text; background-clip: text;
          -webkit-text-fill-color: transparent; color: transparent;
          animation: shimmer-gold 4s ease-in-out infinite;
        }
        .advanced-card {
          animation: float-up 0.6s ease-out 0.1s both;
        }
        .advanced-cta {
          animation: pulse-glow 2.4s ease-in-out infinite;
        }
        .free-card {
          animation: float-up 0.5s ease-out;
        }
        .background-orb {
          position: absolute; border-radius: 50%; filter: blur(80px);
          pointer-events: none; opacity: 0.3;
        }
      `}</style>

      <div className="background-orb" style={{
        width: 400, height: 400, top: -100, right: -100,
        background: 'radial-gradient(circle, rgba(124,58,237,0.4), transparent)',
      }} />
      <div className="background-orb" style={{
        width: 500, height: 500, bottom: -150, left: -150,
        background: 'radial-gradient(circle, rgba(212,160,23,0.3), transparent)',
      }} />

      <div className="container page-content" style={{
        maxWidth: 980, margin: '0 auto', padding: '2rem 1.25rem 4rem', position: 'relative', zIndex: 1,
      }}>
        {/* ═══ Hero ═══════════════════════════════════════════════════════ */}
        <div style={{ textAlign: 'center', marginBottom: '2.5rem' }}>
          {isAdvanced ? (
            <>
              <div style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
                padding: '0.4rem 1rem', borderRadius: 999, marginBottom: '1rem',
                background: 'linear-gradient(135deg, rgba(124,58,237,0.15), rgba(212,160,23,0.15))',
                border: '1px solid rgba(212,160,23,0.3)',
                fontSize: '0.78rem', fontWeight: 600, letterSpacing: '0.04em',
              }}>
                <span style={{ fontSize: '1rem' }}>✨</span>
                <span className="gold-shimmer-text">Membre Avancé</span>
              </div>
              <h1 style={{ fontSize: '2.4rem', fontWeight: 800, margin: '0 0 0.5rem', color: 'var(--text-primary)' }}>
                Tu es au plein potentiel.
              </h1>
              <p style={{ color: 'var(--text-muted)', fontSize: '1rem', maxWidth: 560, margin: '0 auto' }}>
                Profite de tous les outils Sylea sans limite. On gère ton abonnement, tu gères ton avenir.
              </p>
            </>
          ) : (
            <>
              <div style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
                padding: '0.35rem 0.9rem', borderRadius: 999, marginBottom: '1rem',
                background: 'rgba(124,58,237,0.12)',
                border: '1px solid rgba(124,58,237,0.25)',
                fontSize: '0.72rem', fontWeight: 600, letterSpacing: '0.06em',
                color: 'var(--accent-violet-light)', textTransform: 'uppercase',
              }}>
                <span>◈</span> Choisis ton plan
              </div>
              <h1 style={{
                fontSize: 'clamp(2rem, 5vw, 2.8rem)', fontWeight: 800,
                margin: '0 0 0.65rem', lineHeight: 1.15,
                color: 'var(--text-primary)',
              }}>
                Débloque ton plein potentiel<br />
                <span className="gold-shimmer-text">avec Sylea Avancé.</span>
              </h1>
              <p style={{
                color: 'var(--text-muted)', fontSize: '1rem',
                maxWidth: 560, margin: '0 auto', lineHeight: 1.55,
              }}>
                Sylea t'accompagne chaque jour vers tes objectifs avec un coach IA personnalisé.{' '}
                <strong style={{ color: 'var(--text-secondary)' }}>Sans engagement, annulable à tout moment.</strong>
              </p>
            </>
          )}
        </div>

        {/* ═══ Pricing rows (uniquement Free) ═══════════════════════════════ */}
        {isFree && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', marginBottom: '2.5rem' }}>
            {/* Card Gratuit (full row) */}
            <div className="free-card" style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: '1.25rem',
              padding: '1.75rem 2rem',
              display: 'grid',
              gridTemplateColumns: 'minmax(220px, 280px) 1fr',
              gap: '2rem',
              alignItems: 'start',
            }}>
              {/* Col gauche : titre + prix + bouton */}
              <div>
                <div style={{
                  display: 'inline-flex', alignItems: 'center',
                  padding: '0.25rem 0.7rem', borderRadius: 999,
                  background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)',
                  fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-muted)',
                  textTransform: 'uppercase', letterSpacing: '0.06em',
                  marginBottom: '0.875rem',
                }}>
                  Plan actuel
                </div>
                <h2 style={{ fontSize: '1.5rem', fontWeight: 700, margin: '0 0 0.25rem', color: 'var(--text-primary)' }}>
                  Gratuit
                </h2>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', margin: '0 0 1.25rem' }}>
                  Pour découvrir Sylea
                </p>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.3rem', marginBottom: '1.25rem' }}>
                  <span style={{ fontSize: '2.5rem', fontWeight: 800, color: 'var(--text-primary)' }}>0</span>
                  <span style={{ fontSize: '1.4rem', fontWeight: 600, color: 'var(--text-secondary)' }}>€</span>
                  <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>/mois</span>
                </div>
                <button
                  disabled
                  style={{
                    width: '100%', padding: '0.75rem 1rem',
                    background: 'rgba(255,255,255,0.04)',
                    border: '1px solid var(--border)',
                    borderRadius: '0.625rem',
                    color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.85rem',
                    cursor: 'default',
                  }}
                >
                  Plan actuel
                </button>
              </div>

              {/* Col droite : features */}
              <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '0.15rem' }}>
                {FREE_FEATURES.map((f) => (
                  <FeatureItem key={f.label} label={f.label} state={f.state} />
                ))}
              </ul>
            </div>

            {/* Card Avancé (full row, mise en valeur) */}
            <div className="advanced-card" style={{
              background: 'linear-gradient(155deg, rgba(124,58,237,0.10) 0%, rgba(15,12,30,0.85) 35%, rgba(212,160,23,0.10) 100%)',
              borderRadius: '1.25rem',
              padding: '1.75rem 2rem',
              position: 'relative',
              boxShadow: '0 8px 32px rgba(124,58,237,0.15)',
              display: 'grid',
              gridTemplateColumns: 'minmax(220px, 280px) 1fr',
              gap: '2rem',
              alignItems: 'start',
            }}>
              {/* Border gradient via overlay */}
              <div style={{
                position: 'absolute', inset: 0, borderRadius: '1.25rem',
                padding: 1.5,
                background: 'linear-gradient(135deg, rgba(124,58,237,0.6), rgba(212,160,23,0.6), rgba(124,58,237,0.6))',
                WebkitMask: 'linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)',
                WebkitMaskComposite: 'xor', maskComposite: 'exclude',
                pointerEvents: 'none',
              }} />

              {/* Badge "Recommande" centre haut */}
              <div style={{
                position: 'absolute', top: -12, left: '50%', transform: 'translateX(-50%)',
                background: 'linear-gradient(135deg, #7c3aed, #d4a017, #fbbf24)',
                backgroundSize: '200% 100%',
                animation: 'shimmer-gold 3s ease-in-out infinite',
                color: '#fff', fontSize: '0.7rem', fontWeight: 700,
                padding: '0.35rem 1rem', borderRadius: 999,
                letterSpacing: '0.06em', textTransform: 'uppercase',
                boxShadow: '0 4px 16px rgba(124,58,237,0.4)',
                whiteSpace: 'nowrap', zIndex: 2,
              }}>
                ⭐ Le plus complet
              </div>

              {/* Col gauche : titre + prix + bouton */}
              <div style={{ position: 'relative', zIndex: 1 }}>
                <div style={{
                  display: 'inline-flex', alignItems: 'center',
                  padding: '0.25rem 0.7rem', borderRadius: 999,
                  background: 'rgba(212,160,23,0.12)', border: '1px solid rgba(212,160,23,0.3)',
                  fontSize: '0.7rem', fontWeight: 600, color: '#fbbf24',
                  textTransform: 'uppercase', letterSpacing: '0.06em',
                  marginBottom: '0.875rem',
                }}>
                  ✨ Recommandé
                </div>
                <h2 className="gold-shimmer-text" style={{
                  fontSize: '1.65rem', fontWeight: 800,
                  margin: '0 0 0.25rem',
                }}>
                  Avancé
                </h2>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', margin: '0 0 1.25rem' }}>
                  Pour exploiter Sylea à 100%
                </p>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.3rem', marginBottom: '0.4rem' }}>
                  <span style={{
                    fontSize: '2.5rem', fontWeight: 800,
                    background: 'linear-gradient(135deg, #fbbf24, #d4a017)',
                    WebkitBackgroundClip: 'text', backgroundClip: 'text',
                    WebkitTextFillColor: 'transparent',
                  }}>
                    {ADVANCED_PRICE_EUR}
                  </span>
                  <span style={{ fontSize: '1.4rem', fontWeight: 600, color: '#d4a017' }}>€</span>
                  <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>/mois</span>
                </div>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: '0 0 1.25rem' }}>
                  Soit <strong style={{ color: '#d4a017' }}>moins d'1 café par semaine</strong>.
                </p>
                <button
                  onClick={upgradeToAdvanced}
                  disabled={checkoutLoading !== null}
                  className="advanced-cta"
                  style={{
                    width: '100%', padding: '0.95rem 1rem',
                    background: 'linear-gradient(135deg, #7c3aed 0%, #a855f7 30%, #d4a017 70%, #fbbf24 100%)',
                    backgroundSize: '200% 100%',
                    border: 'none', borderRadius: '0.75rem',
                    color: '#fff', fontWeight: 700, fontSize: '0.9rem',
                    cursor: checkoutLoading !== null ? 'wait' : 'pointer',
                    letterSpacing: '0.02em',
                    transition: 'transform 0.15s, background-position 0.3s',
                    opacity: checkoutLoading !== null ? 0.7 : 1,
                  }}
                  onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.backgroundPosition = '100% 0' }}
                  onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.backgroundPosition = '0% 0' }}
                >
                  {checkoutLoading ? 'Redirection…' : `🚀 Passer à Avancé`}
                </button>
                <p style={{
                  fontSize: '0.7rem', color: 'var(--text-muted)', textAlign: 'center',
                  margin: '0.6rem 0 0',
                }}>
                  ✓ Sans engagement &nbsp;·&nbsp; ✓ Annulable en 1 clic
                </p>
              </div>

              {/* Col droite : features */}
              <ul style={{
                listStyle: 'none', padding: 0, margin: 0,
                display: 'flex', flexDirection: 'column', gap: '0.15rem',
                position: 'relative', zIndex: 1,
              }}>
                {ADVANCED_FEATURES.map((f) => (
                  <FeatureItem key={f.label} label={f.label} state={f.state} />
                ))}
              </ul>
            </div>
          </div>
        )}

        {/* ═══ Trust block (uniquement Free) ════════════════════════════════ */}
        {isFree && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: '1rem',
            marginBottom: '2.5rem',
            padding: '1.5rem',
            background: 'rgba(255,255,255,0.02)',
            border: '1px solid rgba(255,255,255,0.05)',
            borderRadius: '1rem',
          }}>
            {[
              { icon: '🔒', title: 'Données chiffrées', desc: 'Tes informations restent sur ton compte, point.' },
              { icon: '⚡', title: 'Annulation immédiate', desc: 'Pas d\'engagement, pas de question.' },
              { icon: '💳', title: 'Paiement sécurisé', desc: 'Géré par Stripe, leader du paiement en ligne.' },
            ].map((b) => (
              <div key={b.title} style={{ textAlign: 'center', padding: '0.5rem' }}>
                <div style={{ fontSize: '1.6rem', marginBottom: '0.4rem' }}>{b.icon}</div>
                <div style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '0.2rem' }}>
                  {b.title}
                </div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  {b.desc}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ═══ Membre Avance : header + portail ═════════════════════════════ */}
        {isAdvanced && (
          <div style={{
            background: 'linear-gradient(155deg, rgba(124,58,237,0.08), rgba(15,12,30,0.8), rgba(212,160,23,0.08))',
            border: '1px solid rgba(212,160,23,0.25)',
            borderRadius: '1.25rem',
            padding: '1.75rem',
            marginBottom: '1.5rem',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            flexWrap: 'wrap', gap: '1rem',
          }}>
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                Ton plan
              </div>
              <div className="gold-shimmer-text" style={{ fontSize: '2rem', fontWeight: 800, marginTop: 4 }}>
                Sylea Avancé
              </div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: 4 }}>
                {ADVANCED_PRICE_EUR} €/mois
              </div>
            </div>
            <button
              onClick={openPortal}
              style={{
                padding: '0.75rem 1.5rem',
                background: 'transparent',
                border: '1px solid rgba(212,160,23,0.4)',
                borderRadius: '0.625rem',
                color: '#d4a017', fontWeight: 600, fontSize: '0.9rem',
                cursor: 'pointer', whiteSpace: 'nowrap',
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'rgba(212,160,23,0.08)' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
            >
              Gérer mon abonnement
            </button>
          </div>
        )}

        {/* ═══ Code promo ═══════════════════════════════════════════════════ */}
        {isFree && <PromoCodeSection />}
      </div>
    </div>
  )
}

/**
 * Champ "Code promo" : permet a l'utilisateur d'appliquer un coupon Stripe
 * avant de s'abonner. Simule le flow Stripe Checkout avec un parametre
 * coupon optionnel passe a la session de checkout.
 */
function PromoCodeSection() {
  const [code, setCode] = useState('')
  const [applying, setApplying] = useState(false)
  const [feedback, setFeedback] = useState<{ kind: 'idle' | 'success' | 'error'; msg: string }>({ kind: 'idle', msg: '' })

  const apply = async () => {
    const trimmed = code.trim()
    if (!trimmed) {
      setFeedback({ kind: 'error', msg: 'Entre un code avant de l\'appliquer.' })
      return
    }
    setApplying(true)
    setFeedback({ kind: 'idle', msg: '' })
    try {
      const r = await api.stripeCheckout('advanced', { coupon: trimmed })
      if (r.ok && r.url) {
        // Le code est valide, on bascule sur la page de paiement Stripe.
        setFeedback({ kind: 'success', msg: 'Code appliqué — redirection vers le paiement…' })
        window.location.href = r.url
      } else {
        setFeedback({
          kind: 'error',
          msg: r.error || 'Code invalide ou expiré.',
        })
      }
    } catch (e: any) {
      setFeedback({ kind: 'error', msg: e?.message || 'Erreur inattendue.' })
    } finally {
      setApplying(false)
    }
  }

  return (
    <div style={{
      marginTop: '2.5rem',
      padding: '1.5rem',
      background: 'rgba(255,255,255,0.02)',
      border: '1px solid rgba(255,255,255,0.06)',
      borderRadius: '1rem',
      maxWidth: 520, marginLeft: 'auto', marginRight: 'auto',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.6rem' }}>
        <span style={{ fontSize: '1.1rem' }}>🎟️</span>
        <h3 style={{
          fontSize: '0.95rem', fontWeight: 700, color: 'var(--text-primary)',
          margin: 0, letterSpacing: '0.02em',
        }}>
          Tu as un code promo ?
        </h3>
      </div>
      <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', margin: '0 0 0.875rem', lineHeight: 1.5 }}>
        Entre ton code ci-dessous pour bénéficier d'une réduction lors du passage à Sylea Avancé.
      </p>
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <input
          type="text"
          value={code}
          onChange={(e) => { setCode(e.target.value.toUpperCase()); setFeedback({ kind: 'idle', msg: '' }) }}
          placeholder="EX: SYLEA20"
          disabled={applying}
          style={{
            flex: 1, padding: '0.7rem 0.9rem',
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid var(--border)',
            borderRadius: '0.5rem',
            color: 'var(--text-primary)', fontSize: '0.88rem',
            fontFamily: 'var(--font-mono, monospace)',
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
            outline: 'none',
          }}
          onKeyDown={(e) => { if (e.key === 'Enter') apply() }}
        />
        <button
          onClick={apply}
          disabled={applying || !code.trim()}
          style={{
            padding: '0.7rem 1.25rem',
            background: applying || !code.trim()
              ? 'rgba(255,255,255,0.06)'
              : 'linear-gradient(135deg, #7c3aed, #d4a017)',
            border: 'none',
            borderRadius: '0.5rem',
            color: '#fff', fontWeight: 700, fontSize: '0.85rem',
            cursor: applying || !code.trim() ? 'not-allowed' : 'pointer',
            whiteSpace: 'nowrap',
          }}
        >
          {applying ? 'Vérification…' : 'Appliquer'}
        </button>
      </div>
      {feedback.kind !== 'idle' && (
        <p style={{
          margin: '0.7rem 0 0',
          fontSize: '0.8rem',
          color: feedback.kind === 'success' ? '#4ade80' : '#f87171',
          fontWeight: 500,
        }}>
          {feedback.kind === 'success' ? '✓ ' : '⚠ '}{feedback.msg}
        </p>
      )}
    </div>
  )
}
