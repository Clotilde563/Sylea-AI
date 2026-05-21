// Page de callback OAuth — traite le code d'autorisation Google / GitHub / Apple
// Supporte 4 flows :
//   1. Login Google (?code=...&state=login) → crée/connecte le compte
//   2. Login GitHub (?code=...&state=github_login) → crée/connecte le compte
//   3. Connexion intégration (?code=...&state=integration) → ajoute Calendar/Gmail/Drive
//   4. Login Apple (?code=...&state=apple_login + first_name/last_name optionnels)
//      Note : Apple redirige en POST form_post. Le backend doit le convertir en
//      GET avec query params avant d'arriver ici (route /api/auth/oauth/apple/callback).

import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuthStore } from '../auth/authStore'
import { api } from '../api/client'

export default function AuthCallbackPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const handleGoogleCallback = useAuthStore((s) => s.handleGoogleCallback)
  const handleGithubCallback = useAuthStore((s) => s.handleGithubCallback)
  const handleAppleCallback = useAuthStore((s) => s.handleAppleCallback)
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
          setStatus(`Connecté : ${res.services.join(', ')}`)
          setTimeout(() => navigate('/integrations'), 1500)
        })
        .catch((e: any) => {
          setError(e.message || 'Erreur connexion Google')
        })
    } else if (state === 'github_login') {
      // Flow 2: login/register with GitHub
      setStatus('Connexion à votre compte GitHub...')
      handleGithubCallback(code)
        .then(() => navigate('/'))
        .catch((e: any) => {
          setError(e.message || 'Erreur de connexion GitHub')
        })
    } else if (state === 'apple_login' || state.startsWith('apple_')) {
      // Flow 4 : login/register avec Apple
      // Le backend forward le form_post Apple en query params (sécurité : on
      // ne reçoit jamais le code Apple directement en form POST côté frontend).
      setStatus('Connexion à votre compte Apple...')
      const firstName = searchParams.get('first_name') || undefined
      const lastName = searchParams.get('last_name') || undefined

      handleAppleCallback(code, { firstName, lastName })
        .then(() => {
          // Si on est dans le flow desktop (state encode un nonce), on
          // redirige vers le scheme sylea:// pour réveiller l'app desktop.
          if (state.startsWith('desktop_apple_')) {
            const nonce = state.substring('desktop_apple_'.length)
            const token = localStorage.getItem('sylea_auth_token') || ''
            const deepLink = `sylea://auth/callback?token=${encodeURIComponent(token)}&nonce=${encodeURIComponent(nonce)}`
            setStatus("Retour vers l'application Syléa Desktop…")
            // window.location.href déclenche le scheme sur la plupart des
            // navigateurs ; en cas d'échec on affiche un message + bouton.
            setTimeout(() => {
              window.location.href = deepLink
              // Backup : afficher un bouton si le deep-link ne marche pas
              setTimeout(() => {
                setStatus(
                  "Si l'application ne s'ouvre pas automatiquement, " +
                    'cliquez sur "Ouvrir Syléa Desktop" ci-dessous.',
                )
              }, 1500)
            }, 200)
          } else {
            navigate('/')
          }
        })
        .catch((e: any) => {
          setError(e.message || 'Erreur de connexion Apple')
        })
    } else if (state.startsWith('desktop_google_')) {
      // Flow 5 : login/register Google depuis le desktop (deep-link return).
      //
      // Le state contient le nonce genere cote desktop. Apres echange du code
      // contre un JWT, on redirige le navigateur vers sylea://auth/callback
      // ?token=<JWT>&nonce=<NONCE> — le scheme handler reveille Syléa Desktop
      // qui recupere le token via le plugin deep-link.
      //
      // Symetrique a desktop_apple_ ci-dessus.
      setStatus('Connexion à votre compte Google…')
      const nonce = state.substring('desktop_google_'.length)
      handleGoogleCallback(code)
        .then(() => {
          const token = localStorage.getItem('sylea_auth_token') || ''
          const deepLink =
            `sylea://auth/callback?token=${encodeURIComponent(token)}` +
            `&nonce=${encodeURIComponent(nonce)}`
          setStatus("Retour vers l'application Syléa Desktop…")
          setTimeout(() => {
            window.location.href = deepLink
            // Backup : afficher un message si le deep-link ne marche pas
            setTimeout(() => {
              setStatus(
                "Si l'application Syléa Desktop ne s'ouvre pas automatiquement, " +
                  'revenez manuellement dans l\'app — votre session est active.',
              )
            }, 2000)
          }, 200)
        })
        .catch((e: any) => {
          setError(e.message || 'Erreur de connexion Google')
        })
    } else {
      // Flow 1: login/register with Google
      setStatus('Connexion à votre compte Google...')
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
