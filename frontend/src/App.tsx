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
import { DesktopStatusBanner } from './components/DesktopStatusBanner'
import ParametresPage       from './pages/ParametresPage'
import AgentsPage           from './pages/AgentsPage'
import LoginPage            from './pages/LoginPage'
import { ProtectedRoute }   from './auth/ProtectedRoute'
import { LanguageProvider, useT } from './i18n/LanguageContext'
import LockScreen           from './security/LockScreen'
import { DeviceContextProvider } from './contexts/DeviceContext'
import { GeoPermissionModal }    from './components/GeoPermissionModal'
import { CookieBanner }     from './components/CookieBanner'
import PrivacyPolicyPage    from './pages/PrivacyPolicyPage'
import TermsPage            from './pages/TermsPage'
import HelpPage             from './pages/HelpPage'
import WorkspacePage        from './pages/WorkspacePage'
import CoachingPage         from './pages/CoachingPage'
import IntegrationsPage     from './pages/IntegrationsPage'
import NetworkPage          from './pages/NetworkPage'
import MarketplacePage      from './pages/MarketplacePage'
import OutilsPage           from './pages/OutilsPage'
import AuthCallbackPage     from './pages/AuthCallbackPage'
import QuotasPage           from './pages/QuotasPage'
import WorkspacesPage       from './pages/WorkspacesPage'
import { ToastProvider }    from './components/Toast'

// ── Application ───────────────────────────────────────────────────────────────

function AppContent() {
  // Skip splash if user is already authenticated (has valid JWT token)
  const hasToken = !!localStorage.getItem('sylea_auth_token')
  const [showSplash, setShowSplash] = useState(!hasToken)
  const [chatbotOpen, setChatbotOpen] = useState(false)
  const t = useT()

  return (
    <BrowserRouter>
      {/* Bandeau cookies RGPD */}
      <CookieBanner />
      {/* Verrouillage securite */}
      <LockScreen />
      {/* Animation d'intro Syléa — 8s, plein écran, au-dessus de tout */}
      {showSplash && <SyleaSplash onDone={() => setShowSplash(false)} />}

      <Routes>
        {/* Routes publiques */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/auth/callback" element={<AuthCallbackPage />} />
        <Route path="/privacy" element={<PrivacyPolicyPage />} />
        <Route path="/terms" element={<TermsPage />} />
        <Route path="/help" element={<HelpPage />} />

        {/* Route splash legacy (navigation directe à /splash) */}
        <Route path="/splash" element={<SplashPage />} />

        {/* Routes protegees — authentification requise */}
        <Route element={<ProtectedRoute />}>
          <Route
            path="/*"
            element={
              <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
                <NavBar onOpenChatbot={() => setChatbotOpen(true)} />
                {/* Phase 2c — bandeau pont desktop <-> web (vert si OK, rouge sinon) */}
                <DesktopStatusBanner />
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
                    <Route path="/workspace"    element={<WorkspacePage />} />                    <Route path="/coaching"     element={<CoachingPage />} />
                    <Route path="/integrations" element={<IntegrationsPage />} />
                    {/* Backward-compat: /credentials → onglet "Clés API" de Intégrations */}
                    <Route path="/credentials"  element={<Navigate to="/integrations?tab=credentials" replace />} />
                    <Route path="/network"      element={<NetworkPage />} />
                    <Route path="/marketplace"  element={<MarketplacePage />} />
                    <Route path="/outils"       element={<OutilsPage />} />
                    {/* Phase 10/11 */}
                    <Route path="/quotas"         element={<QuotasPage />} />
                    <Route path="/workspaces"     element={<WorkspacesPage />} />
                    {/* Backward-compat: /api-keys → onglet "Tokens API B2B" de Intégrations */}
                    <Route path="/api-keys"       element={<Navigate to="/integrations?tab=tokens" replace />} />
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
                  <span style={{ marginLeft: '1.5rem' }}>
                    <a href="/privacy" style={{ color: 'var(--text-muted)', textDecoration: 'none', marginRight: '0.75rem' }}>
                      Confidentialite
                    </a>
                    <a href="/terms" style={{ color: 'var(--text-muted)', textDecoration: 'none' }}>
                      CGU
                    </a>
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
        <ToastProvider>
          <GeoPermissionModal />
          <AppContent />
        </ToastProvider>
      </DeviceContextProvider>
    </LanguageProvider>
  )
}

