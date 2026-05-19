// Page intermédiaire pour Sign in with Apple depuis l'app desktop Tauri.
//
// Flux :
//   1. Desktop ouvre cette URL dans le navigateur système :
//      https://sylea.ai/auth/apple-desktop?nonce=<NONCE>
//   2. On déclenche immédiatement appleLogin() (redirige vers appleid.apple.com)
//   3. Après authentification chez Apple, retour sur /auth/callback (form_post
//      converti en GET par le backend)
//   4. AuthCallbackPage récupère le JWT, puis détecte qu'on est dans le flux
//      "desktop" (state=desktop_apple_<NONCE>) et redirige vers
//      sylea://auth/callback?token=<JWT>&nonce=<NONCE>
//   5. macOS/Windows ouvre Syléa Desktop qui récupère le token via deep-link
//
// L'utilisateur voit donc :
//   App desktop → clic "Continuer avec Apple"
//   → Navigateur s'ouvre
//   → Auth Apple (Touch ID / Face ID si Safari sur Mac avec compte iCloud)
//   → "Retour vers l'application Syléa Desktop..." (cette page redirige)
//   → App desktop reprend, connecté

import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'

export default function AppleDesktopBridgePage() {
  const [searchParams] = useSearchParams()
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState('Préparation de Sign in with Apple…')

  useEffect(() => {
    // Sign in with Apple est masqué tant que les fonds Apple Developer
    // ne sont pas disponibles. Réactiver via VITE_APPLE_SIGNIN_ENABLED=true.
    if (import.meta.env.VITE_APPLE_SIGNIN_ENABLED !== 'true') {
      setError(
        "La connexion Apple n'est pas encore disponible. " +
          "Utilisez Google, GitHub ou e-mail pour vous connecter.",
      )
      return
    }

    const nonce = searchParams.get('nonce') || ''
    if (!nonce) {
      setError("Paramètre 'nonce' manquant — relancez depuis l'application desktop.")
      return
    }

    // Lance la redirection vers Apple avec un state qui encode le nonce desktop
    const redirectUri = `${window.location.origin}/auth/callback`
    const state = `desktop_apple_${nonce}`

    api
      .authAppleUrl(redirectUri, state)
      .then(({ url }) => {
        setStatus('Redirection vers Apple…')
        window.location.href = url
      })
      .catch((e: any) => {
        setError(e.message || 'Erreur initialisation Apple Sign-In')
      })
  }, [searchParams])

  if (error) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          background: '#030710',
          color: '#fff',
          flexDirection: 'column',
          gap: '1rem',
          padding: '2rem',
          textAlign: 'center',
        }}
      >
        <p style={{ color: '#ef4444', maxWidth: 480 }}>{error}</p>
        <button
          onClick={() => window.close()}
          style={{
            padding: '0.5rem 1.5rem',
            background: '#2563eb',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            cursor: 'pointer',
          }}
        >
          Fermer cette fenêtre
        </button>
      </div>
    )
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        background: '#030710',
        color: '#fff',
        flexDirection: 'column',
        gap: '1rem',
      }}
    >
      <p>{status}</p>
    </div>
  )
}
