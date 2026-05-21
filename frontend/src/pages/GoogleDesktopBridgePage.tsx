// Page intermediaire pour Sign in with Google depuis l'app desktop Tauri.
//
// Flux complet (cf. apiClient.ts + AuthCallbackPage + main.rs deep-link handler) :
//   1. Desktop genere un nonce aleatoire, le stocke en localStorage interne,
//      et ouvre dans le navigateur systeme :
//        http://localhost:5173/auth/google-desktop?nonce=<NONCE>
//      (en prod : https://sylea.ai/auth/google-desktop?nonce=<NONCE>)
//   2. Cette page recupere le nonce, demande l'URL Google OAuth au backend
//      avec state=desktop_google_<NONCE>, puis redirige le navigateur.
//   3. Apres authentification chez Google, retour sur /auth/callback?code=...
//      &state=desktop_google_<NONCE>
//   4. AuthCallbackPage echange le code contre un JWT via POST /api/auth/oauth/google,
//      puis (parce que le state commence par desktop_google_) redirige le
//      navigateur vers sylea://auth/callback?token=<JWT>&nonce=<NONCE>
//   5. Le scheme handler Windows/macOS/Linux ouvre Sylea Desktop, qui via le
//      plugin tauri-plugin-deep-link emet l'evenement 'deep-link:received'
//      avec l'URL complete.
//   6. Le listener dans desktop/src/App.tsx parse le token, verifie le nonce
//      contre celui stocke au depart, et setToken(jwt) → l'user est connecte.
//
// Pourquoi un nonce ?
//   - Securite : empeche un attaquant qui devine l'URL deep-link de forger un
//     login. Le nonce est genere cote desktop, jamais transmis a Google, et
//     verifie au retour. Si nonce mismatch → on rejette le token.
//   - Symetrique au flow Apple existant (AppleDesktopBridgePage.tsx).

import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'

export default function GoogleDesktopBridgePage() {
  const [searchParams] = useSearchParams()
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState('Préparation de la connexion Google…')

  useEffect(() => {
    const nonce = searchParams.get('nonce') || ''
    if (!nonce) {
      setError("Paramètre 'nonce' manquant — relancez depuis l'application desktop.")
      return
    }

    // Lance la redirection vers Google avec un state qui encode le nonce desktop
    const redirectUri = `${window.location.origin}/auth/callback`
    const state = `desktop_google_${nonce}`

    api
      .authGoogleUrl(redirectUri, state)
      .then(({ url }) => {
        setStatus('Redirection vers Google…')
        window.location.href = url
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : 'Erreur initialisation Google OAuth'
        setError(msg)
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
