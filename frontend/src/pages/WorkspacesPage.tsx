import { useState, useEffect } from 'react'
import { api } from '../api/client'

type Workspace = Awaited<ReturnType<typeof api.listWorkspaces>>['items'][0]
type Member = Awaited<ReturnType<typeof api.listWorkspaceMembers>>['members'][0]
type SharedMem = Awaited<ReturnType<typeof api.listWorkspaceSharedMemory>>['items'][0]

/** Composant reutilisable : peut etre rendu en page complete (avec wrapper +
 *  titre) OU embarque dans un autre conteneur (ex: onglet du reseau Sylea).
 *  Passez `embedded={true}` pour omettre le wrapper et le titre. */
export function WorkspacesSection({ embedded = false }: { embedded?: boolean }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [selected, setSelected] = useState<Workspace | null>(null)
  const [members, setMembers] = useState<Member[]>([])
  const [memory, setMemory] = useState<SharedMem[]>([])
  const [newName, setNewName] = useState('')
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'member' | 'admin'>('member')
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')

  const loadWorkspaces = async () => {
    const r = await api.listWorkspaces()
    setWorkspaces(r.items)
  }

  const loadMembers = async (wsId: string) => {
    const r = await api.listWorkspaceMembers(wsId)
    setMembers(r.members)
    const m = await api.listWorkspaceSharedMemory(wsId)
    setMemory(m.items)
  }

  useEffect(() => { loadWorkspaces() }, [])
  useEffect(() => { if (selected) loadMembers(selected.id) }, [selected])

  const create = async () => {
    if (!newName.trim()) return
    const r = await api.createWorkspace(newName.trim())
    if (r.ok) {
      setNewName('')
      loadWorkspaces()
    } else {
      alert(r.error)
    }
  }

  const del = async (id: string) => {
    if (!confirm('Supprimer ce workspace ?')) return
    await api.deleteWorkspace(id)
    if (selected?.id === id) setSelected(null)
    loadWorkspaces()
  }

  const invite = async () => {
    if (!selected || !inviteEmail.trim()) return
    const r = await api.addWorkspaceMember(selected.id, inviteEmail.trim(), inviteRole)
    if (r.ok) {
      setInviteEmail('')
      loadMembers(selected.id)
    } else {
      alert(r.error)
    }
  }

  const kick = async (uid: string) => {
    if (!selected) return
    if (!confirm('Retirer ce membre ?')) return
    await api.removeWorkspaceMember(selected.id, uid)
    loadMembers(selected.id)
  }

  const addMemory = async () => {
    if (!selected || !newKey.trim() || !newValue.trim()) return
    const r = await api.shareWorkspaceMemory(selected.id, newKey, newValue)
    if (r.ok) {
      setNewKey(''); setNewValue('')
      loadMembers(selected.id)
    }
  }

  const grid = (
    <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: '1.5rem' }}>
        {/* Liste workspaces */}
        <div>
          <div style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            borderRadius: '0.75rem',
            padding: '1rem',
            marginBottom: '1rem',
          }}>
            <input
              type="text"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder="Nom du workspace"
              onKeyDown={e => e.key === 'Enter' && create()}
              style={{
                width: '100%', padding: '8px', borderRadius: 6,
                background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                color: 'var(--text-primary)', marginBottom: 8,
              }}
            />
            <button onClick={create} style={{
              width: '100%', padding: '8px',
              background: 'var(--accent-violet)', color: '#fff',
              border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 600,
            }}>
              + Créer
            </button>
          </div>

          {workspaces.map(w => (
            <div
              key={w.id}
              onClick={() => setSelected(w)}
              style={{
                background: selected?.id === w.id ? 'rgba(26,111,216,0.1)' : 'var(--bg-surface)',
                border: `1px solid ${selected?.id === w.id ? 'var(--accent-violet)' : 'var(--border)'}`,
                borderRadius: '0.5rem',
                padding: '0.75rem',
                marginBottom: '0.5rem',
                cursor: 'pointer',
                transition: 'all 0.15s',
              }}
            >
              <div style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{w.name}</div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', marginTop: 4 }}>
                {w.my_role}
              </div>
            </div>
          ))}
          {workspaces.length === 0 && (
            <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              Aucun workspace.
            </div>
          )}
        </div>

        {/* Détails workspace sélectionné */}
        {selected ? (
          <div>
            <div style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: '0.75rem',
              padding: '1.5rem',
              marginBottom: '1rem',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <h2 style={{ color: 'var(--text-primary)', margin: 0 }}>{selected.name}</h2>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 4 }}>
                    Créé le {new Date(selected.created_at).toLocaleDateString('fr-FR')}
                  </div>
                </div>
                {selected.my_role === 'owner' && (
                  <button
                    onClick={() => del(selected.id)}
                    style={{
                      background: 'transparent', color: '#ef4444',
                      border: '1px solid #ef4444', padding: '6px 12px',
                      borderRadius: 6, cursor: 'pointer', fontSize: '0.8rem',
                    }}
                  >
                    🗑 Supprimer
                  </button>
                )}
              </div>
            </div>

            {/* Membres */}
            <div style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: '0.75rem',
              padding: '1.5rem',
              marginBottom: '1rem',
            }}>
              <h3 style={{ color: 'var(--text-primary)', fontSize: '1rem', marginBottom: '1rem' }}>
                Membres ({members.length})
              </h3>
              {(selected.my_role === 'owner' || selected.my_role === 'admin') && (
                <div style={{ display: 'flex', gap: 8, marginBottom: '1rem' }}>
                  <input
                    type="text"
                    value={inviteEmail}
                    onChange={e => setInviteEmail(e.target.value)}
                    placeholder="user_id à inviter"
                    style={{
                      flex: 1, padding: '6px 10px', borderRadius: 6,
                      background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                      color: 'var(--text-primary)',
                    }}
                  />
                  <select
                    value={inviteRole}
                    onChange={e => setInviteRole(e.target.value as any)}
                    style={{
                      padding: '6px', borderRadius: 6,
                      background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                      color: 'var(--text-primary)',
                    }}
                  >
                    <option value="member">Member</option>
                    <option value="admin">Admin</option>
                  </select>
                  <button onClick={invite} style={{
                    padding: '6px 16px', background: 'var(--accent-violet)',
                    color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer',
                  }}>
                    Inviter
                  </button>
                </div>
              )}
              {members.map(m => (
                <div key={m.user_id} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '0.5rem', borderTop: '1px solid var(--border)',
                }}>
                  <div>
                    <span style={{ color: 'var(--text-primary)' }}>{m.user_id.slice(0, 16)}</span>
                    <span style={{ marginLeft: 8, fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                      {m.role}
                    </span>
                  </div>
                  {selected.my_role === 'owner' && m.role !== 'owner' && (
                    <button
                      onClick={() => kick(m.user_id)}
                      style={{
                        background: 'transparent', color: '#ef4444',
                        border: 'none', cursor: 'pointer', fontSize: '0.8rem',
                      }}
                    >
                      Retirer
                    </button>
                  )}
                </div>
              ))}
            </div>

            {/* Mémoire partagée */}
            <div style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: '0.75rem',
              padding: '1.5rem',
            }}>
              <h3 style={{ color: 'var(--text-primary)', fontSize: '1rem', marginBottom: '1rem' }}>
                Mémoire partagée ({memory.length})
              </h3>
              <div style={{ display: 'flex', gap: 8, marginBottom: '1rem' }}>
                <input
                  type="text"
                  value={newKey}
                  onChange={e => setNewKey(e.target.value)}
                  placeholder="Clé (ex: style-marketing)"
                  style={{
                    flex: 1, padding: '6px 10px', borderRadius: 6,
                    background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                    color: 'var(--text-primary)',
                  }}
                />
                <input
                  type="text"
                  value={newValue}
                  onChange={e => setNewValue(e.target.value)}
                  placeholder="Valeur"
                  style={{
                    flex: 2, padding: '6px 10px', borderRadius: 6,
                    background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                    color: 'var(--text-primary)',
                  }}
                />
                <button onClick={addMemory} style={{
                  padding: '6px 16px', background: 'var(--accent-violet)',
                  color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer',
                }}>
                  +
                </button>
              </div>
              {memory.map(m => (
                <div key={m.id} style={{
                  padding: '0.5rem', borderTop: '1px solid var(--border)', fontSize: '0.85rem',
                }}>
                  <div style={{ color: 'var(--accent-silver)', fontWeight: 500 }}>{m.key}</div>
                  <div style={{ color: 'var(--text-secondary)', marginTop: 2 }}>{m.value}</div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div style={{
            background: 'var(--bg-surface)', border: '1px solid var(--border)',
            borderRadius: '0.75rem', padding: '3rem', textAlign: 'center',
            color: 'var(--text-muted)',
          }}>
            Sélectionne un workspace pour voir ses détails.
          </div>
        )}
      </div>
  )

  if (embedded) return grid
  return (
    <div className="page animate-fade-in" style={{ padding: '2rem', maxWidth: 1200, margin: '0 auto' }}>
      <h1 style={{ color: 'var(--text-primary)', marginBottom: '0.3rem' }}>Workspaces</h1>
      <p style={{ color: 'var(--text-muted)', marginBottom: '2rem' }}>
        Collabore avec ton équipe — mémoire et skills partagés.
      </p>
      {grid}
    </div>
  )
}

/** Page wrapper backward-compat : route /workspaces.
 *  TODO: la route est conservee pour bookmark/tests existants mais peut etre
 *  retiree quand l'onglet "Equipes" du Reseau Sylea est devenu le seul point
 *  d'entree. */
export default function WorkspacesPage() {
  return <WorkspacesSection embedded={false} />
}
