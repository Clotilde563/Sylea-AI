import { useState, useEffect } from 'react'
import { api } from '../api/client'

type AdminUser = Awaited<ReturnType<typeof api.adminListUsers>>['items'][0]
type AdminStats = Awaited<ReturnType<typeof api.adminGetStats>>
type ActivityItem = Awaited<ReturnType<typeof api.adminRecentActivity>>['items'][0]

function StatCard({ label, value, color = 'var(--text-primary)' }: { label: string; value: string | number; color?: string }) {
  return (
    <div style={{
      background: 'var(--bg-surface)',
      border: '1px solid var(--border)',
      borderRadius: '0.75rem',
      padding: '1rem',
      minWidth: 120,
    }}>
      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {label}
      </div>
      <div style={{ fontSize: '1.8rem', fontWeight: 700, color, marginTop: 4 }}>
        {value}
      </div>
    </div>
  )
}

export default function AdminPage() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [activity, setActivity] = useState<ActivityItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'users' | 'activity'>('users')

  const reload = async () => {
    try {
      const [u, s, a] = await Promise.all([
        api.adminListUsers(100),
        api.adminGetStats(),
        api.adminRecentActivity(50),
      ])
      setUsers(u.items)
      setStats(s)
      setActivity(a.items)
      setLoading(false)
    } catch (e: any) {
      setError(e.message || 'Accès refusé (admin requis)')
      setLoading(false)
    }
  }

  useEffect(() => { reload() }, [])

  const changePlan = async (userId: string, plan: string) => {
    try {
      await api.adminSetPlan(userId, plan)
      reload()
    } catch (e: any) {
      alert(e.message)
    }
  }

  const toggleDisabled = async (u: AdminUser) => {
    try {
      if (u.disabled) await api.adminEnableUser(u.id)
      else await api.adminDisableUser(u.id)
      reload()
    } catch (e: any) {
      alert(e.message)
    }
  }

  if (loading) return <div className="page animate-fade-in" style={{ padding: '2rem' }}>Chargement...</div>
  if (error) return (
    <div className="page animate-fade-in" style={{ padding: '2rem', color: 'var(--danger)' }}>
      {error}
    </div>
  )

  return (
    <div className="page animate-fade-in" style={{ padding: '2rem', maxWidth: 1200, margin: '0 auto' }}>
      <h1 style={{ color: 'var(--text-primary)', marginBottom: '0.3rem' }}>Admin Dashboard</h1>
      <p style={{ color: 'var(--text-muted)', marginBottom: '2rem' }}>
        Vision globale des utilisateurs, usage et activité.
      </p>

      {/* Stats */}
      {stats && (
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '2rem' }}>
          <StatCard label="Total users" value={stats.users_total} />
          <StatCard label="Actifs" value={stats.users_active} color="#22c55e" />
          <StatCard label="Admins" value={stats.admins} color="#1a6fd8" />
          <StatCard label="Messages total" value={stats.messages_total.toLocaleString()} />
          <StatCard
            label={`Tokens ${stats.month_key}`}
            value={(stats.tokens_this_month / 1000).toFixed(0) + 'k'}
            color="#c8dff4"
          />
          <StatCard label="Requêtes ce mois" value={stats.requests_this_month.toLocaleString()} />
        </div>
      )}

      {/* Plans distribution */}
      {stats?.plans_distribution && (
        <div style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: '0.75rem',
          padding: '1rem',
          marginBottom: '2rem',
        }}>
          <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
            Distribution des plans
          </div>
          <div style={{ display: 'flex', gap: '1.5rem' }}>
            {Object.entries(stats.plans_distribution).map(([p, n]) => (
              <div key={p}>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{p}</div>
                <div style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--text-primary)' }}>{n}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', borderBottom: '1px solid var(--border)' }}>
        {(['users', 'activity'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              background: 'transparent',
              border: 'none',
              color: tab === t ? 'var(--accent-violet-light)' : 'var(--text-muted)',
              padding: '0.75rem 1rem',
              cursor: 'pointer',
              borderBottom: tab === t ? '2px solid var(--accent-violet-light)' : '2px solid transparent',
              fontWeight: 600,
              textTransform: 'capitalize',
            }}
          >
            {t === 'users' ? '👥 Utilisateurs' : '📊 Activité récente'}
          </button>
        ))}
      </div>

      {/* Users table */}
      {tab === 'users' && (
        <div style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: '0.75rem',
          overflow: 'auto',
        }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
            <thead>
              <tr style={{ background: 'rgba(255,255,255,0.03)' }}>
                {['Email', 'Plan', 'Créé le', 'Messages', 'Tokens mois', 'Statut', 'Actions'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '0.75rem', color: 'var(--text-muted)', fontWeight: 500, fontSize: '0.75rem' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '0.75rem', color: 'var(--text-primary)' }}>
                    {u.email}
                    {u.is_admin && <span style={{ marginLeft: 6, fontSize: '0.65rem', color: '#1a6fd8' }}>ADMIN</span>}
                  </td>
                  <td style={{ padding: '0.75rem' }}>
                    <select
                      value={u.plan}
                      onChange={e => changePlan(u.id, e.target.value)}
                      style={{
                        background: 'var(--bg-elevated)', color: 'var(--text-primary)',
                        border: '1px solid var(--border)', borderRadius: 6, padding: '4px 8px',
                        fontSize: '0.8rem',
                      }}
                    >
                      <option value="free">Free</option>
                      <option value="advanced">Avancé</option>
                      <option value="team">Team</option>
                    </select>
                  </td>
                  <td style={{ padding: '0.75rem', color: 'var(--text-secondary)' }}>
                    {new Date(u.created_at).toLocaleDateString('fr-FR')}
                  </td>
                  <td style={{ padding: '0.75rem', color: 'var(--text-secondary)' }}>{u.messages_total}</td>
                  <td style={{ padding: '0.75rem', color: 'var(--text-secondary)' }}>
                    {(u.usage_this_month.tokens / 1000).toFixed(1)}k
                  </td>
                  <td style={{ padding: '0.75rem' }}>
                    <span style={{
                      fontSize: '0.7rem',
                      padding: '2px 8px',
                      borderRadius: 10,
                      background: u.disabled ? 'rgba(239,68,68,0.2)' : 'rgba(34,197,94,0.15)',
                      color: u.disabled ? '#ef4444' : '#22c55e',
                    }}>
                      {u.disabled ? 'Désactivé' : 'Actif'}
                    </span>
                  </td>
                  <td style={{ padding: '0.75rem' }}>
                    <button
                      onClick={() => toggleDisabled(u)}
                      style={{
                        background: 'transparent',
                        color: u.disabled ? '#22c55e' : '#ef4444',
                        border: `1px solid ${u.disabled ? '#22c55e' : '#ef4444'}`,
                        padding: '4px 10px',
                        borderRadius: 6,
                        cursor: 'pointer',
                        fontSize: '0.75rem',
                      }}
                    >
                      {u.disabled ? 'Activer' : 'Désactiver'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {users.length === 0 && (
            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
              Aucun utilisateur.
            </div>
          )}
        </div>
      )}

      {/* Activity */}
      {tab === 'activity' && (
        <div style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: '0.75rem',
          overflow: 'hidden',
        }}>
          {activity.length === 0 && (
            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
              Aucune activité récente.
            </div>
          )}
          {activity.map(a => (
            <div key={a.id} style={{
              padding: '0.75rem 1rem',
              borderTop: '1px solid var(--border)',
              display: 'flex',
              alignItems: 'center',
              gap: '1rem',
              fontSize: '0.85rem',
            }}>
              <div style={{
                width: 8, height: 8, borderRadius: '50%',
                background: a.success ? '#22c55e' : '#ef4444',
              }} />
              <div style={{ flex: 1 }}>
                <div style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                  {a.action_type}
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                  {a.summary} · user {a.user_id?.slice(0, 8)}…
                </div>
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                {new Date(a.created_at).toLocaleString('fr-FR')}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
