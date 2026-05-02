/**
 * OpenClawDirectToolsSection — gestion granulaire des 38 outils OpenClaw
 * directement exposes au LLM d'Agent 3 (Phase 5).
 *
 * - Toggle global `direct_tools_enabled` : expose les 38 ou rien.
 * - Quand active : checkbox par outil pour selection granulaire.
 * - Persistance via PUT /api/agent3/preferences (openclaw_enabled_tools).
 *
 * Note : ce composant gere l'EXPOSITION AU LLM, pas la permission d'execution.
 * La page /outils traite separement la permission d'execution (toggles legacy).
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { useToast } from './Toast'

type OCTool = {
  name: string
  group: string
  description: string
  exposed_to_llm: boolean
  is_destructive: boolean
}

const GROUP_LABEL: Record<string, string> = {
  web: '🌐 Web & Recherche',
  ui: '🖥️ Navigateur & Canvas',
  runtime: '⚙️ Terminal & Process',
  fs: '📁 Filesystem',
  sessions: '🧬 Sous-agents',
  memory: '🧠 Mémoire',
  automation: '⏰ Automatisation',
  messaging: '💬 Messagerie',
  media: '🎨 Média (IA)',
  safety: '🛡️ Sécurité',
  special: '⭐ Spécial',
}

export default function OpenClawDirectToolsSection() {
  const { toast } = useToast()
  const [data, setData] = useState<{
    tools: OCTool[]
    direct_tools_enabled: boolean
    enabled_filter: 'all' | 'subset'
    counts: { total: number; exposed: number; destructive: number }
  } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setError(null)
    try {
      const r = await api.agent3ListOpenClawTools()
      setData({
        tools: r.tools,
        direct_tools_enabled: r.direct_tools_enabled,
        enabled_filter: r.enabled_filter,
        counts: r.counts,
      })
    } catch (e: any) {
      setError(e?.message || 'Impossible de charger les outils OpenClaw')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const grouped = useMemo(() => {
    if (!data) return {} as Record<string, OCTool[]>
    const out: Record<string, OCTool[]> = {}
    for (const t of data.tools) {
      if (!out[t.group]) out[t.group] = []
      out[t.group].push(t)
    }
    return out
  }, [data])

  const toggleGlobal = async () => {
    if (!data || saving) return
    setSaving(true)
    try {
      await api.agent3SetOpenClawEnabledTools(null, !data.direct_tools_enabled)
      toast.success(
        !data.direct_tools_enabled
          ? 'Exposition directe OpenClaw activée'
          : 'Exposition directe OpenClaw désactivée'
      )
      await load()
    } catch (e: any) {
      toast.error(e?.message || 'Échec de la mise à jour')
    } finally {
      setSaving(false)
    }
  }

  const toggleOne = async (tool: OCTool) => {
    if (!data || saving) return
    const nowExposed = !tool.exposed_to_llm
    // Calcule la nouvelle liste
    const next = data.tools
      .map((t) => (t.name === tool.name ? { ...t, exposed_to_llm: nowExposed } : t))
      .filter((t) => t.exposed_to_llm)
      .map((t) => t.name)
    // Si TOUS sont exposés -> null (filtre 'all'), sinon liste explicite
    const payload = next.length === data.tools.length ? null : next
    setSaving(true)
    try {
      await api.agent3SetOpenClawEnabledTools(payload)
      toast.success(
        nowExposed ? `"${tool.name}" exposé au LLM` : `"${tool.name}" masqué au LLM`
      )
      await load()
    } catch (e: any) {
      toast.error(e?.message || 'Échec de la mise à jour')
    } finally {
      setSaving(false)
    }
  }

  const selectAll = async () => {
    if (!data || saving) return
    setSaving(true)
    try {
      await api.agent3SetOpenClawEnabledTools(null)  // null = tous
      toast.success('Tous les outils OpenClaw sont exposés')
      await load()
    } catch (e: any) {
      toast.error(e?.message || 'Échec')
    } finally {
      setSaving(false)
    }
  }

  const selectNone = async () => {
    if (!data || saving) return
    setSaving(true)
    try {
      await api.agent3SetOpenClawEnabledTools([])  // liste vide = aucun
      toast.success('Aucun outil OpenClaw exposé (safe mode)')
      await load()
    } catch (e: any) {
      toast.error(e?.message || 'Échec')
    } finally {
      setSaving(false)
    }
  }

  const selectSafeOnly = async () => {
    if (!data || saving) return
    const safe = data.tools.filter((t) => !t.is_destructive).map((t) => t.name)
    setSaving(true)
    try {
      await api.agent3SetOpenClawEnabledTools(safe)
      toast.success(`${safe.length} outils non destructifs exposés`)
      await load()
    } catch (e: any) {
      toast.error(e?.message || 'Échec')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <section style={{ marginTop: '2rem', padding: '1rem', color: 'var(--text-muted)' }}>
        Chargement des outils OpenClaw…
      </section>
    )
  }

  if (!data) {
    return (
      <section style={{ marginTop: '2rem', padding: '1rem', color: '#ef4444' }}>
        {error || 'Impossible de charger les outils OpenClaw.'}
      </section>
    )
  }

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
        background: 'linear-gradient(90deg, rgba(212,160,23,0.10), transparent)',
        borderBottom: '1px solid var(--border)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <div style={{ fontSize: '1.05rem', fontWeight: 600, color: '#d4a017' }}>
              🦞 Outils OpenClaw directs ({data.counts.exposed}/{data.counts.total} exposés)
            </div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
              Contrôle granulaire des 38 outils OpenClaw envoyés au LLM. Les outils{' '}
              <span style={{ color: '#f59e0b' }}>⚠️ destructifs</span> sont marqués.
              {data.counts.destructive > 0 && ` ${data.counts.destructive} destructifs existent.`}
            </div>
          </div>
          <button
            onClick={toggleGlobal}
            disabled={saving}
            style={{
              padding: '0.5rem 1rem',
              background: data.direct_tools_enabled ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)',
              border: `1px solid ${data.direct_tools_enabled ? 'rgba(16,185,129,0.4)' : 'rgba(239,68,68,0.4)'}`,
              color: data.direct_tools_enabled ? '#10b981' : '#ef4444',
              borderRadius: 8,
              fontSize: '0.85rem',
              fontWeight: 600,
              cursor: saving ? 'not-allowed' : 'pointer',
              opacity: saving ? 0.5 : 1,
              whiteSpace: 'nowrap',
            }}
          >
            {data.direct_tools_enabled ? '✓ Exposition activée' : '✕ Exposition désactivée'}
          </button>
        </div>
      </header>

      {/* Presets */}
      {data.direct_tools_enabled && (
        <div style={{
          padding: '0.65rem 1.25rem',
          background: 'rgba(255,255,255,0.02)',
          borderBottom: '1px solid var(--border)',
          display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center',
        }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Préselections :</span>
          <button onClick={selectAll} disabled={saving} style={presetBtnStyle}>Tous (38)</button>
          <button onClick={selectSafeOnly} disabled={saving} style={presetBtnStyle}>Non destructifs ({data.tools.filter(t => !t.is_destructive).length})</button>
          <button onClick={selectNone} disabled={saving} style={presetBtnStyle}>Aucun</button>
        </div>
      )}

      {/* Tools list grouped */}
      {data.direct_tools_enabled && Object.entries(grouped).map(([group, tools]) => (
        <div key={group} style={{ borderBottom: '1px solid var(--border)' }}>
          <div style={{
            padding: '0.55rem 1.25rem',
            fontSize: '0.78rem',
            color: 'var(--text-muted)',
            background: 'rgba(255,255,255,0.015)',
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
          }}>
            {GROUP_LABEL[group] || group} ({tools.filter(t => t.exposed_to_llm).length}/{tools.length})
          </div>
          <div style={{ padding: '0.5rem 0.75rem' }}>
            {tools.map((t) => (
              <label
                key={t.name}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '0.6rem',
                  padding: '0.5rem 0.6rem',
                  borderRadius: 6,
                  cursor: saving ? 'not-allowed' : 'pointer',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
              >
                <input
                  type="checkbox"
                  checked={t.exposed_to_llm}
                  disabled={saving}
                  onChange={() => toggleOne(t)}
                  style={{ marginTop: '0.2rem', cursor: saving ? 'not-allowed' : 'pointer' }}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: '0.85rem', fontWeight: 500, color: 'var(--text-primary)' }}>
                    {t.name}
                    {t.is_destructive && (
                      <span style={{ marginLeft: '0.4rem', color: '#f59e0b', fontSize: '0.72rem' }}>⚠️ destructif</span>
                    )}
                  </div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', lineHeight: 1.4, marginTop: '0.15rem' }}>
                    {t.description}
                  </div>
                </div>
              </label>
            ))}
          </div>
        </div>
      ))}

      {!data.direct_tools_enabled && (
        <div style={{ padding: '1.5rem 1.25rem', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
          Les outils OpenClaw directs sont désactivés. L'agent utilisera uniquement ses outils natifs
          Sylea et les skills ClawHub pour accomplir ses tâches.
        </div>
      )}
    </section>
  )
}

const presetBtnStyle: React.CSSProperties = {
  padding: '0.35rem 0.7rem',
  background: 'rgba(255,255,255,0.04)',
  border: '1px solid var(--border)',
  borderRadius: 6,
  color: 'var(--text-secondary)',
  fontSize: '0.75rem',
  cursor: 'pointer',
}
