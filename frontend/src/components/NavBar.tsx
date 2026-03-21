// Barre de navigation principale Syléa.AI

import { useState, useRef, useEffect } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { SyleaLogo } from './SyleaLogo'
import { useStore } from '../store/useStore'
import { useT } from '../i18n/LanguageContext'
import { ConfirmProfilModal } from './ConfirmProfilModal'

interface NavBarProps {
  onOpenChatbot?: () => void
}

export function NavBar({ onOpenChatbot }: NavBarProps) {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const profil = useStore((s) => s.profil)
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

  const links = [
    { to: '/', label: t('nav.dashboard') },
    { to: '/dilemme', label: t('nav.analyser') },
    { to: '/statistiques', label: t('nav.statistiques') },
  ]

  return (
    <>
    <nav
      style={{
        background: 'rgba(3,7,15,0.94)',
        backdropFilter: 'blur(16px)',
        borderBottom: '1px solid var(--border)',
        position: 'sticky',
        top: 0,
        zIndex: 100,
      }}
    >
      <div
        className="container"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          height: '3.5rem',
        }}
      >
        {/* Logo + brand + arrow */}
        <div ref={dropdownRef} style={{ display: 'flex', alignItems: 'center', position: 'relative' }}>
          <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', textDecoration: 'none' }}>
            <SyleaLogo size={34} animated={false} />
            <span style={{ fontWeight: 700, fontSize: '1.05rem', letterSpacing: '0.12em' }}>
              <span style={{
                color: 'var(--accent-silver)',
                filter: 'drop-shadow(0 0 6px rgba(184,208,234,0.35))',
              }}>SYLÉA</span>
              <span style={{
                color: 'var(--accent-violet-light)',
                marginLeft: '0.25rem',
                filter: 'drop-shadow(0 0 5px rgba(64,144,240,0.6))',
              }}>.AI</span>
            </span>
          </Link>

          {/* Flèche dropdown */}
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            style={{
              background: 'transparent', border: 'none', cursor: 'pointer',
              padding: '0.25rem 0.35rem', marginLeft: '0.3rem',
              display: 'flex', alignItems: 'center',
              color: 'var(--text-muted)',
              transition: 'transform 0.2s, color 0.15s',
              transform: dropdownOpen ? 'rotate(180deg)' : 'rotate(0deg)',
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </button>

          {/* Dropdown menu */}
          {dropdownOpen && (
            <div style={{
              position: 'absolute', top: '100%', left: 0,
              marginTop: '0.35rem',
              background: 'rgba(6, 12, 26, 0.94)',
              backdropFilter: 'blur(20px)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg)',
              boxShadow: '0 12px 40px rgba(0,0,0,0.7)',
              minWidth: 280, zIndex: 200,
              animation: 'fadeInScale 0.15s ease',
              overflow: 'hidden',
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

              {/* Onglet 1: Aide et ressources */}
              <button
                onClick={() => setDropdownOpen(false)}
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

              {/* Onglet 3: Modifier / Créer mon profil */}
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
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
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

        {/* Liens de navigation */}
        <div style={{ display: 'flex', gap: '0.25rem' }}>
          {links.map(({ to, label }) => {
            const active = pathname === to || (to !== '/' && pathname.startsWith(to))
            return (
              <Link
                key={to}
                to={to}
                style={{
                  padding: '0.375rem 0.75rem',
                  borderRadius: '6px',
                  fontSize: '0.85rem',
                  fontWeight: active ? 600 : 400,
                  color: active ? 'var(--accent-violet-light)' : 'var(--text-muted)',
                  background: active ? 'rgba(26,111,216,0.13)' : 'transparent',
                  border: active ? '1px solid rgba(26,111,216,0.25)' : '1px solid transparent',
                  textDecoration: 'none',
                  transition: 'all 0.15s',
                  whiteSpace: 'nowrap',
                }}
              >
                {label}
              </Link>
            )
          })}
          {/* Mes agents Syléa — lien scintillant */}
          {(() => {
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
