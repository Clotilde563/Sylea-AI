// Error Boundary — Syléa.AI
//
// Fix P3 (2026-06) : aucun Error Boundary dans l'app → une seule exception de
// rendu dans n'importe quel composant (ex: AgentsPage 8400 lignes, parseActions,
// un champ manquant dans un event stream) crashait TOUTE l'app en écran blanc.
//
// Ce boundary attrape l'erreur, affiche un fallback propre + un bouton "Recharger",
// et logge l'erreur (sans exposer la stack à l'utilisateur).

import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  message: string
}

export class RouteErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, message: '' }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error?.message || 'Erreur inattendue' }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Log technique (console + télémétrie éventuelle). On NE montre PAS la
    // stack à l'utilisateur (fuite d'infos internes).
    // eslint-disable-next-line no-console
    console.error('[RouteErrorBoundary]', error, info?.componentStack)
  }

  private handleReload = () => {
    // Reset l'état puis recharge la page courante (le boundary se ré-arme).
    this.setState({ hasError: false, message: '' })
    try { window.location.reload() } catch { /* noop */ }
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div
        role="alert"
        style={{
          minHeight: '60vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '1rem',
          padding: '2rem',
          textAlign: 'center',
        }}
      >
        <div style={{ fontSize: '2.5rem' }}>⚠️</div>
        <h2 style={{ margin: 0, color: 'var(--text-primary, #e8e8f0)' }}>
          Oups, quelque chose s'est mal passé
        </h2>
        <p style={{ color: 'var(--text-muted, #94a3b8)', maxWidth: 480, lineHeight: 1.6 }}>
          Cette page a rencontré une erreur inattendue. Le reste de l'application
          reste accessible. Tu peux recharger pour réessayer.
        </p>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button
            type="button"
            onClick={this.handleReload}
            style={{
              padding: '0.6rem 1.2rem',
              borderRadius: '10px',
              border: 'none',
              background: 'linear-gradient(135deg, #5520b8, #1848d8, #00c8ff)',
              color: '#fff',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Recharger
          </button>
          <button
            type="button"
            onClick={() => { try { window.location.href = '/' } catch { /* noop */ } }}
            style={{
              padding: '0.6rem 1.2rem',
              borderRadius: '10px',
              border: '1px solid var(--border, rgba(255,255,255,0.12))',
              background: 'transparent',
              color: 'var(--text-secondary, #cbd5e1)',
              cursor: 'pointer',
            }}
          >
            Tableau de bord
          </button>
        </div>
      </div>
    )
  }
}

export default RouteErrorBoundary
