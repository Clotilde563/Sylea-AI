// Page Outils — Gestion fine des 38 outils OpenClaw (Agent 3)
// Chaque outil peut etre active/desactive au niveau utilisateur en plus du profil agent.

import { useState, useEffect, useMemo } from 'react'
import { api } from '../api/client'
import ClawHubSkillsSection from '../components/ClawHubSkillsSection'
import OpenClawDirectToolsSection from '../components/OpenClawDirectToolsSection'
import ConfirmDialog, { type ConfirmDialogProps } from '../components/ConfirmDialog'
import { useToast } from '../components/Toast'

const LS_FILTER_GROUP = 'sylea_outils_filter_group'
const LS_SEARCH = 'sylea_outils_search'

// ── Types ────────────────────────────────────────────────────────────────────
interface Tool {
  name: string
  description: string
  group: string
  enabled_profile: boolean
  enabled_user: boolean | null
  effectively_enabled: boolean
}

interface ToolsResponse {
  agent_id: string
  total_tools: number
  enabled_count: number
  has_user_overrides: boolean
  tools: Tool[]
  groups: Record<string, Tool[]>
}

// ── Metadonnees de presentation par groupe ──────────────────────────────────
// Correspond aux 11 groupes exposes par openclaw_bridge.py (Phase 3 = 38 outils).
const GROUP_META: Record<string, { label: string; emoji: string; color: string; description: string }> = {
  web: {
    label: 'Web & Recherche',
    emoji: '🌐',
    color: '#3b82f6',
    description: '9 outils : fetch, DuckDuckGo, Firecrawl, Perplexity, Brave, Google, Tavily, Exa, X',
  },
  ui: {
    label: 'Navigateur & Canvas',
    emoji: '🖥️',
    color: '#06b6d4',
    description: 'Browser Chrome, presentations, diagrammes',
  },
  runtime: {
    label: 'Terminal & Process',
    emoji: '⚙️',
    color: '#f59e0b',
    description: 'exec shell, bash interactif, gestion de processus',
  },
  fs: {
    label: 'Fichiers',
    emoji: '📁',
    color: '#10b981',
    description: 'read, write, edit, apply_patch',
  },
  sessions: {
    label: 'Sous-agents',
    emoji: '🧵',
    color: '#8b5cf6',
    description: 'Spawn, send, list, history de sessions autonomes',
  },
  memory: {
    label: 'Memoire persistante',
    emoji: '🧠',
    color: '#d946ef',
    description: 'Recherche et recuperation de souvenirs long-terme',
  },
  automation: {
    label: 'Automation',
    emoji: '⏱️',
    color: '#ec4899',
    description: 'Taches planifiees (cron) et controle du Gateway',
  },
  messaging: {
    label: 'Messagerie',
    emoji: '✉️',
    color: '#7c3aed',
    description: 'Envoi de messages multi-canal',
  },
  media: {
    label: 'Multimedia',
    emoji: '🎨',
    color: '#a855f7',
    description: '5 outils : analyse image, generation image / musique / video / voix',
  },
  safety: {
    label: 'Securite & Guardrails',
    emoji: '🛡️',
    color: '#ef4444',
    description: '3 outils : moderation contenu, verification URL, scrub PII',
  },
  special: {
    label: 'Speciaux',
    emoji: '✨',
    color: '#fbbf24',
    description: 'llm_task (sous-LLM), lobster (workflows), subagents (orchestration)',
  },
}

// ── Outils sensibles (prevenir l'utilisateur lors de l'activation) ─────────
// Noms reels des tools OpenClaw (cf. ALL_OPENCLAW_TOOLS dans openclaw_bridge.py)
const SENSITIVE_TOOLS = new Set([
  'exec',           // shell arbitraire
  'bash',           // terminal interactif
  'process',        // kill/start process
  'write',          // ecriture fichier
  'edit',           // modif fichier
  'apply_patch',    // patch diff
  'browser',        // automation navigateur
  'message',        // envoi messages externes
  'cron',           // tache planifiee
  'sessions_spawn', // sous-agent autonome
  'subagents',      // orchestration multi-agents
])

