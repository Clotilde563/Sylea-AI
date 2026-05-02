/**
 * AuditLogPage — Historique des actions destructives de l'Agent 3.
 *
 * Liste des actions réellement exécutées (EMAIL, FILE_CREATE, CALENDAR_EVENT, ...),
 * avec leur statut (succès/échec), résumé non-sensible, et date.
 *
 * Source : GET /api/agent3/audit. Écriture : automatique via le dispatcher natif
 * dans api/agent3_security.py → audit_log_action() dans la table agent3_audit_log.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'

type AuditEntry = {
  id: string
  action_type: string
  summary: string
  success: boolean
  error_message: string
  created_at: string
}

const ACTION_LABEL: Record<string, { emoji: string; fr: string }> = {
  EMAIL: { emoji: '📧', fr: 'Email' },
  GMAIL_SEND: { emoji: '📧', fr: 'Email (Gmail)' },
  FILE_CREATE: { emoji: '📄', fr: 'Création fichier' },
  CALENDAR_EVENT: { emoji: '📅', fr: 'Événement Calendar' },
  DRIVE_SAVE: { emoji: '☁️', fr: 'Sauvegarde Drive' },
  CRON: { emoji: '⏰', fr: 'Tâche planifiée' },
  COMPUTER_USE: { emoji: '🖥️', fr: 'Computer Use' },
  CLAWHUB_INSTALL: { emoji: '🧩', fr: 'Installation skill' },
  CLAWHUB_PUBLISH: { emoji: '🚀', fr: 'Publication skill' },
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString('fr-FR', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

export default function AuditLogPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [countsByType, setCountsByType] = useState<Record<string, number>>({})
  const [successCount, setSuccessCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'success' | 'error'>('all')
  const [typeFilter, setTypeFilter] = useState<string>('all')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await api.agent3GetAudit(200)
      setEntries(r.entries)
      setCountsByType(r.counts_by_type)
      setSuccessCount(r.success_count)
    } catch (e: any) {
      setError(e?.message || 'Impossible de charger l\'historique')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const filtered = useMemo(() => {
    return entries.filter((e) => {
      if (filter === 'success' && !e.success) return false
      if (filter === 'error' && e.success) return false
      if (typeFilter !== 'all' && e.action_type !== typeFilter) return false
      return true
    })
  }, [entries, filter, typeFilter])

  const types = useMemo(() => Object.keys(countsByType).sort(), [countsByType])

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto', padding: '2rem 1rem' }}>
      {/* Header */}
      <div style={{ marginBottom: '1.5rem' }}>
        <p style={{
          color: 'var(--text-muted)', fontSize: '0.875rem',
          marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.1em',
        }}>
          Agent 3
        </p>
        <h1 style={{ fontSize: '1.75rem', color: 'var(--accent-silver)', marginBottom: '0.5rem' }}>
          Historique des actions
        </h1>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', lineHeight: 1.5 }}>
          Toutes les actions réellement exécutées par l'agent (emails, fichiers, événements, etc.).
          Conservé pour t'aider à comprendre ce que l'agent a fait en ton nom.
        </p>
      </div>

      {/* Stats + filtres */}
      <div style={{
        display: 'flex', gap: '0.75rem', flexWrap: 'wrap',
        marginBottom: '1.25rem', alignItems: 'center',
      }}>
        <div style={{
          padding: '0.55rem 0.85rem', background: 'rgba(16,185,129,0.08)',
          border: '1px solid rgba(16,185,129,0.25)', borderRadius: 8,
          fontSize: '0.82rem', color: '#10b981',
        }}>
          ✓ {successCount} réussies
        </div>
        <div style={{
          padding: '0.55rem 0.85rem', background: 'rgba(239,68,68,0.08)',
          border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8,
          fontSize: '0.82rem', color: '#ef4444',
        }}>
          ✕ {entries.length - successCount} échouées
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ display: 'flex', gap: '0.3rem' }}>
          {(['all', 'success', 'error'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              style={{
                padding: '0.4rem 0.75rem',
                background: filter === f ? 'var(--accent-silver, #c0c0c0)' : 'rgba(255,255,255,0.04)',
                color: filter === f ? '#000' : 'var(--text-muted)',
                border: '1px solid var(--border)',
                borderRadius: 6, fontSize: '0.78rem',
                fontWeight: filter === f ? 600 : 400,
                cursor: 'pointer',
              }}
            >
              {f === 'all' ? 'Toutes' : f === 'success' ? 'Réussies' : 'Échouées'}
            </button>
          ))}
        </div>
        <button
          onClick={load}
          disabled={loading}
          style={{
            padding: '0.4rem 0.75rem',
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid var(--border)',
            borderRadius: 6, color: 'var(--text-muted)',
            fontSize: '0.78rem', cursor: loading ? 'not-allowed' : 'pointer',
          }}
        >
          ↻ Rafraîchir
        </button>
      </div>

      {/* Type chips */}
      {types.length > 0 && (
        <div style={{ display: 'flex', gap: '0.3rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
          <button
            onClick={() => setTypeFilter('all')}
            style={{
              padding: '0.3rem 0.6rem',
              background: typeFilter === 'all' ? 'rgba(99,102,241,0.15)' : 'rgba(255,255,255,0.03)',
              border: '1px solid var(--border)', borderRadius: 16,
              color: typeFilter === 'all' ? '#6366f1' : 'var(--text-muted)',
              fontSize: '0.72rem', cursor: 'pointer',
            }}
          >
            Tous ({entries.length})
          </button>
          {types.map((t) => {
            const label = ACTION_LABEL[t] ?? { emoji: '•', fr: t }
            const active = typeFilter === t
            return (
              <button
                key={t}
                onClick={() => setTypeFilter(t)}
                style={{
                  padding: '0.3rem 0.6rem',
                  background: active ? 'rgba(99,102,241,0.15)' : 'rgba(255,255,255,0.03)',
                  border: '1px solid var(--border)', borderRadius: 16,
                  color: active ? '#6366f1' : 'var(--text-muted)',
                  fontSize: '0.72rem', cursor: 'pointer',
                }}
              >
                {label.emoji} {label.fr} ({countsByType[t]})
              </button>
            )
          })}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div style={{ textAlign: 'center', padding: '3rem 0', color: 'var(--text-muted)' }}>
          <div style={{
            width: 28, height: 28, margin: '0 auto 0.75rem',
            border: '3px solid rgba(255,255,255,0.08)',
            borderTopColor: 'var(--accent-silver, #c0c0c0)',
            borderRadius: '50%',
            animation: 'audit-spin 0.8s linear infinite',
          }} />
          Chargement…
          <style>{`@keyframes audit-spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div style={{
          padding: '0.9rem', background: 'rgba(239,68,68,0.08)',
          border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8,
          color: '#ef4444', fontSize: '0.85rem',
        }}>
          {error}
        </div>
      )}

      {/* Empty */}
      {!loading && !error && filtered.length === 0 && (
        <div style={{
          textAlign: 'center', padding: '3rem 0',
          color: 'var(--text-muted)', fontSize: '0.9rem',
        }}>
          {entries.length === 0
            ? 'Aucune action destructive exécutée pour le moment.'
            : 'Aucune action ne correspond à ces filtres.'}
        </div>
      )}

      {/* Liste */}
      {!loading && filtered.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {filtered.map((e) => {
            const label = ACTION_LABEL[e.action_type] ?? { emoji: '•', fr: e.action_type }
            return (
              <div
                key={e.id}
                style={{
                  padding: '0.75rem 1rem',
                  background: e.success ? 'rgba(16,185,129,0.04)' : 'rgba(239,68,68,0.05)',
                  border: `1px solid ${e.success ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.25)'}`,
                  borderRadius: 8,
                  display: 'flex', alignItems: 'flex-start', gap: '0.75rem',
                }}
              >
                <span style={{ fontSize: '1.25rem', flexShrink: 0, marginTop: '0.1rem' }}>
                  {label.emoji}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'baseline', flexWrap: 'wrap' }}>
                    <span style={{
                      fontSize: '0.88rem', fontWeight: 600,
                      color: e.success ? '#10b981' : '#ef4444',
                    }}>
                      {label.fr}
                    </span>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                      {formatDate(e.created_at)}
                    </span>
                    {!e.success && (
                      <span style={{
                        fontSize: '0.7rem', color: '#ef4444',
                        background: 'rgba(239,68,68,0.1)', padding: '2px 6px', borderRadius: 4,
                      }}>
                        échec
                      </span>
                    )}
                  </div>
                  {e.summary && (
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary, #d0d0d0)', marginTop: '0.2rem', lineHeight: 1.4 }}>
                      {e.summary}
                    </div>
                  )}
                  {!e.success && e.error_message && (
                    <div style={{ fontSize: '0.72rem', color: '#ef4444', marginTop: '0.25rem', fontStyle: 'italic' }}>
                      {e.error_message.slice(0, 240)}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
