// Barre de navigation principale Syléa.AI

import { useState, useRef, useEffect } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { SyleaLogo } from './SyleaLogo'
import { useStore } from '../store/useStore'
import { useAuthStore } from '../auth/authStore'
import { useT } from '../i18n/LanguageContext'
import { ConfirmProfilModal } from './ConfirmProfilModal'
import PlanBadge from './PlanBadge'

// Email du compte owner (seul a voir l'entree menu Admin)
const ADMIN_EMAIL = 'louisdeniau35@gmail.com'

// Small red dot shown when there are unread proactive agent messages
function AgentNotificationDot() {
  const unread = useStore((s) => s.unreadAgentMessages)
  if (unread <= 0) return null
  return (
    <span style={{
      position: 'absolute',
      top: 2,
      right: 2,
      width: 9,
      height: 9,
      borderRadius: '50%',
      background: '#ef4444',
      border: '2px solid rgba(3,7,15,0.94)',
      boxShadow: '0 0 6px rgba(239,68,68,0.6)',
      animation: 'agent-pulse-dot-nav 2s ease-in-out infinite',
    }} />
  )
}

interface NavBarProps {
  onOpenChatbot?: () => void
}

export function NavBar({ onOpenChatbot }: NavBarProps) {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const profil = useStore((s) => s.profil)
  const authUser = useAuthStore((s) => s.user)
  const isAdmin = (authUser?.email || '').trim().toLowerCase() === ADMIN_EMAIL
  const t = useT()
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [showProfilModal, setShowProfilModal] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Click outside to close dropdown
  useEffect(() => {
    if (!dropdownOpen) return
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [dropdownOpen])

  // Masquer tous les liens tant que le profil n'est pas créé
  const links = profil ? [
    { to: '/', label: t('nav.dashboard') },
    { to: '/statistiques', label: t('nav.statistiques') || 'Statistiques' },
    { to: '/tracking', label: 'Mes dilemmes' },
    { to: '/progression-decisions', label: t('nav.progression_decisions') || 'Progression des décisions' },
  ] : []

  return (
    <>
    <nav
      className="glass-strong"
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 100,
        borderBottom: '1px solid var(--border)',
        backgroundImage: 'linear-gradient(180deg, rgba(8,9,12,0.85), rgba(8,9,12,0.78))',
      }}
    >
      <div
        className="container container-lg"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          height: '3.25rem',
        }}
      >
        {/* Logo + brand + arrow */}
        <div ref={dropdownRef} style={{ display: 'flex', alignItems: 'center', position: 'relative' }}>
          <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', textDecoration: 'none' }}>
            <SyleaLogo size={28} animated={false} />
            <span style={{
              fontWeight: 700,
              fontSize: '0.95rem',
              letterSpacing: '0.06em',
              fontFeatureSettings: '"cv11", "ss03"',
            }}>
              <span style={{ color: 'var(--text-primary)' }}>Syléa</span>
              <span className="headline-gradient" style={{ marginLeft: 1, fontWeight: 800 }}>.ai</span>
            </span>
          </Link>

          {/* Badge plan actuel */}
          <div style={{ marginLeft: '0.6rem' }}>
            <PlanBadge />
          </div>

          {/* Flèche dropdown */}
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            style={{
              background: 'transparent', border: 'none', cursor: 'pointer',
              padding: '4px 6px', marginLeft: 4,
              display: 'flex', alignItems: 'center',
              color: 'var(--text-muted)',
              transition: 'transform var(--duration-base) var(--ease-out), color var(--duration-fast) var(--ease-out)',
              transform: dropdownOpen ? 'rotate(180deg)' : 'rotate(0deg)',
              borderRadius: 'var(--radius-sm)',
            }}
            onMouseEnter={e => { e.currentTarget.style.color = 'var(--text-primary)' }}
            onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-muted)' }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </button>

          {/* Dropdown menu — Linear style (glass + border subtle + items propres) */}
          {dropdownOpen && (
            <div className="glass-strong animate-fade-in-scale" style={{
              position: 'absolute', top: '100%', left: 0,
              marginTop: 8,
              border: '1px solid var(--border-strong)',
              borderRadius: 'var(--radius-lg)',
              boxShadow: 'var(--shadow-xl)',
              minWidth: 300, zIndex: 200,
              overflow: 'hidden',
              padding: 4,
            }}>
              {/* Onglet 0: Parametres */}
              <button
                onClick={() => { setDropdownOpen(false); navigate('/parametres') }}
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.6rem',
                  width: '100%', padding: '0.75rem 1rem',
                  background: 'transparent', border: 'none', borderBottom: '1px solid var(--border)',
                  color: 'var(--text-secondary)', fontSize: '0.82rem',
                  cursor: 'pointer', textAlign: 'left',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
                </svg>
                <div>
                  <div style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{t('nav.parametres')}</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>{t('nav.parametres_desc')}</div>
                </div>
              </button>

              {/* Intégrations & Sécurité — temporairement greye, "à venir" */}
              <button
                disabled
                aria-disabled="true"
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.6rem',
                  width: '100%', padding: '0.75rem 1rem',
                  background: 'transparent', border: 'none', borderBottom: '1px solid var(--border)',
                  color: 'var(--text-muted)', fontSize: '0.82rem',
                  cursor: 'not-allowed', textAlign: 'left',
                  opacity: 0.55,
                }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
                </svg>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontWeight: 500, color: 'var(--text-secondary)' }}>
                    Intégrations & Sécurité
                    <span style={{
                      fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.05em',
                      padding: '0.08rem 0.4rem', borderRadius: 999,
                      background: 'rgba(245,158,11,0.15)', color: '#fbbf24',
                      border: '1px solid rgba(245,158,11,0.3)',
                      textTransform: 'uppercase',
                    }}>
                      À venir
                    </span>
                  </div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>Services OAuth · Clés API tierces · Tokens B2B</div>
                </div>
              </button>

              {/* Phase 10/11 entries */}
              <button
                onClick={() => { setDropdownOpen(false); navigate('/quotas') }}
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.6rem',
                  width: '100%', padding: '0.75rem 1rem',
                  background: 'transparent', border: 'none', borderBottom: '1px solid var(--border)',
                  color: 'var(--text-secondary)', fontSize: '0.82rem',
                  cursor: 'pointer', textAlign: 'left', transition: 'background 0.15s',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="12 2 15 8 22 9 17 14 18 21 12 17 6 21 7 14 2 9 9 8"/>
                </svg>
                <div>
                  <div style={{ fontWeight: 500, color: 'var(--text-primary)' }}>Plan & Quotas</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>Abonnement, consommation mensuelle</div>
                </div>
              </button>

              {/* Onglet Admin — visible uniquement pour le compte owner */}
              {isAdmin && (
                <button
                  onClick={() => { setDropdownOpen(false); navigate('/admin') }}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '0.6rem',
                    width: '100%', padding: '0.75rem 1rem',
                    background: 'transparent', border: 'none', borderBottom: '1px solid var(--border)',
                    color: 'var(--text-secondary)', fontSize: '0.82rem',
                    cursor: 'pointer', textAlign: 'left', transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                  </svg>
                  <div>
                    <div style={{ fontWeight: 500, color: 'var(--text-primary)' }}>Admin</div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>Dashboard owner (réservé)</div>
                  </div>
                </button>
              )}

              {/* Onglet 1: Aide et ressources */}
              <button
                onClick={() => { setDropdownOpen(false); navigate('/help') }}
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.6rem',
                  width: '100%', padding: '0.75rem 1rem',
                  background: 'transparent', border: 'none', borderBottom: '1px solid var(--border)',
                  color: 'var(--text-secondary)', fontSize: '0.82rem',
                  cursor: 'pointer', textAlign: 'left',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                </svg>
                <div>
                  <div style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{t('nav.aide')}</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>{t('nav.aide_desc')}</div>
                </div>
              </button>

              {/* Onglet 2: Service client */}
              <button
                onClick={() => {
                  setDropdownOpen(false)
                  onOpenChatbot?.()
                }}
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.6rem',
                  width: '100%', padding: '0.75rem 1rem',
                  background: 'transparent', border: 'none', borderBottom: '1px solid var(--border)',
                  color: 'var(--text-secondary)', fontSize: '0.82rem',
                  cursor: 'pointer', textAlign: 'left',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                </svg>
                <div>
                  <div style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{t('nav.service')}</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>{t('nav.service_desc')}</div>
                </div>
              </button>

              {/* Onglet 7: Modifier / Créer mon profil */}
              <button
                onClick={() => {
                  setDropdownOpen(false)
                  if (profil) {
                    setShowProfilModal(true)
                  } else {
                    navigate('/profil')
                  }
                }}
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.6rem',
                  width: '100%', padding: '0.75rem 1rem',
                  background: 'transparent', border: 'none',
                  color: 'var(--text-secondary)', fontSize: '0.82rem',
                  cursor: 'pointer', textAlign: 'left',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={profil ? '#ef4444' : 'var(--accent-violet-light)'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
                <div>
                  <div style={{ fontWeight: 500, color: profil ? '#ef4444' : 'var(--accent-violet-light)' }}>{profil ? t('nav.profil_edit') : t('nav.profil_create')}</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>{profil ? t('nav.profil_edit_desc') : t('nav.profil_create_desc')}</div>
                </div>
              </button>
            </div>
          )}
        </div>

        {/* Liens de navigation — style Linear (subtle, active state via couleur+dot) */}
        <div style={{ display: 'flex', gap: '2px', alignItems: 'center' }}>
          {links.map(({ to, label }) => {
            const active = pathname === to || (to !== '/' && pathname.startsWith(to))
            return (
              <Link
                key={to}
                to={to}
                style={{
                  position: 'relative',
                  padding: '7px 12px',
                  borderRadius: 'var(--radius-md)',
                  fontSize: 'var(--fs-sm)',
                  fontWeight: 500,
                  letterSpacing: 'var(--tracking-normal)',
                  color: active ? 'var(--text-primary)' : 'var(--text-muted)',
                  background: active ? 'var(--bg-elevated)' : 'transparent',
                  textDecoration: 'none',
                  transition: 'color var(--duration-fast) var(--ease-out), background var(--duration-fast) var(--ease-out)',
                  whiteSpace: 'nowrap',
                }}
                onMouseEnter={e => {
                  if (!active) {
                    e.currentTarget.style.color = 'var(--text-secondary)'
                    e.currentTarget.style.background = 'rgba(255,255,255,0.03)'
                  }
                }}
                onMouseLeave={e => {
                  if (!active) {
                    e.currentTarget.style.color = 'var(--text-muted)'
                    e.currentTarget.style.background = 'transparent'
                  }
                }}
              >
                {label}
                {active && (
                  <span style={{
                    position: 'absolute',
                    bottom: -1,
                    left: '50%',
                    transform: 'translateX(-50%)',
                    width: 18,
                    height: 2,
                    borderRadius: 1,
                    background: 'var(--sylea-gradient)',
                    boxShadow: '0 0 8px rgba(59,130,246,0.5)',
                  }} />
                )}
              </Link>
            )
          })}
          {/* Mes agents Syléa — lien scintillant (masqué sans profil) */}
          {profil && (() => {
            const agentsActive = pathname === '/agents' || pathname.startsWith('/agents')
            return (
              <Link
                to="/agents"
                className="sylea-shimmer-link"
                style={{
                  padding: '0.375rem 0.75rem',
                  borderRadius: '6px',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  textDecoration: 'none',
                  whiteSpace: 'nowrap',
                  position: 'relative',
                  background: agentsActive
                    ? 'linear-gradient(135deg, rgba(59,130,246,0.15), rgba(139,92,246,0.15), rgba(239,68,68,0.15))'
                    : 'transparent',
                  border: agentsActive
                    ? '1px solid rgba(139,92,246,0.35)'
                    : '1px solid transparent',
                  backgroundClip: 'padding-box',
                  transition: 'all 0.2s',
                }}
              >
                <span style={{
                  background: 'linear-gradient(90deg, #3b82f6, #8b5cf6, #ef4444, #f59e0b, #3b82f6)',
                  backgroundSize: '200% 100%',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  animation: 'sylea-shimmer 3s linear infinite',
                }}>
                  {t('nav.agents')}
                </span>
                {/* Notification dot for unread proactive messages */}
                <AgentNotificationDot />
              </Link>
            )
          })()}
        </div>
      </div>
    </nav>

    {/* Modale de confirmation profil */}
    <ConfirmProfilModal
      visible={showProfilModal}
      onConfirm={() => { setShowProfilModal(false); navigate('/profil') }}
      onCancel={() => setShowProfilModal(false)}
    />
    </>
  )
}
