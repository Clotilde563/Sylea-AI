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
import { HistoriquePage }   from './pages/HistoriquePage'
import { ServiceChatbot }   from './components/ServiceChatbot'
import ParametresPage       from './pages/ParametresPage'
import AgentsPage           from './pages/AgentsPage'
import LoginPage            from './pages/LoginPage'
import { ProtectedRoute }   from './auth/ProtectedRoute'
import { LanguageProvider, useT } from './i18n/LanguageContext'
import LockScreen           from './security/LockScreen'
import { DeviceContextProvider } from './contexts/DeviceContext'
import { GeoPermissionModal }    from './components/GeoPermissionModal'

// ── Application ───────────────────────────────────────────────────────────────

function AppContent() {
  // Skip splash if user is already authenticated (has valid JWT token)
  const hasToken = !!localStorage.getItem('sylea_auth_token')
  const [showSplash, setShowSplash] = useState(!hasToken)
  const [chatbotOpen, setChatbotOpen] = useState(false)
  const t = useT()

  return (
    <BrowserRouter>
      {/* Verrouillage securite */}
      <LockScreen />
      {/* Animation d'intro Syléa — 8s, plein écran, au-dessus de tout */}
      {showSplash && <SyleaSplash onDone={() => setShowSplash(false)} />}

      <Routes>
        {/* Route publique — connexion */}
        <Route path="/login" element={<LoginPage />} />

        {/* Route splash legacy (navigation directe à /splash) */}
        <Route path="/splash" element={<SplashPage />} />

        {/* Routes protegees — authentification requise */}
        <Route element={<ProtectedRoute />}>
          <Route
            path="/*"
            element={
              <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
                <NavBar onOpenChatbot={() => setChatbotOpen(true)} />
                <main style={{ flex: 1 }}>
                  <Routes>
                    <Route path="/"             element={<DashboardPage />} />
                    <Route path="/profil"       element={<ProfilWizardPage />} />
                    <Route path="/dilemme"      element={<DilemmePage />} />
                    <Route path="/statistiques" element={<StatistiquesPage />} />
                    <Route path="/historique"   element={<HistoriquePage />} />
                    <Route path="/evenement"    element={<EvenementPage />} />
                    <Route path="/bilan"        element={<BilanPage />} />
                    <Route path="/parametres"   element={<ParametresPage />} />
                    <Route path="/agents"       element={<AgentsPage />} />
                    <Route path="*"             element={<Navigate to="/" replace />} />
                  </Routes>
                </main>
                <ServiceChatbot visible={chatbotOpen} onClose={() => setChatbotOpen(false)} />

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
                    SYLEA
                  </span>
                  <span style={{ color: 'var(--accent-violet-light)' }}>.AI</span>
                  <span style={{ marginLeft: '1rem', letterSpacing: '0.02em' }}>
                    {t('common.votre_assistant')}
                  </span>
                </footer>
              </div>
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default function App() {
  return (
    <LanguageProvider>
      <DeviceContextProvider>
        <GeoPermissionModal />
        <AppContent />
      </DeviceContextProvider>
    </LanguageProvider>
  )
}

