import { useState, useEffect } from 'react'
import { api } from '../api/client'

type Webhook = Awaited<ReturnType<typeof api.listWebhooks>>['items'][0]
type Delivery = Awaited<ReturnType<typeof api.webhookDeliveries>>['items'][0]

const AVAILABLE_EVENTS = [
  { value: 'message.completed', label: 'Message agent complété' },
  { value: 'tool.invoked', label: 'Tool/skill exécuté' },
  { value: 'quota.warning', label: 'Quota atteint 80%' },
  { value: 'quota.exceeded', label: 'Quota dépassé' },
  { value: 'task_plan.created', label: 'Plan auto généré' },
  { value: 'feedback.received', label: 'Feedback reçu' },
  { value: '*', label: 'Tous les événements' },
]

export default function WebhooksPage() {
  const [webhooks, setWebhooks] = useState<Webhook[]>([])
  const [deliveries, setDeliveries] = useState<Delivery[]>([])
  const [url, setUrl] = useState('')
  const [events, setEvents] = useState<string[]>(['message.completed'])
  const [secret, setSecret] = useState<string | null>(null)
  const [tab, setTab] = useState<'subs' | 'deliveries'>('subs')

  const load = async () => {
    const [w, d] = await Promise.all([
      api.listWebhooks(),
      api.webhookDeliveries(50),
    ])
    setWebhooks(w.items)
    setDeliveries(d.items)
  }

  useEffect(() => { load() }, [])

  const create = async () => {
    if (!url.trim() || events.length === 0) {
      alert('URL + au moins 1 event requis')
      return
    }
    const r = await api.createWebhook(url.trim(), events)
    if (r.ok && r.secret) {
      setSecret(r.secret)
      setUrl('')
      load()
    } else {
      alert(r.error || 'Erreur')
    }
  }

  const del = async (id: string) => {
    if (!confirm('Supprimer ce webhook ?')) return
    await api.deleteWebhook(id)
    load()
  }

  return (
    <div className="page animate-fade-in" style={{ padding: '2rem', maxWidth: 1000, margin: '0 auto' }}>
      <h1 style={{ color: 'var(--text-primary)', marginBottom: '0.3rem' }}>Webhooks</h1>
      <p style={{ color: 'var(--text-muted)', marginBottom: '2rem' }}>
        Recevez des notifications HTTP en temps réel sur vos événements Sylea.
      </p>

      {secret && (
        <div style={{
          background: 'rgba(34,197,94,0.08)',
          border: '1px solid #22c55e',
          borderRadius: '0.75rem',
          padding: '1rem',
          marginBottom: '2rem',
        }}>
          <div style={{ color: '#22c55e', fontWeight: 600, marginBottom: 8 }}>
            ✓ Webhook créé — voici le secret HMAC (à stocker pour vérifier les signatures)
          </div>
          <div style={{
            background: 'var(--bg-elevated)', padding: '10px 14px', borderRadius: 6,
            fontFamily: 'monospace', fontSize: '0.85rem', color: 'var(--text-primary)',
            wordBreak: 'break-all',
          }}>
            {secret}
          </div>
          <button onClick={() => setSecret(null)} style={{
            marginTop: 12, background: 'transparent', color: 'var(--text-muted)',
            border: 'none', cursor: 'pointer', fontSize: '0.8rem',
          }}>
            Fermer
          </button>
        </div>
      )}

      {/* Création */}
      <div style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: '0.75rem',
        padding: '1.5rem',
        marginBottom: '2rem',
      }}>
        <h2 style={{ color: 'var(--text-primary)', fontSize: '1rem', marginBottom: '1rem' }}>
          Nouveau webhook
        </h2>
        <input
          type="url"
          value={url}
          onChange={e => setUrl(e.target.value)}
          placeholder="https://api.monserveur.com/webhook"
          style={{
            width: '100%', padding: '8px 12px', marginBottom: '1rem',
            background: 'var(--bg-elevated)', border: '1px solid var(--border)',
            borderRadius: 6, color: 'var(--text-primary)',
          }}
        />
        <div style={{ marginBottom: '1rem' }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 6 }}>
            Événements à souscrire
          </div>
          {AVAILABLE_EVENTS.map(e => (
            <label key={e.value} style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: 4, cursor: 'pointer',
            }}>
              <input
                type="checkbox"
                checked={events.includes(e.value)}
                onChange={ev => {
                  setEvents(prev =>
                    ev.target.checked ? [...prev, e.value] : prev.filter(x => x !== e.value)
                  )
                }}
              />
              <span style={{ fontSize: '0.85rem', color: 'var(--text-primary)' }}>
                <code style={{ color: 'var(--accent-silver)' }}>{e.value}</code>
                <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>— {e.label}</span>
              </span>
            </label>
          ))}
        </div>
        <button onClick={create} style={{
          padding: '8px 20px', background: 'var(--accent-violet)', color: '#fff',
          border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 600,
        }}>
          Créer
        </button>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: '1rem', borderBottom: '1px solid var(--border)' }}>
        {(['subs', 'deliveries'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              background: 'transparent', border: 'none',
              color: tab === t ? 'var(--accent-violet-light)' : 'var(--text-muted)',
              padding: '0.75rem 1rem', cursor: 'pointer',
              borderBottom: tab === t ? '2px solid var(--accent-violet-light)' : '2px solid transparent',
              fontWeight: 600,
            }}
          >
            {t === 'subs' ? `Abonnements (${webhooks.length})` : `Livraisons récentes (${deliveries.length})`}
          </button>
        ))}
      </div>

      {tab === 'subs' && (
        <>
          {webhooks.length === 0 && (
            <div style={{
              background: 'var(--bg-surface)', border: '1px solid var(--border)',
              borderRadius: '0.75rem', padding: '2rem', textAlign: 'center',
              color: 'var(--text-muted)',
            }}>
              Aucun webhook configuré.
            </div>
          )}
          {webhooks.map(w => (
            <div key={w.id} style={{
              background: 'var(--bg-surface)', border: '1px solid var(--border)',
              borderRadius: '0.75rem', padding: '1rem', marginBottom: '0.75rem',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <div style={{
                    fontFamily: 'monospace', fontSize: '0.85rem',
                    color: 'var(--text-primary)', marginBottom: 4,
                  }}>
                    {w.target_url}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: 4 }}>
                    {w.events.map(e => (
                      <code key={e} style={{
                        background: 'rgba(26,111,216,0.15)', padding: '2px 6px',
                        borderRadius: 4, marginRight: 4, color: 'var(--accent-violet-light)',
                      }}>
                        {e}
                      </code>
                    ))}
                  </div>
                  {w.failures_count > 0 && (
                    <div style={{ fontSize: '0.7rem', color: '#ef4444' }}>
                      ⚠ {w.failures_count} échecs
                      {w.last_error && ` : ${w.last_error.slice(0, 80)}`}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => del(w.id)}
                  style={{
                    background: 'transparent', color: '#ef4444',
                    border: '1px solid #ef4444', padding: '4px 10px',
                    borderRadius: 6, cursor: 'pointer', fontSize: '0.75rem',
                  }}
                >
                  Supprimer
                </button>
              </div>
            </div>
          ))}
        </>
      )}

      {tab === 'deliveries' && (
        <div style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: '0.75rem',
          overflow: 'hidden',
        }}>
          {deliveries.length === 0 && (
            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
              Aucune livraison.
            </div>
          )}
          {deliveries.map(d => (
            <div key={d.id} style={{
              padding: '0.75rem 1rem', borderTop: '1px solid var(--border)',
              display: 'flex', alignItems: 'center', gap: '1rem', fontSize: '0.85rem',
            }}>
              <span style={{
                padding: '2px 8px', borderRadius: 10,
                background: (d.status_code && d.status_code >= 200 && d.status_code < 300)
                  ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
                color: (d.status_code && d.status_code >= 200 && d.status_code < 300) ? '#22c55e' : '#ef4444',
                fontSize: '0.7rem', fontWeight: 600,
              }}>
                {d.status_code || 'ERR'}
              </span>
              <code style={{ color: 'var(--accent-silver)' }}>{d.event}</code>
              <span style={{ flex: 1, color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                {d.error || 'OK'}
              </span>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                {new Date(d.attempted_at).toLocaleString('fr-FR')}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
