// Application principale Syléa.AI — Router + Layout + Intro animée

import { useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { NavBar }            from './components/NavBar'
import { SyleaSplash }       from './components/SyleaSplash'
import { SplashPage }        from './pages/SplashPage'
import { DashboardPage }     from './pages/DashboardPage'
import { ProfilWizardPage }  from './pages/ProfilWizardPage'
import { DilemmePage }       from './pages/DilemmePage'
import { StatistiquesPage }  from './pages/StatistiquesPage'
import { EvenementPage }    from './pages/EvenementPage'
import { BilanPage }        from './pages/BilanPage'

// ── Application ───────────────────────────────────────────────────────────────

export default function App() {
  // true = affiche l'animation au lancement | false = désactivé
  const [showSplash, setShowSplash] = useState(true)

  return (
    <BrowserRouter>
      {/* Animation d'intro Syléa — 8s, plein écran, au-dessus de tout */}
      {showSplash && <SyleaSplash onDone={() => setShowSplash(false)} />}

      <Routes>
        {/* Route splash legacy (navigation directe à /splash) */}
        <Route path="/splash" element={<SplashPage />} />

        {/* Pages avec navbar */}
        <Route
          path="/*"
          element={
            <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
              <NavBar />
              <main style={{ flex: 1 }}>
                <Routes>
                  <Route path="/"             element={<DashboardPage />} />
                  <Route path="/profil"       element={<ProfilWizardPage />} />
                  <Route path="/dilemme"      element={<DilemmePage />} />
                  <Route path="/statistiques" element={<StatistiquesPage />} />
                  <Route path="/evenement"    element={<EvenementPage />} />
                  <Route path="/bilan"        element={<BilanPage />} />
                  <Route path="*"             element={<Navigate to="/" replace />} />
                </Routes>
              </main>

              {/* Footer */}
              <footer
                style={{
                  borderTop: '1px solid var(--border)',
                  padding: '0.875rem 0',
                  textAlign: 'center',
                  fontSize: '0.75rem',
                  color: 'var(--text-muted)',
                  letterSpacing: '0.06em',
                }}
              >
                <span style={{ color: 'var(--accent-silver)', fontWeight: 700, letterSpacing: '0.12em' }}>
                  SYLÉA
                </span>
                <span style={{ color: 'var(--accent-violet-light)' }}>.AI</span>
                <span style={{ marginLeft: '1rem', letterSpacing: '0.02em' }}>
                  Votre assistant de vie augmenté
                </span>
              </footer>
            </div>
          }
        />
      </Routes>
    </BrowserRouter>
  )
}

// ── VideoSplash conservée pour usage futur (animation syléa.mp4) ──────────────
/*
function VideoSplash({ onDone }: { onDone: () => void }) {
  return (
    <div style={{ position: 'fixed', inset: 0, background: '#000', zIndex: 9999, overflow: 'hidden' }}>
      <video src="/animation-sylea.mp4" autoPlay muted playsInline onEnded={onDone}
        style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
      <div style={{ position: 'absolute', top: 0, right: 0, width: '180px', height: '55px',
        background: '#000', pointerEvents: 'none' }} />
      <button onClick={onDone} style={{ position: 'absolute', bottom: '2.5rem', right: '2.5rem',
        background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.18)',
        color: 'rgba(255,255,255,0.6)', padding: '0.45rem 1.4rem', borderRadius: '3px',
        cursor: 'pointer', fontSize: '0.72rem', letterSpacing: '0.15em' }}>
        PASSER ›
      </button>
    </div>
  )
}
*/
