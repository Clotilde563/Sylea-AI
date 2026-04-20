/**
 * OpenClawOnboarding.tsx — Wizard d'installation du moteur AI OpenClaw.
 *
 * Affiche au 1er lancement de Sylea Agent, tant que `is_onboarded()`
 * retourne false. Guide l'utilisateur en 5 etapes :
 *
 *   1. Verification Node.js (pre-requis)
 *   2. Installation d'OpenClaw via `npm install -g openclaw@latest`
 *   3. Generation automatique du token gateway
 *   4. Selection des 5 skills ClawHub pre-coches
 *   5. Synthese "pret a utiliser"
 *
 * Communique avec le backend Rust via `invoke` (commandes Tauri) et
 * ecoute les evenements de streaming pour afficher les logs en temps reel.
 */

import { useEffect, useRef, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'

// ── Types ──────────────────────────────────────────────────────────────────

type WizardStep = 'welcome' | 'install' | 'token' | 'skills' | 'done' | 'node-missing'

interface ClawHubSkill {
  slug: string
  name: string
  emoji: string
  description: string
  preselected: boolean
}

// ── Catalogue des 5 skills pre-selectionnes ────────────────────────────────
// Slugs reels validees contre `openclaw skills search <mot-cle>` (avr. 2026).
// Selection curee : utilitaires quotidiens couvrant les 5 "piliers" d'une
// vie pro (calendrier, email, notes, communication, taches).
// NOTE : les slugs ci-dessous correspondent a des skills publies sur le
// marketplace ClawHub — `openclaw skills install <slug>` les telecharge
// et les place dans ~/.openclaw/skills/<slug>/.

const CURATED_SKILLS: ClawHubSkill[] = [
  {
    slug: 'gws-calendar-agenda',
    name: 'Google Calendar',
    emoji: '📅',
    description: 'Lister et consulter vos evenements Google Calendar a venir',
    preselected: true,
  },
  {
    slug: 'gmail',
    name: 'Gmail',
    emoji: '📧',
    description: 'Lire, rediger et gerer vos emails Gmail via l\'API managee',
    preselected: true,
  },
  {
    slug: 'notion',
    name: 'Notion',
    emoji: '📓',
    description: 'Creer et gerer pages, bases de donnees et blocs Notion',
    preselected: true,
  },
  {
    slug: 'slack',
    name: 'Slack',
    emoji: '💬',
    description: 'Envoyer des messages et reagir dans vos canaux Slack',
    preselected: true,
  },
  {
    slug: 'todoist-cli',
    name: 'Todoist',
    emoji: '✅',
    description: 'Gerer vos taches, projets et labels Todoist en CLI',
    preselected: true,
  },
]

// ── Composant principal ────────────────────────────────────────────────────

interface OpenClawOnboardingProps {
  onComplete: () => void
}

export default function OpenClawOnboarding({ onComplete }: OpenClawOnboardingProps) {
  // ── State global du wizard ───────────────────────────────────────────────
  const [step, setStep] = useState<WizardStep>('welcome')
  const [nodeVersion, setNodeVersion] = useState<string | null>(null)
  const [npmVersion, setNpmVersion] = useState<string | null>(null)
  const [openclawVersion, setOpenclawVersion] = useState<string | null>(null)

  // ── State installation OpenClaw ──────────────────────────────────────────
  const [installLogs, setInstallLogs] = useState<string[]>([])
  const [installStatus, setInstallStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [installError, setInstallError] = useState<string | null>(null)
  const installLogsRef = useRef<HTMLDivElement | null>(null)

  // ── State generation token ───────────────────────────────────────────────
  const [gatewayToken, setGatewayToken] = useState<string | null>(null)
  const [tokenStatus, setTokenStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle')

  // ── State installation skills ClawHub ────────────────────────────────────
  const [selectedSlugs, setSelectedSlugs] = useState<Set<string>>(
    new Set(CURATED_SKILLS.filter((s) => s.preselected).map((s) => s.slug))
  )
  const [skillInstallProgress, setSkillInstallProgress] = useState<
    Record<string, 'idle' | 'running' | 'done' | 'error'>
  >({})
  const [skillInstallError, setSkillInstallError] = useState<Record<string, string>>({})
  const [skillLogs, setSkillLogs] = useState<string[]>([])
  const skillLogsRef = useRef<HTMLDivElement | null>(null)

  // ── Etape 1 : Verif Node.js au montage ───────────────────────────────────
  useEffect(() => {
    (async () => {
      try {
        const node = await invoke<string>('check_node_installed')
        setNodeVersion(node)
        try {
          const npm = await invoke<string>('check_npm_installed')
          setNpmVersion(npm)
        } catch {
          setNpmVersion(null)
        }
        // Aussi : verifier si OpenClaw est deja la (reinstallation / mise a jour)
        try {
          const ocv = await invoke<string>('check_openclaw_installed')
          setOpenclawVersion(ocv)
        } catch {
          setOpenclawVersion(null)
        }
      } catch (err) {
        // Node.js absent — ecran dedie pour inviter l'utilisateur a l'installer
        setStep('node-missing')
      }
    })()
  }, [])

  // ── Ecoute des evenements d'installation OpenClaw ────────────────────────
  useEffect(() => {
    let unlistenLog: UnlistenFn | null = null
    let unlistenDone: UnlistenFn | null = null
    let unlistenError: UnlistenFn | null = null

    ;(async () => {
      unlistenLog = await listen<string>('openclaw:install:log', (event) => {
        setInstallLogs((prev) => [...prev, event.payload])
        // Autoscroll
        requestAnimationFrame(() => {
          if (installLogsRef.current) {
            installLogsRef.current.scrollTop = installLogsRef.current.scrollHeight
          }
        })
      })
      unlistenDone = await listen<string>('openclaw:install:done', () => {
        setInstallStatus('done')
        // Apres l'install, revalider la version
        invoke<string>('check_openclaw_installed')
          .then((v) => setOpenclawVersion(v))
          .catch(() => {})
      })
      unlistenError = await listen<string>('openclaw:install:error', (event) => {
        setInstallStatus('error')
        setInstallError(event.payload)
      })
    })()

    return () => {
      unlistenLog?.()
      unlistenDone?.()
      unlistenError?.()
    }
  }, [])

  // ── Ecoute des evenements d'installation ClawHub ─────────────────────────
  useEffect(() => {
    let unlistenLog: UnlistenFn | null = null
    let unlistenDone: UnlistenFn | null = null
    let unlistenError: UnlistenFn | null = null

    ;(async () => {
      unlistenLog = await listen<string>('clawhub:install:log', (event) => {
        setSkillLogs((prev) => [...prev, event.payload])
        requestAnimationFrame(() => {
          if (skillLogsRef.current) {
            skillLogsRef.current.scrollTop = skillLogsRef.current.scrollHeight
          }
        })
      })
      unlistenDone = await listen<{ slug: string }>('clawhub:install:done', (event) => {
        setSkillInstallProgress((prev) => ({
          ...prev,
          [event.payload.slug]: 'done',
        }))
      })
      unlistenError = await listen<{ slug: string; error: string }>(
        'clawhub:install:error',
        (event) => {
          setSkillInstallProgress((prev) => ({
            ...prev,
            [event.payload.slug]: 'error',
          }))
          setSkillInstallError((prev) => ({
            ...prev,
            [event.payload.slug]: event.payload.error,
          }))
        }
      )
    })()

    return () => {
      unlistenLog?.()
      unlistenDone?.()
      unlistenError?.()
    }
  }, [])

  // ── Actions du wizard ────────────────────────────────────────────────────

  const startInstallOpenClaw = async () => {
    if (openclawVersion) {
      // Deja installe → sauter a l'etape suivante
      setInstallStatus('done')
      return
    }
    setInstallStatus('running')
    setInstallLogs([])
    setInstallError(null)
    try {
      await invoke('install_openclaw')
    } catch (err) {
      setInstallStatus('error')
      setInstallError(String(err))
    }
  }

  const generateToken = async () => {
    setTokenStatus('running')
    try {
      const token = await invoke<string>('generate_gateway_token')
      setGatewayToken(token)
      setTokenStatus('done')
    } catch (err) {
      setTokenStatus('error')
      console.error('Erreur generation token:', err)
    }
  }

  const toggleSkill = (slug: string) => {
    setSelectedSlugs((prev) => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })
  }

  const selectAll = () => {
    setSelectedSlugs(new Set(CURATED_SKILLS.map((s) => s.slug)))
  }

  const deselectAll = () => {
    setSelectedSlugs(new Set())
  }

  const installSelectedSkills = async () => {
    const slugs = Array.from(selectedSlugs)
    if (slugs.length === 0) {
      // Rien a installer — passer directement a la fin
      setStep('done')
      return
    }
    setSkillLogs([])
    // Reset le statut pour les skills selectionnes
    const initial: Record<string, 'running' | 'done' | 'error'> = {}
    for (const slug of slugs) initial[slug] = 'running'
    setSkillInstallProgress(initial)

    // Installation sequentielle pour eviter les conflits npm
    for (const slug of slugs) {
      try {
        await invoke('install_clawhub_skill', { slug })
        // Attendre l'evenement :done ou :error (ou timeout 60s)
        await new Promise<void>((resolve) => {
          const checkInterval = setInterval(() => {
            setSkillInstallProgress((prev) => {
              const status = prev[slug]
              if (status === 'done' || status === 'error') {
                clearInterval(checkInterval)
                resolve()
              }
              return prev
            })
          }, 200)
          // Timeout fail-safe
          setTimeout(() => {
            clearInterval(checkInterval)
            resolve()
          }, 60_000)
        })
      } catch (err) {
        setSkillInstallProgress((prev) => ({ ...prev, [slug]: 'error' }))
        setSkillInstallError((prev) => ({ ...prev, [slug]: String(err) }))
      }
    }
  }

  const finishOnboarding = async () => {
    try {
      const installedSlugs = Object.entries(skillInstallProgress)
        .filter(([_, status]) => status === 'done')
        .map(([slug]) => slug)
      await invoke('mark_onboarded', { skills: installedSlugs })
      onComplete()
    } catch (err) {
      console.error('Erreur mark_onboarded:', err)
      // Ne pas bloquer : on laisse passer l'utilisateur quand meme
      onComplete()
    }
  }

  // ── Styles partages ──────────────────────────────────────────────────────

  const containerStyle: React.CSSProperties = {
    position: 'fixed',
    inset: 0,
    background: 'linear-gradient(135deg, #0a0e27 0%, #151938 50%, #1a1240 100%)',
    color: '#e5e7eb',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    padding: '24px',
    overflowY: 'auto',
    zIndex: 10_000,
  }

  const cardStyle: React.CSSProperties = {
    maxWidth: 640,
    margin: '0 auto',
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid rgba(168,139,255,0.18)',
    borderRadius: 16,
    padding: '32px',
    boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
  }

  const titleStyle: React.CSSProperties = {
    fontSize: 24,
    fontWeight: 700,
    marginBottom: 8,
    background: 'linear-gradient(90deg, #60a5fa, #a78bfa)',
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
    backgroundClip: 'text',
  }

  const subtitleStyle: React.CSSProperties = {
    fontSize: 14,
    color: '#9ca3af',
    marginBottom: 28,
    lineHeight: 1.6,
  }

  const primaryButton: React.CSSProperties = {
    background: 'linear-gradient(90deg, #6366f1, #a78bfa)',
    color: '#fff',
    border: 'none',
    padding: '12px 24px',
    borderRadius: 10,
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
    transition: 'transform 0.15s, opacity 0.15s',
  }

  const secondaryButton: React.CSSProperties = {
    background: 'transparent',
    color: '#9ca3af',
    border: '1px solid rgba(255,255,255,0.15)',
    padding: '10px 20px',
    borderRadius: 10,
    fontSize: 13,
    cursor: 'pointer',
  }

  const progressPillStyle = (active: boolean, done: boolean): React.CSSProperties => ({
    padding: '4px 10px',
    borderRadius: 999,
    fontSize: 11,
    fontWeight: 600,
    background: done
      ? 'rgba(74,222,128,0.15)'
      : active
      ? 'rgba(99,102,241,0.25)'
      : 'rgba(255,255,255,0.05)',
    color: done ? '#4ade80' : active ? '#a78bfa' : '#6b7280',
    border: done
      ? '1px solid rgba(74,222,128,0.4)'
      : active
      ? '1px solid rgba(167,139,250,0.5)'
      : '1px solid rgba(255,255,255,0.08)',
  })

  // ── Rendu : barre de progression ─────────────────────────────────────────

  const STEPS_ORDER: Array<{ key: WizardStep; label: string }> = [
    { key: 'welcome', label: '1. Systeme' },
    { key: 'install', label: '2. OpenClaw' },
    { key: 'token', label: '3. Gateway' },
    { key: 'skills', label: '4. Skills' },
    { key: 'done', label: '5. Pret' },
  ]

  const currentStepIndex = STEPS_ORDER.findIndex((s) => s.key === step)

  const renderProgressBar = () => (
    <div style={{ display: 'flex', gap: 8, marginBottom: 24, flexWrap: 'wrap' }}>
      {STEPS_ORDER.map((s, i) => (
        <span
          key={s.key}
          style={progressPillStyle(i === currentStepIndex, i < currentStepIndex)}
        >
          {s.label}
        </span>
      ))}
    </div>
  )

  // ══════════════════════════════════════════════════════════════════════════
  //  Rendu des ecrans
  // ══════════════════════════════════════════════════════════════════════════

  // ── Ecran special : Node.js manquant ─────────────────────────────────────
  if (step === 'node-missing') {
    return (
      <div style={containerStyle}>
        <div style={cardStyle}>
          <div style={titleStyle}>Node.js requis</div>
          <div style={subtitleStyle}>
            Sylea Agent a besoin de Node.js pour faire tourner son moteur AI
            OpenClaw. Veuillez installer Node.js 18+ puis relancer
            l'application.
          </div>
          <div
            style={{
              background: 'rgba(245,158,11,0.08)',
              border: '1px solid rgba(245,158,11,0.3)',
              borderRadius: 10,
              padding: 14,
              marginBottom: 20,
              fontSize: 13,
              color: '#fbbf24',
            }}
          >
            ⚠ Node.js n'est pas detecte dans votre PATH systeme.
          </div>
          <a
            href="https://nodejs.org/fr/download/"
            target="_blank"
            rel="noreferrer"
            style={{ ...primaryButton, display: 'inline-block', textDecoration: 'none' }}
          >
            Telecharger Node.js (gratuit, 45 Mo)
          </a>
          <div style={{ marginTop: 16, fontSize: 12, color: '#6b7280' }}>
            Installation facile en 2 min. Relancez Sylea Agent ensuite —
            nous detecterons Node automatiquement.
          </div>
        </div>
      </div>
    )
  }

  // ── Ecran 1 : Bienvenue + verif systeme ──────────────────────────────────
  if (step === 'welcome') {
    return (
      <div style={containerStyle}>
        <div style={cardStyle}>
          {renderProgressBar()}
          <div style={titleStyle}>Bienvenue dans Sylea Agent</div>
          <div style={subtitleStyle}>
            Pour que Syléa fonctionne en local, nous allons installer
            OpenClaw, son moteur AI open-source sous licence MIT
            (38 outils dispo). Prevoyez 2 minutes.
          </div>

          <div
            style={{
              background: 'rgba(99,102,241,0.05)',
              border: '1px solid rgba(99,102,241,0.2)',
              borderRadius: 12,
              padding: 16,
              marginBottom: 20,
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 12, fontSize: 14 }}>
              ✓ Verification systeme
            </div>
            <div style={{ fontSize: 13, lineHeight: 1.8 }}>
              <div>
                Node.js :{' '}
                <span style={{ color: nodeVersion ? '#4ade80' : '#9ca3af' }}>
                  {nodeVersion ?? 'detection…'}
                </span>
              </div>
              <div>
                npm :{' '}
                <span style={{ color: npmVersion ? '#4ade80' : '#9ca3af' }}>
                  {npmVersion ?? 'detection…'}
                </span>
              </div>
              <div>
                OpenClaw :{' '}
                <span
                  style={{
                    color: openclawVersion ? '#4ade80' : '#fbbf24',
                  }}
                >
                  {openclawVersion ?? 'non installe — sera installe a l\'etape 2'}
                </span>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
            <button
              style={primaryButton}
              disabled={!nodeVersion || !npmVersion}
              onClick={() => setStep('install')}
            >
              Continuer →
            </button>
          </div>
        </div>
      </div>
    )
  }

  // ── Ecran 2 : Installation OpenClaw ──────────────────────────────────────
  if (step === 'install') {
    return (
      <div style={containerStyle}>
        <div style={cardStyle}>
          {renderProgressBar()}
          <div style={titleStyle}>Syléa installe son moteur AI OpenClaw</div>
          <div style={subtitleStyle}>
            Licence MIT · 38 outils · Execution 100% locale.
            <br />
            Commande : <code>npm install -g openclaw@latest</code>
          </div>

          {openclawVersion && installStatus === 'idle' && (
            <div
              style={{
                background: 'rgba(74,222,128,0.1)',
                border: '1px solid rgba(74,222,128,0.3)',
                borderRadius: 10,
                padding: 14,
                marginBottom: 20,
                fontSize: 13,
                color: '#4ade80',
              }}
            >
              ✓ OpenClaw {openclawVersion} est deja installe. Vous pouvez
              continuer directement.
            </div>
          )}

          {installStatus === 'idle' && !openclawVersion && (
            <button style={primaryButton} onClick={startInstallOpenClaw}>
              Installer OpenClaw
            </button>
          )}

          {installStatus === 'running' && (
            <div style={{ marginBottom: 20 }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  marginBottom: 12,
                  fontSize: 13,
                  color: '#a78bfa',
                }}
              >
                <span className="loader" style={{
                  display: 'inline-block',
                  width: 14,
                  height: 14,
                  border: '2px solid rgba(167,139,250,0.3)',
                  borderTopColor: '#a78bfa',
                  borderRadius: '50%',
                  animation: 'spin 1s linear infinite',
                }} />
                Installation en cours (cela peut prendre 1 a 3 minutes)…
              </div>
            </div>
          )}

          {installStatus === 'done' && (
            <div
              style={{
                background: 'rgba(74,222,128,0.1)',
                border: '1px solid rgba(74,222,128,0.3)',
                borderRadius: 10,
                padding: 14,
                marginBottom: 20,
                fontSize: 13,
                color: '#4ade80',
              }}
            >
              ✓ OpenClaw installe avec succes
              {openclawVersion ? ` (v${openclawVersion})` : ''}.
            </div>
          )}

          {installStatus === 'error' && (
            <div
              style={{
                background: 'rgba(239,68,68,0.1)',
                border: '1px solid rgba(239,68,68,0.3)',
                borderRadius: 10,
                padding: 14,
                marginBottom: 20,
                fontSize: 13,
                color: '#fca5a5',
              }}
            >
              ✗ Erreur : {installError ?? 'Installation echouee'}
              <div style={{ marginTop: 8 }}>
                <button style={secondaryButton} onClick={startInstallOpenClaw}>
                  Reessayer
                </button>
              </div>
            </div>
          )}

          {/* Console de logs scrollable — uniquement si on a des logs */}
          {installLogs.length > 0 && (
            <div
              ref={installLogsRef}
              style={{
                background: '#000',
                border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: 8,
                padding: 12,
                fontFamily: '"Fira Code", Consolas, monospace',
                fontSize: 11,
                color: '#9ca3af',
                maxHeight: 180,
                overflowY: 'auto',
                marginBottom: 20,
                whiteSpace: 'pre-wrap',
              }}
            >
              {installLogs.map((line, i) => (
                <div key={i}>{line}</div>
              ))}
            </div>
          )}

          <div style={{ display: 'flex', gap: 12, justifyContent: 'space-between' }}>
            <button style={secondaryButton} onClick={() => setStep('welcome')}>
              ← Retour
            </button>
            <button
              style={primaryButton}
              disabled={installStatus !== 'done' && !openclawVersion}
              onClick={() => setStep('token')}
            >
              Continuer →
            </button>
          </div>
        </div>
      </div>
    )
  }

  // ── Ecran 3 : Generation du token gateway ────────────────────────────────
  if (step === 'token') {
    return (
      <div style={containerStyle}>
        <div style={cardStyle}>
          {renderProgressBar()}
          <div style={titleStyle}>Configuration du gateway</div>
          <div style={subtitleStyle}>
            OpenClaw expose ses outils via un gateway local securise par un
            token unique (32 caracteres hex). Nous le generons et
            l'enregistrons dans <code>~/.openclaw/openclaw.json</code>.
          </div>

          {tokenStatus === 'idle' && (
            <button style={primaryButton} onClick={generateToken}>
              Generer le token gateway
            </button>
          )}

          {tokenStatus === 'running' && (
            <div style={{ fontSize: 13, color: '#a78bfa' }}>Generation en cours…</div>
          )}

          {tokenStatus === 'done' && gatewayToken && (
            <div
              style={{
                background: 'rgba(74,222,128,0.1)',
                border: '1px solid rgba(74,222,128,0.3)',
                borderRadius: 10,
                padding: 14,
                marginBottom: 20,
              }}
            >
              <div style={{ fontSize: 13, color: '#4ade80', marginBottom: 8 }}>
                ✓ Token genere et sauvegarde localement
              </div>
              <code
                style={{
                  display: 'block',
                  background: '#000',
                  padding: 8,
                  borderRadius: 6,
                  fontSize: 11,
                  color: '#e5e7eb',
                  wordBreak: 'break-all',
                  fontFamily: '"Fira Code", Consolas, monospace',
                }}
              >
                {gatewayToken.slice(0, 8)}…{gatewayToken.slice(-8)}
              </code>
              <div style={{ fontSize: 11, color: '#6b7280', marginTop: 8 }}>
                Conserve dans <code>~/.openclaw/openclaw.json</code> · URL:
                http://localhost:18789
              </div>
            </div>
          )}

          {tokenStatus === 'error' && (
            <div
              style={{
                background: 'rgba(239,68,68,0.1)',
                border: '1px solid rgba(239,68,68,0.3)',
                borderRadius: 10,
                padding: 14,
                marginBottom: 20,
                fontSize: 13,
                color: '#fca5a5',
              }}
            >
              ✗ Erreur lors de la generation du token.
              <div style={{ marginTop: 8 }}>
                <button style={secondaryButton} onClick={generateToken}>
                  Reessayer
                </button>
              </div>
            </div>
          )}

          <div style={{ display: 'flex', gap: 12, justifyContent: 'space-between' }}>
            <button style={secondaryButton} onClick={() => setStep('install')}>
              ← Retour
            </button>
            <button
              style={primaryButton}
              disabled={tokenStatus !== 'done'}
              onClick={() => setStep('skills')}
            >
              Continuer →
            </button>
          </div>
        </div>
      </div>
    )
  }

  // ── Ecran 4 : Selection & installation des skills ClawHub ────────────────
  if (step === 'skills') {
    const allSelected = selectedSlugs.size === CURATED_SKILLS.length
    const anyInstalling = Object.values(skillInstallProgress).some((s) => s === 'running')
    const allDone =
      selectedSlugs.size > 0 &&
      Array.from(selectedSlugs).every(
        (slug) => skillInstallProgress[slug] === 'done' || skillInstallProgress[slug] === 'error'
      )

    return (
      <div style={containerStyle}>
        <div style={cardStyle}>
          {renderProgressBar()}
          <div style={titleStyle}>Choisissez vos skills ClawHub</div>
          <div style={subtitleStyle}>
            Ces skills permettent a Syléa d'interagir avec vos outils
            quotidiens. Ils sont pre-selectionnes, vous pourrez toujours en
            installer d'autres plus tard depuis le marketplace.
          </div>

          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <button
              style={{ ...secondaryButton, fontSize: 12, padding: '6px 12px' }}
              onClick={allSelected ? deselectAll : selectAll}
            >
              {allSelected ? 'Tout decocher' : 'Tout cocher'}
            </button>
            <div
              style={{
                fontSize: 12,
                color: '#9ca3af',
                alignSelf: 'center',
                marginLeft: 'auto',
              }}
            >
              {selectedSlugs.size} / {CURATED_SKILLS.length} selectionnes
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 20 }}>
            {CURATED_SKILLS.map((skill) => {
              const checked = selectedSlugs.has(skill.slug)
              const progress = skillInstallProgress[skill.slug]
              return (
                <label
                  key={skill.slug}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 12,
                    padding: 12,
                    border: `1px solid ${
                      checked ? 'rgba(167,139,250,0.4)' : 'rgba(255,255,255,0.08)'
                    }`,
                    borderRadius: 10,
                    background: checked
                      ? 'rgba(167,139,250,0.05)'
                      : 'rgba(255,255,255,0.02)',
                    cursor: anyInstalling ? 'not-allowed' : 'pointer',
                    opacity: anyInstalling && !checked ? 0.5 : 1,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleSkill(skill.slug)}
                    disabled={anyInstalling || progress === 'done'}
                    style={{ marginTop: 3, cursor: 'pointer' }}
                  />
                  <div style={{ flex: 1 }}>
                    <div
                      style={{
                        fontSize: 14,
                        fontWeight: 600,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                      }}
                    >
                      <span style={{ fontSize: 18 }}>{skill.emoji}</span>
                      <span>{skill.name}</span>
                      {progress === 'running' && (
                        <span
                          style={{
                            fontSize: 11,
                            color: '#a78bfa',
                            padding: '2px 6px',
                            borderRadius: 999,
                            background: 'rgba(167,139,250,0.15)',
                          }}
                        >
                          Installation…
                        </span>
                      )}
                      {progress === 'done' && (
                        <span
                          style={{
                            fontSize: 11,
                            color: '#4ade80',
                            padding: '2px 6px',
                            borderRadius: 999,
                            background: 'rgba(74,222,128,0.15)',
                          }}
                        >
                          ✓ Installe
                        </span>
                      )}
                      {progress === 'error' && (
                        <span
                          style={{
                            fontSize: 11,
                            color: '#fca5a5',
                            padding: '2px 6px',
                            borderRadius: 999,
                            background: 'rgba(239,68,68,0.15)',
                          }}
                          title={skillInstallError[skill.slug] ?? ''}
                        >
                          ✗ Erreur
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 4 }}>
                      {skill.description}
                    </div>
                  </div>
                </label>
              )
            })}
          </div>

          {skillLogs.length > 0 && (
            <div
              ref={skillLogsRef}
              style={{
                background: '#000',
                border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: 8,
                padding: 10,
                fontFamily: '"Fira Code", Consolas, monospace',
                fontSize: 10,
                color: '#9ca3af',
                maxHeight: 120,
                overflowY: 'auto',
                marginBottom: 20,
                whiteSpace: 'pre-wrap',
              }}
            >
              {skillLogs.map((line, i) => (
                <div key={i}>{line}</div>
              ))}
            </div>
          )}

          <div style={{ display: 'flex', gap: 12, justifyContent: 'space-between' }}>
            <button
              style={secondaryButton}
              onClick={() => setStep('token')}
              disabled={anyInstalling}
            >
              ← Retour
            </button>

            {!allDone ? (
              <button
                style={{
                  ...primaryButton,
                  opacity: anyInstalling ? 0.6 : 1,
                  cursor: anyInstalling ? 'wait' : 'pointer',
                }}
                onClick={installSelectedSkills}
                disabled={anyInstalling || selectedSlugs.size === 0}
              >
                {anyInstalling
                  ? 'Installation en cours…'
                  : selectedSlugs.size === 0
                  ? 'Selectionnez au moins 1 skill'
                  : `Installer ${selectedSlugs.size} skill(s)`}
              </button>
            ) : (
              <button style={primaryButton} onClick={() => setStep('done')}>
                Terminer →
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  // ── Ecran 5 : Synthese finale ────────────────────────────────────────────
  if (step === 'done') {
    const installedCount = Object.values(skillInstallProgress).filter(
      (s) => s === 'done'
    ).length
    // URL du site web Syléa — sylea-ai.com en prod, localhost:5173 en dev.
    // On laisse l'utilisateur customiser si besoin via localStorage.
    // Detection dev : hostname de la page Tauri (en dev Vite sert sur localhost,
    // en prod le bundle est charge via tauri://).
    const isDev =
      typeof window !== 'undefined' &&
      (window.location.hostname === 'localhost' ||
        window.location.hostname === '127.0.0.1')
    const SYLEA_WEB_URL =
      (typeof localStorage !== 'undefined' && localStorage.getItem('sylea_web_url')) ||
      (isDev ? 'http://localhost:5173' : 'https://sylea-ai.com')

    const openWebApp = async () => {
      try {
        await invoke('open_url', { url: SYLEA_WEB_URL })
      } catch (err) {
        console.error('open_url failed:', err)
      }
    }

    return (
      <div style={containerStyle}>
        <div style={cardStyle}>
          {renderProgressBar()}

          {/* Celebration : confetti + logo anime */}
          <div
            style={{
              fontSize: 64,
              textAlign: 'center',
              marginBottom: 8,
              animation: 'bounce 1.2s ease-out',
            }}
          >
            🎉
          </div>
          <div style={{ ...titleStyle, textAlign: 'center', fontSize: 22 }}>
            C'est pret ! Bienvenue dans Syléa
          </div>
          <div style={{ ...subtitleStyle, textAlign: 'center' }}>
            Ton assistant est installe sur ton ordinateur. Il peut maintenant
            agir pour toi : ecrire des emails, prendre des notes, gerer ton
            calendrier.
          </div>

          {/* Recapitulatif visuel des installations */}
          <div
            style={{
              background:
                'linear-gradient(135deg, rgba(6,182,212,0.06), rgba(139,92,246,0.06))',
              border: '1px solid rgba(99,102,241,0.25)',
              borderRadius: 14,
              padding: '16px 18px',
              marginBottom: 22,
              fontSize: 13,
              lineHeight: 1.9,
            }}
          >
            <div style={{ fontWeight: 700, marginBottom: 10, fontSize: 14 }}>
              Ce que Syléa a installe pour toi
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ color: '#10b981', fontWeight: 700 }}>✓</span>
              <span>
                Le moteur <b>OpenClaw</b>
                {openclawVersion ? <span style={{ opacity: 0.6 }}> (v{openclawVersion})</span> : null} — 38 outils de base
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ color: '#10b981', fontWeight: 700 }}>✓</span>
              <span>Une cle de securite unique pour ta machine</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ color: '#10b981', fontWeight: 700 }}>✓</span>
              <span>
                <b>{installedCount}</b> skill{installedCount > 1 ? 's' : ''} pour agir concretement
                (calendrier, email, notes...)
              </span>
            </div>
          </div>

          {/* Carte pedagogique : pourquoi ouvrir le site */}
          <div
            style={{
              background: 'rgba(99,102,241,0.08)',
              border: '1px dashed rgba(99,102,241,0.35)',
              borderRadius: 12,
              padding: '14px 16px',
              marginBottom: 20,
              fontSize: 13,
              lineHeight: 1.6,
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 6 }}>
              🔗 Derniere etape : relie ton compte
            </div>
            <div style={{ opacity: 0.85 }}>
              Ouvre Syléa sur le web et connecte-toi. Des que c'est fait, un
              petit point vert apparaitra en haut du site : ca veut dire que
              Syléa et ton ordinateur se parlent.
            </div>
          </div>

          {/* Double CTA : bouton principal (web) + secondaire (lancer app) */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
              alignItems: 'stretch',
            }}
          >
            <button
              style={{
                ...primaryButton,
                padding: '15px 32px',
                fontSize: 15,
                background:
                  'linear-gradient(135deg, #06b6d4 0%, #6366f1 50%, #8b5cf6 100%)',
                boxShadow: '0 4px 14px rgba(99,102,241,0.35)',
              }}
              onClick={openWebApp}
            >
              🌐 Ouvrir Syléa sur le web
            </button>
            <button
              style={{
                background: 'transparent',
                border: '1px solid rgba(99,102,241,0.3)',
                color: 'rgba(255,255,255,0.85)',
                padding: '10px 24px',
                borderRadius: 10,
                cursor: 'pointer',
                fontSize: 13,
                fontWeight: 500,
              }}
              onClick={finishOnboarding}
            >
              Ou ouvrir directement l'app Syléa Agent
            </button>
          </div>
        </div>

        {/* Animation de spinner globale + bounce pour le confetti */}
        <style>{`
          @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
          }
          @keyframes bounce {
            0%   { transform: scale(0); opacity: 0; }
            50%  { transform: scale(1.25); opacity: 1; }
            100% { transform: scale(1); }
          }
        `}</style>
      </div>
    )
  }

  // Etat inconnu — ne devrait jamais arriver
  return null
}
