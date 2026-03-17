// Barre de navigation principale Syléa.AI

import { useState, useRef, useEffect } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { SyleaLogo } from './SyleaLogo'
import { useStore } from '../store/useStore'
import { ConfirmProfilModal } from './ConfirmProfilModal'

interface NavBarProps {
  onOpenChatbot?: () => void
}

export function NavBar({ onOpenChatbot }: NavBarProps) {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const profil = useStore((s) => s.profil)
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
    { to: '/', label: 'Tableau de bord' },
    { to: '/dilemme', label: 'Analyser un choix' },
    { to: '/statistiques', label: 'Statistiques' },
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
                  <div style={{ fontWeight: 500, color: 'var(--text-primary)' }}>Aide et ressources</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>Bientôt disponible</div>
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
                  <div style={{ fontWeight: 500, color: 'var(--text-primary)' }}>Service client</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>Posez vos questions</div>
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
                  <div style={{ fontWeight: 500, color: profil ? '#ef4444' : 'var(--accent-violet-light)' }}>{profil ? 'Modifier mon profil' : 'Créer mon profil'}</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>{profil ? 'Informations et objectif' : 'Commencez ici'}</div>
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
