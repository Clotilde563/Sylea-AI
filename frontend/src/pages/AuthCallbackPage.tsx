// Page de callback OAuth — traite le code d'autorisation Google / GitHub
// Supporte 3 flows :
//   1. Login Google (?code=...&state=login) → crée/connecte le compte
//   2. Login GitHub (?code=...&state=github_login) → crée/connecte le compte
//   3. Connexion intégration (?code=...&state=integration) → ajoute Calendar/Gmail/Drive

import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuthStore } from '../auth/authStore'
import { api } from '../api/client'

export default function AuthCallbackPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const handleGoogleCallback = useAuthStore((s) => s.handleGoogleCallback)
  const handleGithubCallback = useAuthStore((s) => s.handleGithubCallback)
  const token = useAuthStore((s) => s.token)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState('Connexion en cours...')

  // Guard against React Strict Mode double-invoke (code is single-use)
  const processed = useRef(false)

  useEffect(() => {
    if (processed.current) return
    processed.current = true

    const code = searchParams.get('code')
    const state = searchParams.get('state') || 'login'

    if (!code) {
      setError("Code d'autorisation manquant")
      return
    }

    if (state === 'integration' && token) {
      // Flow 3: user is already logged in, just connecting Google integrations
      setStatus('Connexion de Google Calendar, Gmail et Drive...')
      const redirectUri = `${window.location.origin}/auth/callback`
      api.connectGoogleOAuth(code, redirectUri)
        .then((res) => {
          setStatus(`Connecte : ${res.services.join(', ')}`)
          setTimeout(() => navigate('/integrations'), 1500)
        })
        .catch((e: any) => {
          setError(e.message || 'Erreur connexion Google')
        })
    } else if (state === 'github_login') {
      // Flow 2: login/register with GitHub
      setStatus('Connexion a votre compte GitHub...')
      handleGithubCallback(code)
        .then(() => navigate('/'))
        .catch((e: any) => {
          setError(e.message || 'Erreur de connexion GitHub')
        })
    } else {
      // Flow 1: login/register with Google
      setStatus('Connexion a votre compte Google...')
      handleGoogleCallback(code)
        .then(() => navigate('/'))
        .catch((e: any) => {
          setError(e.message || 'Erreur de connexion Google')
        })
    }
  }, [])

  if (error) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', background: '#030710', color: '#fff', flexDirection: 'column', gap: '1rem' }}>
        <p style={{ color: '#ef4444' }}>{error}</p>
        <button onClick={() => navigate(token ? '/integrations' : '/login')} style={{ padding: '0.5rem 1.5rem', background: '#2563eb', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer' }}>
          {token ? 'Retour aux integrations' : 'Retour a la connexion'}
        </button>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', background: '#030710', color: '#fff' }}>
      <p>{status}</p>
    </div>
  )
}
