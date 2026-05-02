import { useState, useEffect } from 'react'
import { api } from '../api/client'

type APIKey = Awaited<ReturnType<typeof api.listApiKeys>>['items'][0]

const AVAILABLE_SCOPES = [
  { value: 'chat:read', label: 'Lire les conversations' },
  { value: 'chat:write', label: 'Envoyer des messages' },
  { value: 'memory:read', label: 'Lire la mémoire' },
  { value: 'memory:write', label: 'Écrire en mémoire' },
  { value: 'admin', label: 'Admin complet' },
]

/** Section réutilisable : peut être rendue en page complète OU embarquée dans
 *  un autre conteneur (ex: onglet "Tokens API" de la page Intégrations).
 *  Passez `embedded={true}` pour omettre le wrapper et le titre. */
export function APIKeysSection({ embedded = false }: { embedded?: boolean }) {
  const [keys, setKeys] = useState<APIKey[]>([])
  const [name, setName] = useState('')
  const [selectedScopes, setSelectedScopes] = useState<string[]>(['chat:read', 'chat:write'])
  const [plaintextToken, setPlaintextToken] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = async () => {
    const r = await api.listApiKeys()
    setKeys(r.items)
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  const create = async () => {
    if (!name.trim()) { alert('Nom requis'); return }
    const r = await api.createApiKey(name.trim(), selectedScopes)
    if (r.ok && r.token) {
      setPlaintextToken(r.token)
      setName('')
      load()
    } else {
      alert(r.error || 'Erreur')
    }
  }

  const revoke = async (id: string) => {
    if (!confirm('Révoquer cette clé ? Les intégrations qui l\'utilisent cesseront de fonctionner.')) return
    await api.revokeApiKey(id)
    load()
  }

  const copyToken = () => {
    if (plaintextToken) {
      navigator.clipboard.writeText(plaintextToken)
      alert('Token copié !')
    }
  }

  const content = (
    <>
      {!embedded && (
        <>
          <h1 style={{ color: 'var(--text-primary)', marginBottom: '0.3rem' }}>API Keys</h1>
          <p style={{ color: 'var(--text-muted)', marginBottom: '2rem' }}>
            Tokens d'accès B2B pour appeler l'API Sylea depuis tes scripts et serveurs.
          </p>
        </>
      )}

      {plaintextToken && (
        <div style={{
          background: 'rgba(34,197,94,0.08)',
          border: '1px solid #22c55e',
          borderRadius: '0.75rem',
          padding: '1rem',
          marginBottom: '2rem',
        }}>
          <div style={{ color: '#22c55e', fontWeight: 600, marginBottom: 8 }}>
            ✓ Token créé — copie-le maintenant, il ne sera plus jamais affiché
          </div>
          <div style={{
            background: 'var(--bg-elevated)',
            padding: '10px 14px',
            borderRadius: 6,
            fontFamily: 'monospace',
            fontSize: '0.85rem',
            color: 'var(--text-primary)',
            wordBreak: 'break-all',
            display: 'flex',
            gap: 10,
            alignItems: 'center',
          }}>
            <span style={{ flex: 1 }}>{plaintextToken}</span>
            <button onClick={copyToken} style={{
              padding: '6px 12px', background: 'var(--accent-violet)', color: '#fff',
              border: 'none', borderRadius: 4, cursor: 'pointer',
            }}>
              📋 Copier
            </button>
          </div>
          <button
            onClick={() => setPlaintextToken(null)}
            style={{
              marginTop: 12, background: 'transparent', color: 'var(--text-muted)',
              border: 'none', cursor: 'pointer', fontSize: '0.8rem',
            }}
          >
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
          Créer une nouvelle clé
        </h2>
        <input
          type="text"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="Nom (ex: 'Mon script backup')"
          style={{
            width: '100%', padding: '8px 12px', marginBottom: '1rem',
            background: 'var(--bg-elevated)', border: '1px solid var(--border)',
            borderRadius: 6, color: 'var(--text-primary)',
          }}
        />
        <div style={{ marginBottom: '1rem' }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 6 }}>
            Permissions (scopes)
          </div>
          {AVAILABLE_SCOPES.map(s => (
            <label key={s.value} style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: 4, cursor: 'pointer',
            }}>
              <input
                type="checkbox"
                checked={selectedScopes.includes(s.value)}
                onChange={e => {
                  setSelectedScopes(prev =>
                    e.target.checked ? [...prev, s.value] : prev.filter(x => x !== s.value)
                  )
                }}
              />
              <span style={{ color: 'var(--text-primary)', fontSize: '0.85rem' }}>
                <code style={{ color: 'var(--accent-silver)' }}>{s.value}</code> — {s.label}
              </span>
            </label>
          ))}
        </div>
        <button onClick={create} style={{
          padding: '8px 20px', background: 'var(--accent-violet)', color: '#fff',
          border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 600,
        }}>
          Générer le token
        </button>
      </div>

      {/* Liste */}
      <h2 style={{ color: 'var(--text-primary)', fontSize: '1rem', marginBottom: '1rem' }}>
        Clés existantes ({keys.length})
      </h2>
      {loading && <div style={{ color: 'var(--text-muted)' }}>Chargement…</div>}
      {!loading && keys.length === 0 && (
        <div style={{
          background: 'var(--bg-surface)', border: '1px solid var(--border)',
          borderRadius: '0.75rem', padding: '2rem', textAlign: 'center',
          color: 'var(--text-muted)',
        }}>
          Aucune clé créée pour l'instant.
        </div>
      )}
      {keys.map(k => (
        <div key={k.id} style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: '0.75rem',
          padding: '1rem',
          marginBottom: '0.75rem',
          opacity: k.revoked ? 0.5 : 1,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <div style={{ color: 'var(--text-primary)', fontWeight: 600, marginBottom: 4 }}>
                {k.name}
                {k.revoked && <span style={{ marginLeft: 8, color: '#ef4444', fontSize: '0.75rem' }}>[RÉVOQUÉE]</span>}
              </div>
              <div style={{
                fontFamily: 'monospace', fontSize: '0.8rem',
                color: 'var(--accent-silver)', marginBottom: 4,
              }}>
                {k.prefix}••••
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                Scopes : {k.scopes.join(', ')}
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 4 }}>
                Créée {new Date(k.created_at).toLocaleDateString('fr-FR')}
                {k.last_used_at && ` · Dernière utilisation ${new Date(k.last_used_at).toLocaleDateString('fr-FR')}`}
              </div>
            </div>
            {!k.revoked && (
              <button
                onClick={() => revoke(k.id)}
                style={{
                  background: 'transparent', color: '#ef4444',
                  border: '1px solid #ef4444', padding: '4px 10px',
                  borderRadius: 6, cursor: 'pointer', fontSize: '0.75rem',
                }}
              >
                Révoquer
              </button>
            )}
          </div>
        </div>
      ))}

      {/* Docs */}
      <div style={{
        marginTop: '2rem',
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: '0.75rem',
        padding: '1.5rem',
      }}>
        <h3 style={{ color: 'var(--text-primary)', fontSize: '0.95rem', marginBottom: 8 }}>
          Utilisation
        </h3>
        <pre style={{
          background: 'var(--bg-elevated)', padding: '12px',
          borderRadius: 6, fontSize: '0.8rem', color: 'var(--text-primary)',
          overflow: 'auto', margin: 0,
        }}>{`curl -X POST https://api.sylea.ai/v1/chat \\
  -H "Authorization: Bearer sk-sylea-..." \\
  -H "Content-Type: application/json" \\
  -d '{"message": "Résume-moi ce lien"}'`}</pre>
      </div>
    </>
  )

  if (embedded) return content
  return (
    <div className="page animate-fade-in" style={{ padding: '2rem', maxWidth: 900, margin: '0 auto' }}>
      {content}
    </div>
  )
}

/** Page wrapper backward-compat : route /api-keys.
 *  La fonction est désormais accessible aussi via /integrations onglet "Tokens API". */
export default function APIKeysPage() {
  return <APIKeysSection embedded={false} />
}
