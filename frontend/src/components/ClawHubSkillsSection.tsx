// ClawHub Skills Section (Phase 4 — auto-extension Agent 3)
//
// Version simplifiee : l'agent s'auto-etend, la liste des skills et le
// viewer SKILL.md ont ete retires (utilite faible, duplique le chat).
//
// Cette section garde deux roles :
//   1. Toggles globaux (permission mode Default/Bypass + kill-switches).
//   2. Historique des auto-extensions (audit trail persistent).
//
// Le feedback temps-reel pendant une auto-extension arrive via SSE dans
// le chat (banner en haut d'AgentsPage). Cette section sert a consulter
// l'historique apres coup.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'

// ── Types ────────────────────────────────────────────────────────────────────
interface ClawHubSettings {
  permission_mode: 'default' | 'bypass'
  clawhub_skills_enabled: boolean
  clawhub_meta_enabled: boolean
  clawhub_enabled_slugs: string[] | null
  enabled_mode: 'all' | 'filter'
}

interface ClawHubEvent {
  id: number
  event_type: 'auto_search' | 'auto_install' | 'auto_publish' | 'auto_unknown'
  slug: string
  trigger_context: string
  success: boolean
  error_message: string
  created_at: string
}

// ── Composant principal ─────────────────────────────────────────────────────
export default function ClawHubSkillsSection() {
  const [settings, setSettings] = useState<ClawHubSettings | null>(null)
  const [events, setEvents] = useState<ClawHubEvent[]>([])
  const [eventsCounts, setEventsCounts] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [updating, setUpdating] = useState(false)  // anti double-submit
  // Modal viewer du SKILL.md
  const [skillMd, setSkillMd] = useState<null | {
    slug: string
    loading: boolean
    content?: string
    name?: string
    description?: string
    version?: string
    author?: string
    homepage?: string
    error?: string
  }>(null)

  const openSkillMd = useCallback(async (slug: string) => {
    setSkillMd({ slug, loading: true })
    try {
      const r = await api.agent3ClawhubGetSkillMarkdown(slug)
      setSkillMd({
        slug: r.slug, loading: false,
        content: r.markdown, name: r.name, description: r.description,
        version: r.version, author: r.author, homepage: r.homepage,
      })
    } catch (e: any) {
      setSkillMd({ slug, loading: false, error: e?.message || 'SKILL.md introuvable' })
    }
  }, [])

  // ── Chargement initial ────────────────────────────────────────────────
  const load = async () => {
    try {
      setError(null)
      const [settingsRes, eventsRes] = await Promise.all([
        api.agent3ClawhubGetSettings(),
        api.agent3ClawhubGetEvents(50),
      ])
      setSettings({
        permission_mode: settingsRes.permission_mode,
        clawhub_skills_enabled: settingsRes.clawhub_skills_enabled,
        clawhub_meta_enabled: settingsRes.clawhub_meta_enabled,
        clawhub_enabled_slugs: settingsRes.clawhub_enabled_slugs,
        enabled_mode: settingsRes.enabled_mode,
      })
      if (eventsRes.success) {
        setEvents(eventsRes.events || [])
        setEventsCounts(eventsRes.counts_by_type || {})
      }
    } catch (err: any) {
      setError(err?.message || 'Erreur reseau')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Toggles globaux (permission_mode, enabled flags) ─────────────────
  const updateSettings = async (patch: Partial<ClawHubSettings>) => {
    if (updating) return  // anti double-submit
    setUpdating(true)
    try {
      const r = await api.agent3ClawhubUpdateSettings({
        permission_mode: patch.permission_mode,
        clawhub_skills_enabled: patch.clawhub_skills_enabled,
        clawhub_meta_enabled: patch.clawhub_meta_enabled,
      })
      setSettings({
        permission_mode: r.permission_mode,
        clawhub_skills_enabled: r.clawhub_skills_enabled,
        clawhub_meta_enabled: r.clawhub_meta_enabled,
        clawhub_enabled_slugs: r.clawhub_enabled_slugs,
        enabled_mode: r.clawhub_enabled_slugs === null ? 'all' : 'filter',
      })
    } catch (err: any) {
      setError(err?.message || 'Échec de la mise à jour des paramètres')
    } finally {
      setUpdating(false)
    }
  }

  const handlePermissionMode = (mode: 'default' | 'bypass') => {
    if (updating) return
    if (mode === 'bypass') {
      const ok = window.confirm(
        `Activer le mode bypass ?\n\n` +
        `Dans ce mode, l'agent pourra :\n` +
        `• Installer des skills ClawHub sans te demander.\n` +
        `• Publier des skills en ton nom sur le registre.\n` +
        `• Exécuter des actions autonomes associées aux skills installées.\n\n` +
        `À activer uniquement si tu fais entièrement confiance à l'agent.`
      )
      if (!ok) return
    }
    updateSettings({ permission_mode: mode })
  }

  const totalEvents = useMemo(() => (
    (eventsCounts.auto_search || 0)
    + (eventsCounts.auto_install || 0)
    + (eventsCounts.auto_publish || 0)
  ), [eventsCounts])

  // ── Rendering ────────────────────────────────────────────────────────
  return (
    <section style={{
      marginTop: '2rem',
      background: 'rgba(255,255,255,0.02)',
      border: '1px solid var(--border)',
      borderRadius: 14,
      overflow: 'hidden',
    }}>
      {/* Header */}
      <header style={{
        padding: '1rem 1.25rem',
        background: 'linear-gradient(90deg, rgba(99,102,241,0.12), transparent)',
        borderBottom: '1px solid var(--border)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <div style={{ fontSize: '1.1rem', fontWeight: 600, color: '#6366f1' }}>
              🧩 Auto-extension ClawHub
              {loading && <span style={{ fontSize: '0.8em', color: 'var(--text-muted)', fontWeight: 400 }}> — chargement...</span>}
            </div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
              L'agent cherche, installe et cree des skills tout seul.
              Le live s'affiche dans le chat ; cette section sert de journal d'audit.
            </div>
          </div>
          <button
            onClick={() => load()}
            style={actionBtnStyle('#64748b')}
            disabled={loading}
          >
            ↻ Rafraichir
          </button>
        </div>
      </header>

      {/* Settings panel */}
      {settings && (
        <div style={{
          padding: '0.85rem 1.25rem',
          background: 'rgba(99,102,241,0.04)',
          borderBottom: '1px solid var(--border)',
          display: 'flex', flexWrap: 'wrap', gap: '1.5rem', alignItems: 'center',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>Mode :</span>
            <div style={{ display: 'flex', background: 'rgba(0,0,0,0.25)', borderRadius: 8, padding: 2 }}>
              <ModeButton
                active={settings.permission_mode === 'default'}
                color="#10b981"
                onClick={() => handlePermissionMode('default')}
              >
                🛡️ Default
              </ModeButton>
              <ModeButton
                active={settings.permission_mode === 'bypass'}
                color="#f59e0b"
                onClick={() => handlePermissionMode('bypass')}
              >
                ⚡ Bypass
              </ModeButton>
            </div>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              {settings.permission_mode === 'default'
                ? '(confirmation avant install/publish)'
                : '(auto-extension sans confirmation)'}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <InlineToggle
              label="Skills exposees comme tools"
              checked={settings.clawhub_skills_enabled}
              onChange={(v) => updateSettings({ clawhub_skills_enabled: v })}
            />
            <InlineToggle
              label="Meta-tools (search/install/publish)"
              checked={settings.clawhub_meta_enabled}
              onChange={(v) => updateSettings({ clawhub_meta_enabled: v })}
            />
          </div>
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div style={{
          padding: '0.65rem 1.25rem',
          background: 'rgba(239,68,68,0.1)',
          color: '#ef4444', fontSize: '0.82rem',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span>⚠️ {error}</span>
          <button onClick={() => setError(null)} style={{
            background: 'transparent', border: 'none', color: '#ef4444', cursor: 'pointer',
          }}>×</button>
        </div>
      )}

      {/* Events history */}
      <div>
        <div style={{
          padding: '0.85rem 1.25rem',
          borderBottom: '1px solid var(--border)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div style={{ fontSize: '0.88rem', fontWeight: 600, color: 'var(--text-primary)' }}>
            📜 Historique auto-extensions
          </div>
          {totalEvents > 0 && (
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              {totalEvents} evts
            </span>
          )}
        </div>

        {/* Counts by type */}
        {totalEvents > 0 && (
          <div style={{
            padding: '0.6rem 1.25rem',
            borderBottom: '1px solid var(--border)',
            display: 'flex', gap: '0.5rem', flexWrap: 'wrap',
          }}>
            <EventCountBadge label="Recherches" count={eventsCounts.auto_search || 0} color="#64748b" />
            <EventCountBadge label="Installations" count={eventsCounts.auto_install || 0} color="#10b981" />
            <EventCountBadge label="Publications" count={eventsCounts.auto_publish || 0} color="#f59e0b" />
          </div>
        )}

        {/* Events list */}
        <div style={{ padding: '0.5rem 0', maxHeight: '480px', overflowY: 'auto' }}>
          {events.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '2rem 1rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
              {loading
                ? 'Chargement...'
                : "Aucune auto-extension pour le moment. Quand l'agent detectera qu'une skill manque, il l'installera ou la creera — elle apparaitra ici."}
            </div>
          ) : (
            events.map((ev) => <EventRow key={ev.id} event={ev} onOpenSkill={openSkillMd} />)
          )}
        </div>
      </div>

      {/* Modal SKILL.md viewer */}
      {skillMd && (
        <SkillMdModal
          data={skillMd}
          onClose={() => setSkillMd(null)}
        />
      )}
    </section>
  )
}

// ── Modal viewer du SKILL.md ─────────────────────────────────────────────────
function SkillMdModal(props: {
  data: {
    slug: string
    loading: boolean
    content?: string
    name?: string
    description?: string
    version?: string
    author?: string
    homepage?: string
    error?: string
  }
  onClose: () => void
}) {
  const d = props.data

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') props.onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [props])

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={(e) => { if (e.target === e.currentTarget) props.onClose() }}
      style={{
        position: 'fixed', inset: 0, zIndex: 10000,
        background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '1.5rem',
      }}
    >
      <div style={{
        maxWidth: 800, width: '100%', maxHeight: '85vh',
        background: 'var(--bg-panel, #121820)',
        border: '1px solid rgba(99,102,241,0.4)',
        borderRadius: 12, overflow: 'hidden',
        display: 'flex', flexDirection: 'column',
        boxShadow: '0 24px 60px rgba(0,0,0,0.6)',
      }}>
        {/* Header */}
        <div style={{
          padding: '1rem 1.25rem',
          borderBottom: '1px solid var(--border)',
          background: 'linear-gradient(90deg, rgba(99,102,241,0.1), transparent)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem',
        }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#6366f1', marginBottom: '0.25rem' }}>
              📖 {d.name || d.slug}
            </div>
            <code style={{ color: 'var(--text-muted)', fontSize: '0.72rem' }}>skill_{d.slug.replace(/-/g, '_')}</code>
            {d.description && (
              <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary, #d0d0d0)', marginTop: '0.3rem', lineHeight: 1.4 }}>
                {d.description}
              </div>
            )}
            <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.4rem', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
              {d.version && <span>v{d.version}</span>}
              {d.author && <span>par {d.author}</span>}
              {d.homepage && (
                <a href={d.homepage} target="_blank" rel="noopener noreferrer" style={{ color: '#6366f1' }}>
                  🔗 homepage
                </a>
              )}
            </div>
          </div>
          <button
            onClick={props.onClose}
            style={{
              background: 'transparent', border: 'none', color: 'var(--text-muted)',
              cursor: 'pointer', fontSize: '1.5rem', padding: '0 0.3rem',
            }}
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '1rem 1.25rem' }}>
          {d.loading && (
            <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', textAlign: 'center', padding: '2rem' }}>
              Chargement du SKILL.md…
            </div>
          )}
          {d.error && (
            <div style={{
              padding: '0.75rem', background: 'rgba(239,68,68,0.08)',
              border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8,
              color: '#ef4444', fontSize: '0.85rem',
            }}>
              {d.error}
            </div>
          )}
          {d.content && (
            <pre style={{
              margin: 0, padding: 0,
              fontFamily: "'Fira Code', 'Cascadia Code', ui-monospace, monospace",
              fontSize: '0.78rem', lineHeight: 1.55,
              color: 'var(--text-primary, #e5e7eb)',
              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            }}>
              {d.content}
            </pre>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: '0.6rem 1.25rem',
          borderTop: '1px solid var(--border)',
          fontSize: '0.7rem', color: 'var(--text-muted)',
          textAlign: 'right',
        }}>
          Fermer : clic exterieur ou Echap
        </div>
      </div>
    </div>
  )
}

// ── Sous-composants ─────────────────────────────────────────────────────────
function EventRow(props: { event: ClawHubEvent; onOpenSkill: (slug: string) => void }) {
  const ev = props.event
  const typeMap: Record<string, { label: string; color: string; icon: string }> = {
    auto_search: { label: 'Recherche', color: '#64748b', icon: '🔍' },
    auto_install: { label: 'Installation', color: '#10b981', icon: '↓' },
    auto_publish: { label: 'Publication', color: '#f59e0b', icon: '↑' },
    auto_unknown: { label: 'Action', color: '#6366f1', icon: '•' },
  }
  const meta = typeMap[ev.event_type] || typeMap.auto_unknown
  const ts = ev.created_at || ''
  // Bouton "Voir SKILL.md" dispo pour les installations et publications reussies.
  const canViewSkill = ev.success
    && (ev.event_type === 'auto_install' || ev.event_type === 'auto_publish')
    && ev.slug
    && ev.slug !== '(none)'

  return (
    <div style={{
      padding: '0.55rem 1.25rem',
      borderBottom: '1px solid rgba(255,255,255,0.04)',
      fontSize: '0.78rem',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.15rem' }}>
        <span style={{ color: meta.color }}>{meta.icon}</span>
        <span style={{ color: meta.color, fontWeight: 600, fontSize: '0.72rem' }}>
          {meta.label}
        </span>
        <code style={{ color: 'var(--text-primary)', fontSize: '0.75rem' }}>{ev.slug}</code>
        {!ev.success && (
          <span style={{
            padding: '0 0.3rem', background: 'rgba(239,68,68,0.15)',
            color: '#ef4444', borderRadius: 3, fontSize: '0.62rem', fontWeight: 600,
          }}>ECHEC</span>
        )}
        {canViewSkill && (
          <button
            onClick={() => props.onOpenSkill(ev.slug)}
            style={{
              padding: '1px 6px',
              background: 'rgba(99,102,241,0.12)',
              border: '1px solid rgba(99,102,241,0.3)',
              borderRadius: 4,
              color: '#6366f1',
              fontSize: '0.65rem',
              cursor: 'pointer',
              marginLeft: '0.3rem',
            }}
            title="Afficher le SKILL.md complet"
          >
            📖 Voir SKILL.md
          </button>
        )}
        <span style={{ marginLeft: 'auto', color: 'var(--text-muted)', fontSize: '0.68rem' }}>
          {ts}
        </span>
      </div>
      {ev.trigger_context && (
        <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginLeft: '1.2rem', lineHeight: 1.35, overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {ev.trigger_context}
        </div>
      )}
      {!ev.success && ev.error_message && (
        <div style={{ fontSize: '0.68rem', color: '#ef4444', marginLeft: '1.2rem', marginTop: '0.15rem', lineHeight: 1.35 }}>
          {ev.error_message}
        </div>
      )}
    </div>
  )
}

function EventCountBadge(props: { label: string; count: number; color: string }) {
  return (
    <div style={{
      padding: '0.25rem 0.55rem',
      background: `${props.color}12`,
      border: `1px solid ${props.color}35`,
      borderRadius: 6,
      fontSize: '0.7rem',
      color: props.color,
      display: 'flex', gap: '0.3rem', alignItems: 'baseline',
    }}>
      <span style={{ fontWeight: 700 }}>{props.count}</span>
      <span style={{ opacity: 0.85 }}>{props.label}</span>
    </div>
  )
}

function ModeButton(props: {
  active: boolean; color: string; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button
      onClick={props.onClick}
      style={{
        padding: '0.3rem 0.7rem',
        background: props.active ? `${props.color}25` : 'transparent',
        border: 'none',
        borderRadius: 6,
        color: props.active ? props.color : 'var(--text-muted)',
        fontSize: '0.78rem', fontWeight: props.active ? 600 : 400,
        cursor: 'pointer',
        transition: 'all 0.15s',
      }}
    >
      {props.children}
    </button>
  )
}

function InlineToggle(props: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', cursor: 'pointer', userSelect: 'none' }}>
      <input
        type="checkbox"
        checked={props.checked}
        onChange={(e) => props.onChange(e.target.checked)}
        style={{ accentColor: '#6366f1', cursor: 'pointer' }}
      />
      <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>{props.label}</span>
    </label>
  )
}

// ── Styles utilitaires ─────────────────────────────────────────────────────
function actionBtnStyle(color: string): React.CSSProperties {
  return {
    padding: '0.4rem 0.75rem',
    background: `${color}20`,
    border: `1px solid ${color}50`,
    borderRadius: 6,
    color: color,
    fontSize: '0.78rem', fontWeight: 500,
    cursor: 'pointer',
  }
}
