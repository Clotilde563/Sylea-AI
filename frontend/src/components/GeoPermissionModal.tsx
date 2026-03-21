// Modal bloquant demandant la permission de geolocalisation
import { useDeviceContext } from '../contexts/DeviceContext'
import { useStore } from '../store/useStore'
import { useT } from '../i18n/LanguageContext'

export function GeoPermissionModal() {
  const { geoDenied, loading, retryGeo, useFallbackCity } = useDeviceContext()
  const profil = useStore(s => s.profil)
  const t = useT()

  // Ne pas afficher si : pas de refus OU en chargement
  if (!geoDenied || loading) return null

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 10000,
      background: 'rgba(2,5,9,0.92)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      backdropFilter: 'blur(8px)',
    }}>
      <div style={{
        background: 'var(--bg-surface, #0d1117)',
        border: '1px solid var(--border, #1e293b)',
        borderRadius: '1rem',
        padding: '2.5rem 2rem',
        maxWidth: 440,
        width: '90%',
        textAlign: 'center',
        boxShadow: '0 0 40px rgba(124,58,237,0.15)',
      }}>
        {/* Icon */}
        <div style={{
          width: 64, height: 64, borderRadius: '50%', margin: '0 auto 1.5rem',
          background: 'linear-gradient(135deg, rgba(59,130,246,0.15), rgba(139,92,246,0.15))',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          border: '2px solid rgba(139,92,246,0.3)',
        }}>
          <svg width={28} height={28} viewBox="0 0 24 24" fill="none" stroke="#8b5cf6" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
            <circle cx="12" cy="10" r="3" />
          </svg>
        </div>

        <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary, #e8e8f0)', marginBottom: '0.75rem' }}>
          {t('common.geo_title') !== 'common.geo_title' ? t('common.geo_title') : 'Localisation requise'}
        </h3>

        <p style={{ fontSize: '0.85rem', color: 'var(--text-muted, #8b8b9e)', lineHeight: 1.6, marginBottom: '1.5rem' }}>
          {t('common.geo_desc') !== 'common.geo_desc'
            ? t('common.geo_desc')
            : "Sylea.AI a besoin de votre localisation, de l'heure et de la meteo pour fournir des analyses IA contextuelles et pertinentes."}
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <button
            onClick={retryGeo}
            style={{
              padding: '0.75rem 1.5rem',
              borderRadius: '0.5rem',
              background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
              color: 'white',
              border: 'none',
              fontWeight: 600,
              fontSize: '0.85rem',
              cursor: 'pointer',
              transition: 'opacity 0.15s',
            }}
          >
            Autoriser la localisation
          </button>

          {profil?.ville && (
            <button
              onClick={() => useFallbackCity(profil.ville)}
              style={{
                padding: '0.625rem 1.5rem',
                borderRadius: '0.5rem',
                background: 'transparent',
                color: 'var(--text-secondary, #a5a5b8)',
                border: '1px solid var(--border, #1e293b)',
                fontWeight: 500,
                fontSize: '0.8rem',
                cursor: 'pointer',
                transition: 'all 0.15s',
              }}
            >
              Utiliser ma ville ({profil.ville})
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
