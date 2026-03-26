// Bandeau de consentement RGPD — cookies

import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'

const LS_KEY = 'sylea_cookies_accepted'

interface CookiePrefs {
  essential: boolean
  analytics: boolean
  personalization: boolean
  date: string
}

export function CookieBanner() {
  const [visible, setVisible] = useState(false)
  const [analytics, setAnalytics] = useState(false)
  const [personalization, setPersonalization] = useState(false)

  useEffect(() => {
    const saved = localStorage.getItem(LS_KEY)
    if (!saved) setVisible(true)
  }, [])

  if (!visible) return null

  const save = (prefs: CookiePrefs) => {
    localStorage.setItem(LS_KEY, JSON.stringify(prefs))
    setVisible(false)
  }

  const acceptAll = () => save({
    essential: true, analytics: true, personalization: true,
    date: new Date().toISOString().slice(0, 10),
  })

  const acceptSelection = () => save({
    essential: true, analytics, personalization,
    date: new Date().toISOString().slice(0, 10),
  })

  const refuseAll = () => save({
    essential: true, analytics: false, personalization: false,
    date: new Date().toISOString().slice(0, 10),
  })

  return (
    <>
      <style>{`
        @keyframes cookie-slide-up {
          from { transform: translateY(100%); opacity: 0 }
          to   { transform: translateY(0); opacity: 1 }
        }
      `}</style>
      <div style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 10000,
        animation: 'cookie-slide-up 0.4s cubic-bezier(0.16,1,0.3,1) forwards',
      }}>
        <div style={{
          maxWidth: 640,
          margin: '0 auto 1rem',
          background: 'rgba(6, 12, 26, 0.97)',
          backdropFilter: 'blur(20px)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: '0 -4px 40px rgba(0,0,0,0.6)',
          padding: '1.5rem',
        }}>
          {/* Title */}
          <div style={{
            fontSize: '0.95rem', fontWeight: 700,
            color: 'var(--text-primary)', marginBottom: '0.75rem',
            display: 'flex', alignItems: 'center', gap: '0.5rem',
          }}>
            <span style={{ fontSize: '1.1rem' }}>&#x1F36A;</span>
            Ce site utilise des cookies
          </div>

          {/* Description */}
          <p style={{
            fontSize: '0.8rem', color: 'var(--text-secondary)',
            lineHeight: 1.6, margin: '0 0 1rem',
          }}>
            Nous utilisons des cookies essentiels pour le fonctionnement de l'application
            et des cookies analytiques pour ameliorer votre experience.
          </p>

          {/* Checkboxes */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', marginBottom: '1.25rem' }}>
            <CheckRow label="Cookies essentiels (obligatoires)" checked disabled />
            <CheckRow label="Cookies analytiques" checked={analytics} onChange={() => setAnalytics(!analytics)} />
            <CheckRow label="Cookies de personnalisation" checked={personalization} onChange={() => setPersonalization(!personalization)} />
          </div>

          {/* Buttons */}
          <div style={{
            display: 'flex', gap: '0.6rem', flexWrap: 'wrap',
          }}>
            <button onClick={acceptAll} className="btn btn-primary" style={{
              fontSize: '0.78rem', padding: '0.55rem 1.1rem', flex: 1,
            }}>
              Tout accepter
            </button>
            <button onClick={acceptSelection} className="btn btn-outline" style={{
              fontSize: '0.78rem', padding: '0.55rem 1.1rem', flex: 1,
            }}>
              Accepter la selection
            </button>
            <button onClick={refuseAll} className="btn btn-outline" style={{
              fontSize: '0.78rem', padding: '0.55rem 1.1rem', flex: 1,
              color: 'var(--text-muted)', borderColor: 'var(--border)',
            }}>
              Tout refuser
            </button>
          </div>

          {/* Link to privacy */}
          <div style={{ marginTop: '0.75rem', textAlign: 'center' }}>
            <Link to="/privacy" style={{
              fontSize: '0.72rem', color: 'var(--accent-violet-light)',
              textDecoration: 'underline',
            }}>
              Politique de confidentialite
            </Link>
          </div>
        </div>
      </div>
    </>
  )
}

function CheckRow({ label, checked, disabled, onChange }: {
  label: string; checked: boolean; disabled?: boolean; onChange?: () => void
}) {
  return (
    <label style={{
      display: 'flex', alignItems: 'center', gap: '0.6rem',
      fontSize: '0.82rem', color: disabled ? 'var(--text-muted)' : 'var(--text-primary)',
      cursor: disabled ? 'default' : 'pointer',
    }}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={onChange}
        style={{
          width: 16, height: 16, accentColor: 'var(--accent-violet)',
          cursor: disabled ? 'default' : 'pointer',
        }}
      />
      {label}
    </label>
  )
}
