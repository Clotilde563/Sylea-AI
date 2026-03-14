// Page Splash — Logo animé + redirect automatique

import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { SyleaLogo } from '../components/SyleaLogo'
import { useStore } from '../store/useStore'
import { api } from '../api/client'

export function SplashPage() {
  const navigate = useNavigate()
  const setProfil = useStore((s) => s.setProfil)

  useEffect(() => {
    // Tenter de charger le profil existant
    api.getProfil()
      .then((p) => {
        setProfil(p)
        setTimeout(() => navigate('/'), 2200)
      })
      .catch(() => {
        // Pas de profil → wizard
        setTimeout(() => navigate('/profil'), 2200)
      })
  }, [navigate, setProfil])

  return (
    <div
      className="page"
      style={{
        alignItems: 'center',
        justifyContent: 'center',
        background: 'radial-gradient(ellipse at 50% 40%, #110d1f 0%, var(--bg-primary) 70%)',
      }}
    >
      {/* Effet de fond */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: 'radial-gradient(circle at 50% 50%, rgba(124,58,237,0.06) 0%, transparent 60%)',
          pointerEvents: 'none',
        }}
      />

      <div
        className="animate-fade-in-scale"
        style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2rem', zIndex: 1 }}
      >
        {/* Logo */}
        <SyleaLogo size={140} animated />

        {/* Wordmark */}
        <div style={{ textAlign: 'center' }}>
          <h1
            style={{
              fontSize: '2.75rem',
              fontWeight: 700,
              letterSpacing: '0.12em',
              marginBottom: '0.25rem',
            }}
          >
            <span style={{ color: 'var(--accent-silver)' }}>S Y L É A</span>
            {'  '}
            <span style={{ color: 'var(--accent-gold)' }}>· A I</span>
          </h1>
          <div
            style={{
              height: '1px',
              background: 'linear-gradient(90deg, transparent, var(--accent-violet), transparent)',
              margin: '0.75rem auto',
              width: '200px',
            }}
          />
          <p style={{ color: 'var(--text-muted)', fontStyle: 'italic', fontSize: '0.95rem', letterSpacing: '0.04em' }}>
            Votre assistant de vie augmenté
          </p>
        </div>

        {/* Indicateur de chargement */}
        <div style={{ display: 'flex', gap: '6px', marginTop: '1rem' }}>
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              style={{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                background: 'var(--accent-violet)',
                opacity: 0.7,
                animation: `pulse 1.2s ${i * 0.2}s ease-in-out infinite`,
              }}
            />
          ))}
        </div>
      </div>

      <style>{`
        @keyframes pulse {
          0%, 80%, 100% { transform: scale(0.8); opacity: 0.4; }
          40% { transform: scale(1.2); opacity: 1; }
        }
      `}</style>
    </div>
  )
}
