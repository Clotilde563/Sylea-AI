// Barre de navigation principale Syléa.AI

import { Link, useLocation } from 'react-router-dom'
import { SyleaLogo } from './SyleaLogo'
import { useStore } from '../store/useStore'

export function NavBar() {
  const { pathname } = useLocation()
  const profil = useStore((s) => s.profil)

  const links = [
    { to: '/', label: 'Tableau de bord' },
    { to: '/dilemme', label: 'Analyser un choix' },
    { to: '/statistiques', label: 'Statistiques' },
    { to: '/profil', label: profil ? 'Mon profil' : 'Créer un profil' },
  ]

  return (
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
        {/* Logo + brand */}
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
  )
}