// ── Composant ───────────────────────────────────────────────────────────────
export default function OutilsPage() {
  const { toast } = useToast()
  const [data, setData] = useState<ToolsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toggling, setToggling] = useState<string | null>(null)
  const [filterGroup, setFilterGroup] = useState<string>(() => {
    try { return localStorage.getItem(LS_FILTER_GROUP) || 'all' } catch { return 'all' }
  })
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set())
  const [searchQuery, setSearchQuery] = useState<string>(() => {
    try { return localStorage.getItem(LS_SEARCH) || '' } catch { return '' }
  })
  const [confirm, setConfirm] = useState<ConfirmDialogProps | null>(null)

  // Persistance filtres
  useEffect(() => {
    try { localStorage.setItem(LS_FILTER_GROUP, filterGroup) } catch {}
  }, [filterGroup])
  useEffect(() => {
    try { localStorage.setItem(LS_SEARCH, searchQuery) } catch {}
  }, [searchQuery])

  // ── Chargement initial ─────────────────────────────────────────────────
  const loadTools = async () => {
    try {
      setError(null)
      const res = await api.agent3GetTools()
      setData(res)
    } catch (err: any) {
      setError(err?.message || 'Impossible de charger les outils')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTools()
  }, [])

  // ── Toggle un outil ────────────────────────────────────────────────────
  const applyToggle = async (tool: Tool, targetEnabled: boolean) => {
    setToggling(tool.name)
    try {
      await api.agent3ToggleTool(tool.name, targetEnabled)
      setData((prev) => {
        if (!prev) return prev
        const newGroups = { ...prev.groups }
        for (const [g, tools] of Object.entries(newGroups)) {
          newGroups[g] = tools.map((t) =>
            t.name === tool.name
              ? { ...t, enabled_user: targetEnabled, effectively_enabled: targetEnabled && t.enabled_profile }
              : t
          )
        }
        const enabledCount = Object.values(newGroups).flat().filter((t) => t.effectively_enabled).length
        return { ...prev, groups: newGroups, enabled_count: enabledCount }
      })
      toast.success(targetEnabled ? `Outil "${tool.name}" activé` : `Outil "${tool.name}" désactivé`)
    } catch (err: any) {
      const msg = err?.message || `Impossible de modifier ${tool.name}`
      setError(msg)
      toast.error(msg)
    } finally {
      setToggling(null)
    }
  }

  const handleToggle = async (tool: Tool) => {
    if (!data) return
    if (toggling) return  // anti double-submit : un toggle a la fois
    const targetEnabled = !tool.effectively_enabled

    // Confirmation pour outils sensibles lors de l'activation
    if (targetEnabled && SENSITIVE_TOOLS.has(tool.name)) {
      setConfirm({
        title: `Activer "${tool.name}" ?`,
        description: tool.description,
        bullets: [
          '• Cet outil peut modifier des fichiers, envoyer des messages ou lancer des commandes.',
          '• Les actions déclenchées peuvent être irréversibles.',
          '• Tu recevras un résumé dans l\'historique après chaque action.',
        ],
        severity: 'warning',
        confirmLabel: 'Activer',
        onConfirm: () => {
          setConfirm(null)
          void applyToggle(tool, targetEnabled)
        },
        onCancel: () => setConfirm(null),
      })
      return
    }

    void applyToggle(tool, targetEnabled)
  }

  // ── Reset override utilisateur (retour profil) ─────────────────────────
  const applyClearOverride = async (tool: Tool) => {
    setToggling(tool.name)
    try {
      await api.agent3ClearToolOverride(tool.name)
      await loadTools()
      toast.success(`Réglage personnel de "${tool.name}" réinitialisé`)
    } catch (err: any) {
      const msg = err?.message || 'Échec de la réinitialisation'
      setError(msg)
      toast.error(msg)
    } finally {
      setToggling(null)
    }
  }

  const handleClearOverride = (tool: Tool) => {
    if (tool.enabled_user === null) return
    if (toggling) return
    setConfirm({
      title: `Réinitialiser "${tool.name}" ?`,
      description: `Ton réglage personnel sera supprimé. L'outil reprendra le comportement par défaut défini par ton profil.`,
      severity: 'info',
      confirmLabel: 'Réinitialiser',
      onConfirm: () => {
        setConfirm(null)
        void applyClearOverride(tool)
      },
      onCancel: () => setConfirm(null),
    })
  }

  // ── Activer/desactiver tout un groupe ──────────────────────────────────
  const applyBulkToggle = async (group: string, enabled: boolean, tools: Tool[]) => {
    const prefs: Record<string, boolean> = {}
    tools.forEach((t) => { prefs[t.name] = enabled })
    setToggling('__bulk__')
    try {
      await api.agent3BulkToggleTools(prefs)
      await loadTools()
      toast.success(
        enabled
          ? `${tools.length} outil(s) activé(s) dans "${group}"`
          : `${tools.length} outil(s) désactivé(s) dans "${group}"`
      )
    } catch (err: any) {
      const msg = err?.message || 'Échec de l\'opération groupée'
      setError(msg)
      toast.error(msg)
    } finally {
      setToggling(null)
    }
  }

  const handleBulkGroupToggle = async (group: string, enabled: boolean) => {
    if (!data) return
    if (toggling) return
    const tools = data.groups[group] || []
    if (enabled) {
      const sensitive = tools.filter((t) => SENSITIVE_TOOLS.has(t.name))
      if (sensitive.length > 0) {
        setConfirm({
          title: `Activer tout le groupe "${group}" ?`,
          description: `Ce groupe contient ${sensitive.length} outil(s) sensible(s) :`,
          bullets: sensitive.map((t) => `• ${t.name}`),
          severity: 'warning',
          confirmLabel: `Activer (${tools.length})`,
          onConfirm: () => {
            setConfirm(null)
            void applyBulkToggle(group, enabled, tools)
          },
          onCancel: () => setConfirm(null),
        })
        return
      }
    }
    void applyBulkToggle(group, enabled, tools)
  }

  const toggleCollapse = (group: string) => {
    const next = new Set(collapsedGroups)
    if (next.has(group)) next.delete(group)
    else next.add(group)
    setCollapsedGroups(next)
  }

  // ── Filtrage (recherche + groupe) ──────────────────────────────────────
  const filteredGroups = useMemo<Record<string, Tool[]>>(() => {
    if (!data) return {}
    const q = searchQuery.trim().toLowerCase()
    const out: Record<string, Tool[]> = {}
    for (const [g, tools] of Object.entries(data.groups)) {
      if (filterGroup !== 'all' && filterGroup !== g) continue
      const kept = q
        ? tools.filter((t) =>
            t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q)
          )
        : tools
      if (kept.length > 0) out[g] = kept
    }
    return out
  }, [data, filterGroup, searchQuery])

  // ── Rendering ──────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div style={{
        maxWidth: 960, margin: '0 auto', padding: '3rem 1rem',
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1rem',
      }}>
        <div
          aria-label="Chargement"
          style={{
            width: 36, height: 36,
            border: '3px solid rgba(255,255,255,0.08)',
            borderTopColor: 'var(--accent-silver, #c0c0c0)',
            borderRadius: '50%',
            animation: 'sylea-spin 0.8s linear infinite',
          }}
        />
        <div style={{ color: 'var(--text-muted)', fontSize: '0.95rem' }}>
          Chargement des outils…
        </div>
        <style>{`@keyframes sylea-spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    )
  }

  if (!data) {
    return (
      <div style={{ maxWidth: 960, margin: '0 auto', padding: '3rem 1rem' }}>
        <div style={{
          background: 'rgba(239,68,68,0.08)',
          border: '1px solid rgba(239,68,68,0.25)',
          borderRadius: 10, padding: '1rem', color: '#ef4444', textAlign: 'center',
        }}>
          {error || 'Impossible de charger les outils'}
          <button
            onClick={loadTools}
            style={{
              marginLeft: '1rem', padding: '0.35rem 0.75rem',
              background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.35)',
              borderRadius: 6, color: '#ef4444', cursor: 'pointer', fontSize: '0.8rem',
            }}
          >
            Reessayer
          </button>
        </div>
      </div>
    )
  }

  const totalTools = data.total_tools
  const activeTools = data.enabled_count
  const groupsList = Object.keys(filteredGroups)

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '2rem 1rem' }}>
      {/* Header */}
      <div style={{ marginBottom: '2rem' }}>
        <p style={{
          color: 'var(--text-muted)', fontSize: '0.875rem',
          marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.1em',
        }}>
          Agent 3 — OpenClaw
        </p>
        <h1 style={{ fontSize: '1.75rem', color: 'var(--accent-silver)', marginBottom: '0.5rem' }}>
          Outils ({activeTools}/{totalTools} actifs)
        </h1>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', lineHeight: 1.5 }}>
          Controlez precisement quels outils l'agent peut utiliser. Les outils sensibles (email, terminal, automation) sont signales d'un{' '}
          <span style={{ color: '#f59e0b' }}>⚠️</span>.
          {data.has_user_overrides && (
            <span style={{ marginLeft: '0.5rem', color: '#8b5cf6' }}>
              ● Vos reglages personnels sont appliques
            </span>
          )}
        </p>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{
          background: 'rgba(239,68,68,0.08)',
          border: '1px solid rgba(239,68,68,0.25)',
          borderRadius: 10, padding: '0.75rem 1rem', marginBottom: '1rem',
          color: '#ef4444', fontSize: '0.85rem',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span>{error}</span>
          <button
            onClick={() => setError(null)}
            style={{
              background: 'transparent', border: 'none', color: '#ef4444',
              cursor: 'pointer', fontSize: '1rem',
            }}
          >
            ×
          </button>
        </div>
      )}

      {/* Toolbar : search + filter */}
      <div style={{
        display: 'flex', gap: '0.75rem', marginBottom: '1.5rem',
        flexWrap: 'wrap', alignItems: 'center',
      }}>
        <input
          type="text"
          placeholder="🔍 Rechercher un outil..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={{
            flex: '1 1 260px',
            padding: '0.55rem 0.85rem',
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            color: 'var(--text-primary)',
            fontSize: '0.9rem',
            outline: 'none',
          }}
        />
        <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
          <FilterPill
            label="Tous"
            active={filterGroup === 'all'}
            onClick={() => setFilterGroup('all')}
          />
          {Object.entries(GROUP_META).map(([g, meta]) => (
            data.groups[g] && data.groups[g].length > 0 ? (
              <FilterPill
                key={g}
                label={`${meta.emoji} ${meta.label}`}
                active={filterGroup === g}
                onClick={() => setFilterGroup(g)}
                color={meta.color}
              />
            ) : null
          ))}
        </div>
      </div>

      {/* Groups */}
      {groupsList.length === 0 ? (
        <div style={{
          textAlign: 'center', padding: '3rem 1rem',
          color: 'var(--text-muted)', fontSize: '0.9rem',
        }}>
          Aucun outil ne correspond aux filtres.
        </div>
      ) : (
        groupsList.map((group) => {
          const meta = GROUP_META[group] || {
            label: group, emoji: '🔧', color: '#64748b', description: '',
          }
          const tools = filteredGroups[group]
          const groupActive = tools.filter((t) => t.effectively_enabled).length
          const collapsed = collapsedGroups.has(group)

          return (
            <section
              key={group}
              style={{
                marginBottom: '1.25rem',
                background: 'rgba(255,255,255,0.02)',
                border: '1px solid var(--border)',
                borderRadius: 14,
                overflow: 'hidden',
              }}
            >
              {/* Header du groupe */}
              <header
                onClick={() => toggleCollapse(group)}
                style={{
                  padding: '0.85rem 1.1rem',
                  borderBottom: collapsed ? 'none' : '1px solid var(--border)',
                  background: `linear-gradient(90deg, ${meta.color}14, transparent)`,
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  cursor: 'pointer', userSelect: 'none',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <span style={{ fontSize: '1.25rem' }}>{meta.emoji}</span>
                  <div>
                    <div style={{
                      fontSize: '0.98rem', fontWeight: 600,
                      color: meta.color,
                    }}>
                      {meta.label}{' '}
                      <span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: '0.8em' }}>
                        ({groupActive}/{tools.length})
                      </span>
                    </div>
                    {meta.description && (
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.12rem' }}>
                        {meta.description}
                      </div>
                    )}
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleBulkGroupToggle(group, true) }}
                    disabled={toggling === '__bulk__'}
                    style={{
                      padding: '0.3rem 0.65rem',
                      background: 'rgba(16,185,129,0.12)',
                      border: '1px solid rgba(16,185,129,0.35)',
                      borderRadius: 6,
                      color: '#10b981', cursor: 'pointer', fontSize: '0.72rem',
                    }}
                    title="Activer tous les outils de ce groupe"
                  >
                    Tout activer
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleBulkGroupToggle(group, false) }}
                    disabled={toggling === '__bulk__'}
                    style={{
                      padding: '0.3rem 0.65rem',
                      background: 'rgba(239,68,68,0.1)',
                      border: '1px solid rgba(239,68,68,0.3)',
                      borderRadius: 6,
                      color: '#ef4444', cursor: 'pointer', fontSize: '0.72rem',
                    }}
                    title="Desactiver tous les outils de ce groupe"
                  >
                    Tout desactiver
                  </button>
                  <span style={{
                    color: 'var(--text-muted)',
                    marginLeft: '0.25rem',
                    transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
                    transition: 'transform 0.2s',
                    fontSize: '0.9rem',
                  }}>
                    ▾
                  </span>
                </div>
              </header>

              {/* Grille d'outils */}
              {!collapsed && (
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
                  gap: '0.6rem',
                  padding: '0.85rem',
                }}>
                  {tools.map((tool) => (
                    <ToolCard
                      key={tool.name}
                      tool={tool}
                      color={meta.color}
                      loading={toggling === tool.name}
                      onToggle={() => handleToggle(tool)}
                      onClearOverride={() => handleClearOverride(tool)}
                      isSensitive={SENSITIVE_TOOLS.has(tool.name)}
                    />
                  ))}
                </div>
              )}
            </section>
          )
        })
      )}

      {/* OpenClaw directs — Phase 5 (exposition granulaire des 38 outils au LLM) */}
      <OpenClawDirectToolsSection />

      {/* ClawHub Skills — Phase 4 (agent auto-extensible) */}
      <ClawHubSkillsSection />

      {/* Modale de confirmation custom (remplace window.confirm) */}
      {confirm && <ConfirmDialog {...confirm} />}

      {/* Legend */}
      <div style={{
        marginTop: '2rem',
        padding: '1rem',
        background: 'rgba(255,255,255,0.02)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        fontSize: '0.78rem',
        color: 'var(--text-muted)',
        lineHeight: 1.6,
      }}>
        <strong style={{ color: 'var(--text-secondary)' }}>Comment ca marche :</strong><br/>
        • <span style={{ color: '#10b981' }}>●</span> outil actif — l'agent peut l'appeler.<br/>
        • <span style={{ color: '#64748b' }}>●</span> outil inactif — ignore par l'agent.<br/>
        • <span style={{ color: '#f59e0b' }}>⚠️</span> outil sensible — confirmation demandee a l'activation.<br/>
        • <span style={{ color: '#8b5cf6' }}>●</span> override utilisateur — votre choix prime sur le profil.<br/>
        • Le profil systeme de l'agent definit l'etat par defaut ; votre toggle enregistre
        un override personnel dans la base locale.<br/>
        • <span style={{ color: '#6366f1' }}>🧩</span> Skills ClawHub : agent auto-extensible —
        installe depuis clawhub.com ou cree de nouvelles skills a la volee.
      </div>
    </div>
  )
}

// ── Sous-composants ─────────────────────────────────────────────────────────

function FilterPill(props: { label: string; active: boolean; onClick: () => void; color?: string }) {
  return (
    <button
      onClick={props.onClick}
      style={{
        padding: '0.35rem 0.75rem',
        background: props.active
          ? (props.color ? `${props.color}25` : 'rgba(139,92,246,0.2)')
          : 'rgba(255,255,255,0.03)',
        border: `1px solid ${props.active
          ? (props.color || 'rgba(139,92,246,0.4)')
          : 'var(--border)'}`,
        borderRadius: 18,
        color: props.active
          ? (props.color || 'var(--accent-violet-light)')
          : 'var(--text-muted)',
        fontSize: '0.78rem',
        cursor: 'pointer',
        transition: 'all 0.15s',
        whiteSpace: 'nowrap',
      }}
    >
      {props.label}
    </button>
  )
}

function ToolCard(props: {
  tool: Tool
  color: string
  loading: boolean
  onToggle: () => void
  onClearOverride: () => void
  isSensitive: boolean
}) {
  const { tool, color, loading, onToggle, onClearOverride, isSensitive } = props
  const hasOverride = tool.enabled_user !== null
  const active = tool.effectively_enabled

  return (
    <div
      style={{
        padding: '0.75rem',
        background: active
          ? `linear-gradient(135deg, ${color}0a, rgba(255,255,255,0.015))`
          : 'rgba(0,0,0,0.18)',
        border: `1px solid ${active ? `${color}40` : 'var(--border)'}`,
        borderRadius: 10,
        display: 'flex', flexDirection: 'column', gap: '0.5rem',
        opacity: loading ? 0.5 : 1,
        transition: 'all 0.15s',
      }}
    >
      {/* Header : name + status dot + toggle */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.5rem' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
            <span style={{
              width: 7, height: 7, borderRadius: '50%',
              background: active ? '#10b981' : '#64748b',
              flexShrink: 0,
              boxShadow: active ? '0 0 6px rgba(16,185,129,0.5)' : 'none',
            }} />
            <code style={{
              fontSize: '0.85rem', fontWeight: 600,
              color: active ? 'var(--text-primary)' : 'var(--text-muted)',
              wordBreak: 'break-word',
            }}>
              {tool.name}
            </code>
            {isSensitive && (
              <span title="Outil sensible" style={{ fontSize: '0.85rem' }}>⚠️</span>
            )}
            {hasOverride && (
              <span
                title={`Override utilisateur : ${tool.enabled_user ? 'force actif' : 'force inactif'}`}
                style={{
                  fontSize: '0.62rem', color: '#8b5cf6',
                  background: 'rgba(139,92,246,0.12)',
                  padding: '0.1rem 0.3rem', borderRadius: 4,
                  border: '1px solid rgba(139,92,246,0.3)',
                  fontWeight: 600, letterSpacing: '0.04em',
                }}
              >
                PERSO
              </span>
            )}
          </div>
        </div>

        {/* Toggle switch */}
        <ToggleSwitch
          checked={active}
          onChange={onToggle}
          disabled={loading}
          color={color}
        />
      </div>

      {/* Description */}
      <p style={{
        fontSize: '0.76rem', color: 'var(--text-muted)',
        margin: 0, lineHeight: 1.4, minHeight: '2.2em',
      }}>
        {tool.description}
      </p>

      {/* Footer : reset override */}
      {hasOverride && (
        <button
          onClick={onClearOverride}
          disabled={loading}
          style={{
            alignSelf: 'flex-start',
            padding: '0.15rem 0.5rem',
            background: 'transparent',
            border: '1px solid rgba(139,92,246,0.3)',
            borderRadius: 5,
            color: '#8b5cf6',
            fontSize: '0.68rem',
            cursor: 'pointer',
          }}
          title="Revenir au parametrage du profil agent"
        >
          ↺ Reset
        </button>
      )}
    </div>
  )
}

function ToggleSwitch(props: { checked: boolean; onChange: () => void; disabled?: boolean; color: string }) {
  return (
    <button
      onClick={props.onChange}
      disabled={props.disabled}
      role="switch"
      aria-checked={props.checked}
      style={{
        width: 36, height: 20, flexShrink: 0,
        background: props.checked ? props.color : 'rgba(100,116,139,0.3)',
        border: 'none',
        borderRadius: 10,
        cursor: props.disabled ? 'not-allowed' : 'pointer',
        position: 'relative',
        transition: 'background 0.2s',
        padding: 0,
      }}
    >
      <span style={{
        position: 'absolute',
        top: 2,
        left: props.checked ? 18 : 2,
        width: 16, height: 16,
        background: '#fff',
        borderRadius: '50%',
        transition: 'left 0.2s',
        boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
      }} />
    </button>
  )
}
