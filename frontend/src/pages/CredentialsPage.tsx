/**
 * CredentialsPage — page /integrations enrichie avec Command Bar universelle.
 *
 * 3 sections :
 *   1. Command Bar : barre de recherche unique, detecte nom app OU cle API collee
 *   2. Grid des providers avec etat connecte/non connecte
 *   3. Drawer d'edition ouverture au clic sur un provider
 *
 * Communication backend : /api/credentials/*
 * (complementaire a /api/integrations/* qui gere OAuth Google/GitHub).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import { useToast } from '../components/Toast'

type Provider = {
  slug: string
  display_name: string
  description: string
  category: string
  logo_emoji: string
  aliases: string[]
  fields: Array<{
    key: string
    label: string
    type: string
    required: boolean
    pattern?: string
    pattern_hint?: string
  }>
  tutorial_url: string
  tutorial_steps: string[]
  used_by_skills: string[]
}

type Credential = {
  provider_slug: string
  field_key: string
  preview: string
  metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string
  last_used_at: string | null
  last_tested_at: string | null
  last_test_ok: boolean | null
  expires_at: string | null
}

type DetectResult = Awaited<ReturnType<typeof api.credentialsDetect>>

const CATEGORY_LABELS: Record<string, { label: string; color: string }> = {
  ai: { label: '🤖 IA / LLM', color: '#a855f7' },
  payments: { label: '💳 Paiements', color: '#10b981' },
  comms: { label: '💬 Communication', color: '#3b82f6' },
  productivity: { label: '📝 Productivité', color: '#f59e0b' },
  dev: { label: '🛠️ Dev / Code', color: '#6366f1' },
  data: { label: '📊 Data', color: '#06b6d4' },
  crm: { label: '👥 CRM', color: '#ec4899' },
}

/** Section réutilisable : peut être rendue en page complète OU embarquée dans
 *  un autre conteneur (ex: onglet "Clés API" de la page Intégrations).
 *  Passez `embedded={true}` pour omettre le wrapper et le header. */
export function CredentialsSection({ embedded = false }: { embedded?: boolean }) {
  const { toast } = useToast()
  const [providers, setProviders] = useState<Provider[]>([])
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedProvider, setSelectedProvider] = useState<Provider | null>(null)
  const [filterCategory, setFilterCategory] = useState<string>('all')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [p, c] = await Promise.all([
        api.credentialsListProviders(),
        api.credentialsListMine(),
      ])
      setProviders(p.providers)
      setCredentials(c.credentials)
    } catch (e: any) {
      setError(e?.message || 'Impossible de charger')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // Index : set des slugs connectés (au moins 1 credential)
  const connectedSlugs = useMemo(
    () => new Set(credentials.map(c => c.provider_slug)),
    [credentials],
  )

  // Credentials groupées par provider pour le drawer
  const credsByProvider = useMemo(() => {
    const m: Record<string, Credential[]> = {}
    for (const c of credentials) {
      if (!m[c.provider_slug]) m[c.provider_slug] = []
      m[c.provider_slug].push(c)
    }
    return m
  }, [credentials])

  // Filtrage par catégorie
  const visibleProviders = useMemo(() => {
    if (filterCategory === 'all') return providers
    return providers.filter(p => p.category === filterCategory)
  }, [providers, filterCategory])

  const categories = useMemo(() => {
    const cats = new Set<string>()
    providers.forEach(p => cats.add(p.category))
    return Array.from(cats).sort()
  }, [providers])

  const content = (
    <>
      {!embedded && (
        <header style={{ marginBottom: '1.5rem' }}>
          <p style={{
            color: 'var(--text-muted)', fontSize: '0.875rem',
            marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.1em',
          }}>
            Sylea
          </p>
          <h1 style={{ fontSize: '1.75rem', color: 'var(--accent-silver)', margin: 0 }}>
            Clés API tierces
          </h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', lineHeight: 1.5, marginTop: '0.3rem' }}>
            Coffre-fort universel. Tape le nom d'une app ou colle une clé API —
            elle sera détectée, chiffrée et validée automatiquement.
          </p>
        </header>
      )}

      {/* ── Command Bar ────────────────────────────────────────────── */}
      <IntegrationsCommandBar
        providers={providers}
        onSaved={async (msg) => {
          toast.success(msg)
          await load()
        }}
        onError={(msg) => toast.error(msg)}
        onSelectProvider={setSelectedProvider}
      />

      {/* ── Section : credentials requises par skills ClawHub ──────── */}
      <SkillCredentialsSection
        onSaved={async (msg) => {
          toast.success(msg)
          await load()
        }}
        onError={(msg) => toast.error(msg)}
        onSelectProvider={(slug) => {
          const p = providers.find(pp => pp.slug === slug)
          if (p) setSelectedProvider(p)
        }}
      />

      {/* ── Filtres catégorie ──────────────────────────────────────── */}
      {!loading && providers.length > 0 && (
        <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
          <button
            onClick={() => setFilterCategory('all')}
            style={chipStyle(filterCategory === 'all')}
          >
            Tous ({providers.length})
          </button>
          {categories.map(cat => {
            const meta = CATEGORY_LABELS[cat] ?? { label: cat, color: '#888' }
            const count = providers.filter(p => p.category === cat).length
            return (
              <button
                key={cat}
                onClick={() => setFilterCategory(cat)}
                style={chipStyle(filterCategory === cat, meta.color)}
              >
                {meta.label} ({count})
              </button>
            )
          })}
        </div>
      )}

      {/* ── Loading / Error ───────────────────────────────────────── */}
      {loading && (
        <div style={{ textAlign: 'center', padding: '3rem 0', color: 'var(--text-muted)' }}>
          Chargement des intégrations…
        </div>
      )}

      {error && !loading && (
        <div style={{
          padding: '0.9rem', background: 'rgba(239,68,68,0.08)',
          border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8,
          color: '#ef4444', fontSize: '0.85rem',
        }}>
          {error}
        </div>
      )}

      {/* ── Grid des providers ────────────────────────────────────── */}
      {!loading && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
          gap: '0.75rem',
        }}>
          {visibleProviders.map(p => {
            const connected = connectedSlugs.has(p.slug)
            const catMeta = CATEGORY_LABELS[p.category] ?? { label: p.category, color: '#888' }
            return (
              <button
                key={p.slug}
                onClick={() => setSelectedProvider(p)}
                style={{
                  padding: '1rem',
                  background: connected ? 'rgba(16,185,129,0.06)' : 'rgba(255,255,255,0.02)',
                  border: connected
                    ? '1px solid rgba(16,185,129,0.3)'
                    : '1px solid var(--border)',
                  borderRadius: 10,
                  textAlign: 'left',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                  position: 'relative',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = connected ? 'rgba(16,185,129,0.1)' : 'rgba(255,255,255,0.04)')}
                onMouseLeave={e => (e.currentTarget.style.background = connected ? 'rgba(16,185,129,0.06)' : 'rgba(255,255,255,0.02)')}
              >
                {connected && (
                  <span style={{
                    position: 'absolute', top: 8, right: 8,
                    width: 8, height: 8, borderRadius: '50%', background: '#10b981',
                  }} />
                )}
                <div style={{ fontSize: '1.8rem', marginBottom: '0.4rem' }}>{p.logo_emoji}</div>
                <div style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {p.display_name}
                </div>
                <div style={{ fontSize: '0.72rem', color: catMeta.color, marginTop: '0.2rem' }}>
                  {catMeta.label}
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.4rem', lineHeight: 1.35 }}>
                  {p.description}
                </div>
                <div style={{ fontSize: '0.7rem', color: connected ? '#10b981' : 'var(--text-muted)', marginTop: '0.5rem' }}>
                  {connected ? '✓ Connecté' : 'Non connecté'}
                </div>
              </button>
            )
          })}
        </div>
      )}

      {/* ── Drawer ─────────────────────────────────────────────────── */}
      {selectedProvider && (
        <ProviderDrawer
          provider={selectedProvider}
          credentials={credsByProvider[selectedProvider.slug] || []}
          onClose={() => setSelectedProvider(null)}
          onSaved={async (msg) => {
            toast.success(msg)
            setSelectedProvider(null)
            await load()
          }}
          onDeleted={async () => {
            toast.success(`${selectedProvider.display_name} déconnecté`)
            setSelectedProvider(null)
            await load()
          }}
          onError={(msg) => toast.error(msg)}
        />
      )}
    </>
  )

  if (embedded) return content
  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '2rem 1rem' }}>
      {content}
    </div>
  )
}

/** Page wrapper backward-compat : route /credentials.
 *  La fonction est désormais accessible aussi via /integrations onglet "Clés API". */
export default function CredentialsPage() {
  return <CredentialsSection embedded={false} />
}

const chipStyle = (active: boolean, color?: string): React.CSSProperties => ({
  padding: '0.35rem 0.8rem',
  background: active ? (color ? `${color}25` : 'rgba(255,255,255,0.08)') : 'rgba(255,255,255,0.03)',
  border: `1px solid ${active ? (color || 'var(--accent-silver)') : 'var(--border)'}`,
  borderRadius: 16,
  color: active ? (color || 'var(--accent-silver)') : 'var(--text-muted)',
  fontSize: '0.75rem',
  fontWeight: active ? 600 : 400,
  cursor: 'pointer',
})


// ═════════════════════════════════════════════════════════════════════════════
// Command Bar : détection automatique clé API vs nom app
// ═════════════════════════════════════════════════════════════════════════════

function IntegrationsCommandBar(props: {
  providers: Provider[]
  onSaved: (msg: string) => void | Promise<void>
  onError: (msg: string) => void
  onSelectProvider: (p: Provider) => void
}) {
  const [input, setInput] = useState('')
  const [result, setResult] = useState<DetectResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const debounceRef = useRef<number | null>(null)

  const detect = useCallback(async (val: string) => {
    if (!val.trim()) {
      setResult(null)
      return
    }
    setLoading(true)
    try {
      const r = await api.credentialsDetect(val)
      setResult(r)
    } catch {
      setResult(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current)
    debounceRef.current = window.setTimeout(() => detect(input), 250)
    return () => {
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current)
    }
  }, [input, detect])

  const isApiKey = result?.type === 'api_key_detected'
  const hasSuggestions = (result?.suggestions?.length ?? 0) > 0 || (result?.matches?.length ?? 0) > 0

  const handleQuickSave = async () => {
    if (!isApiKey || !result) return
    setSaving(true)
    try {
      const first = result.matches[0]
      const resp = await api.credentialsQuickSave(input, first.provider_slug, first.field_key)
      if (resp.success) {
        const label = first.provider_display_name
        const vmsg = resp.validated ? 'connecté et validé' : 'enregistré (validation impossible)'
        await props.onSaved(`${label} ${vmsg}`)
        setInput('')
        setResult(null)
      } else {
        props.onError(resp.message || resp.test_message || 'Échec de la sauvegarde')
      }
    } catch (e: any) {
      props.onError(e?.message || 'Erreur')
    } finally {
      setSaving(false)
    }
  }

  const handleSelectSuggestion = (slug: string) => {
    const p = props.providers.find(pp => pp.slug === slug)
    if (p) {
      props.onSelectProvider(p)
      setInput('')
      setResult(null)
    }
  }

  return (
    <div style={{ position: 'relative', marginBottom: '1.25rem' }}>
      <div style={{ position: 'relative' }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && isApiKey && !saving) {
              e.preventDefault()
              handleQuickSave()
            }
            if (e.key === 'Escape') {
              setInput('')
              setResult(null)
            }
          }}
          placeholder="🔍 Tape le nom d'une app (ex: stripe) ou colle une clé API (sk_live_..., xoxb-...)"
          style={{
            width: '100%',
            padding: '0.85rem 1rem',
            background: 'rgba(255,255,255,0.04)',
            border: `1px solid ${isApiKey ? 'rgba(16,185,129,0.5)' : 'var(--border)'}`,
            borderRadius: 10,
            color: 'var(--text-primary)',
            fontSize: '0.95rem',
            outline: 'none',
            fontFamily: isApiKey ? '"Fira Code", monospace' : undefined,
          }}
        />
        {loading && (
          <span style={{
            position: 'absolute', right: 12, top: '50%',
            transform: 'translateY(-50%)',
            fontSize: '0.75rem', color: 'var(--text-muted)',
          }}>…</span>
        )}
      </div>

      {/* Preview de détection clé API */}
      {isApiKey && result && result.matches.length > 0 && (
        <div style={{
          marginTop: '0.5rem',
          padding: '0.85rem 1rem',
          background: 'rgba(16,185,129,0.08)',
          border: '1px solid rgba(16,185,129,0.35)',
          borderRadius: 10,
          display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap',
        }}>
          <span style={{ fontSize: '1.5rem' }}>{result.matches[0].provider_logo_emoji}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: '0.9rem', color: '#10b981', fontWeight: 600 }}>
              ✓ {result.matches[0].provider_display_name} détecté
              {result.matches[0].metadata?.environment && (
                <span style={{ fontSize: '0.75rem', opacity: 0.8, marginLeft: '0.4rem' }}>
                  ({result.matches[0].metadata.environment})
                </span>
              )}
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.15rem' }}>
              Pression Entrée ou clic sur le bouton pour tester et enregistrer.
            </div>
          </div>
          <button
            onClick={handleQuickSave}
            disabled={saving}
            style={{
              padding: '0.5rem 1rem',
              background: '#10b981',
              border: 'none', borderRadius: 8,
              color: '#fff', fontSize: '0.85rem', fontWeight: 600,
              cursor: saving ? 'wait' : 'pointer',
              opacity: saving ? 0.7 : 1,
            }}
          >
            {saving ? 'Test en cours…' : 'Tester & enregistrer'}
          </button>
        </div>
      )}

      {/* Suggestions de providers (nom app) */}
      {!isApiKey && hasSuggestions && result && (
        <div style={{
          marginTop: '0.5rem',
          background: 'rgba(0,0,0,0.3)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          maxHeight: 320,
          overflowY: 'auto',
        }}>
          {result.suggestions.map(s => (
            <button
              key={s.slug}
              onClick={() => handleSelectSuggestion(s.slug)}
              style={{
                display: 'flex', alignItems: 'center', gap: '0.7rem',
                width: '100%', padding: '0.7rem 1rem',
                background: 'transparent', border: 'none',
                borderBottom: '1px solid rgba(255,255,255,0.04)',
                color: 'var(--text-primary)',
                fontSize: '0.85rem', textAlign: 'left',
                cursor: 'pointer',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.04)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              <span style={{ fontSize: '1.2rem' }}>{s.logo_emoji}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 500 }}>{s.display_name}</div>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                  {s.description}
                </div>
              </div>
              {s.score > 0 && (
                <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', opacity: 0.5 }}>
                  {s.score >= 0.9 ? 'match exact' : s.score >= 0.7 ? 'fort' : 'suggéré'}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}


// ═════════════════════════════════════════════════════════════════════════════
// Drawer : édition complète d'un provider
// ═════════════════════════════════════════════════════════════════════════════

function ProviderDrawer(props: {
  provider: Provider
  credentials: Credential[]
  onClose: () => void
  onSaved: (msg: string) => void | Promise<void>
  onDeleted: () => void | Promise<void>
  onError: (msg: string) => void
}) {
  const p = props.provider
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null)
  const connected = props.credentials.length > 0

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !saving) props.onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [props, saving])

  const handleSave = async () => {
    setSaving(true)
    setTestResult(null)
    try {
      const res = await api.credentialsSave(p.slug, values)
      if (res.success) {
        await props.onSaved(
          res.validated
            ? `${p.display_name} connecté et validé ✓`
            : `${p.display_name} enregistré (validation ${res.test_message})`
        )
      } else {
        props.onError(res.test_message || 'Échec')
      }
    } catch (e: any) {
      props.onError(e?.message || 'Erreur')
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    try {
      const r = await api.credentialsTest(p.slug)
      setTestResult({ ok: r.success, msg: r.message })
    } catch (e: any) {
      setTestResult({ ok: false, msg: e?.message || 'Erreur' })
    } finally {
      setTesting(false)
    }
  }

  const handleDelete = async () => {
    if (!window.confirm(`Déconnecter ${p.display_name} ? Toutes les clés enregistrées seront supprimées.`)) return
    try {
      await api.credentialsDeleteProvider(p.slug)
      await props.onDeleted()
    } catch (e: any) {
      props.onError(e?.message || 'Erreur')
    }
  }

  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget && !saving) props.onClose() }}
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)',
        display: 'flex', justifyContent: 'flex-end',
      }}
    >
      <div style={{
        width: 'min(540px, 92vw)', height: '100%',
        background: 'var(--bg-panel, #111827)',
        borderLeft: '1px solid var(--border)',
        overflowY: 'auto',
        padding: '1.5rem',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <span style={{ fontSize: '2rem' }}>{p.logo_emoji}</span>
            <div>
              <h2 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--text-primary)' }}>{p.display_name}</h2>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>{p.description}</div>
            </div>
          </div>
          <button onClick={props.onClose} style={{
            background: 'transparent', border: 'none', color: 'var(--text-muted)',
            fontSize: '1.5rem', cursor: 'pointer',
          }}>×</button>
        </div>

        {/* Status connecté */}
        {connected && (
          <div style={{
            padding: '0.6rem 0.8rem', marginBottom: '1rem',
            background: 'rgba(16,185,129,0.08)',
            border: '1px solid rgba(16,185,129,0.3)',
            borderRadius: 8, fontSize: '0.82rem', color: '#10b981',
          }}>
            ✓ Connecté — {props.credentials.length} clé(s) enregistrée(s)
            <div style={{ marginTop: '0.4rem', fontSize: '0.7rem', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
              {props.credentials.map(c => `${c.field_key}: ${c.preview}`).join(' · ')}
            </div>
          </div>
        )}

        {/* Tutoriel */}
        <div style={{
          padding: '0.75rem 1rem', marginBottom: '1rem',
          background: 'rgba(99,102,241,0.06)',
          border: '1px solid rgba(99,102,241,0.25)',
          borderRadius: 8,
        }}>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#6366f1', marginBottom: '0.5rem' }}>
            📖 Comment obtenir une clé
          </div>
          <ol style={{ margin: 0, paddingLeft: '1.2rem', fontSize: '0.78rem', color: 'var(--text-secondary, #d0d0d0)', lineHeight: 1.6 }}>
            {p.tutorial_steps.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
          <a href={p.tutorial_url} target="_blank" rel="noopener noreferrer" style={{
            display: 'inline-block', marginTop: '0.5rem',
            fontSize: '0.75rem', color: '#6366f1', textDecoration: 'none',
          }}>
            🔗 Ouvrir la documentation officielle
          </a>
        </div>

        {/* Champs */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.8rem', marginBottom: '1rem' }}>
          {p.fields.map(f => (
            <div key={f.key}>
              <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.3rem' }}>
                {f.label} {f.required && <span style={{ color: '#ef4444' }}>*</span>}
              </label>
              <input
                type={f.type === 'password' ? 'password' : 'text'}
                value={values[f.key] || ''}
                onChange={(e) => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                placeholder={f.pattern_hint || ''}
                style={{
                  width: '100%', padding: '0.6rem 0.8rem',
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid var(--border)',
                  borderRadius: 6, color: 'var(--text-primary)',
                  fontSize: '0.85rem', outline: 'none',
                  fontFamily: f.type === 'password' ? '"Fira Code", monospace' : undefined,
                }}
              />
              {f.pattern_hint && (
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                  {f.pattern_hint}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Test result */}
        {testResult && (
          <div style={{
            padding: '0.6rem 0.8rem', marginBottom: '1rem',
            background: testResult.ok ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.08)',
            border: `1px solid ${testResult.ok ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
            borderRadius: 8, fontSize: '0.82rem',
            color: testResult.ok ? '#10b981' : '#ef4444',
          }}>
            {testResult.ok ? '✓' : '✗'} {testResult.msg}
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
          <button
            onClick={handleSave}
            disabled={saving || p.fields.filter(f => f.required).some(f => !values[f.key])}
            style={primaryBtn(saving)}
          >
            {saving ? 'Enregistrement…' : (connected ? 'Mettre à jour' : 'Enregistrer')}
          </button>
          {connected && (
            <button onClick={handleTest} disabled={testing} style={secondaryBtn(testing)}>
              {testing ? 'Test…' : 'Tester'}
            </button>
          )}
        </div>

        {/* Skills associés */}
        {p.used_by_skills.length > 0 && (
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
            Skills activés : {p.used_by_skills.map(s => (
              <code key={s} style={{ marginRight: '0.3rem', color: 'var(--text-secondary)' }}>{s}</code>
            ))}
          </div>
        )}

        {/* Delete */}
        {connected && (
          <button
            onClick={handleDelete}
            style={{
              width: '100%', padding: '0.5rem',
              background: 'transparent',
              border: '1px solid rgba(239,68,68,0.3)',
              borderRadius: 6, color: '#ef4444',
              fontSize: '0.8rem', cursor: 'pointer',
              marginTop: '1rem',
            }}
          >
            Déconnecter {p.display_name}
          </button>
        )}
      </div>
    </div>
  )
}

const primaryBtn = (disabled: boolean): React.CSSProperties => ({
  flex: 1,
  padding: '0.65rem',
  background: '#6366f1',
  border: 'none', borderRadius: 6,
  color: '#fff', fontSize: '0.85rem', fontWeight: 600,
  cursor: disabled ? 'not-allowed' : 'pointer',
  opacity: disabled ? 0.5 : 1,
})

const secondaryBtn = (disabled: boolean): React.CSSProperties => ({
  padding: '0.65rem 1rem',
  background: 'rgba(255,255,255,0.05)',
  border: '1px solid var(--border)', borderRadius: 6,
  color: 'var(--text-secondary)', fontSize: '0.85rem',
  cursor: disabled ? 'not-allowed' : 'pointer',
  opacity: disabled ? 0.5 : 1,
})


// ═════════════════════════════════════════════════════════════════════════════
// Section : credentials requises par les skills ClawHub installes
// (support infini — n'importe quel skill ClawHub peut demander ses env vars)
// ═════════════════════════════════════════════════════════════════════════════

type SkillCredStatus = Awaited<ReturnType<typeof api.credentialsMissingForSkills>>

function SkillCredentialsSection(props: {
  onSaved: (msg: string) => void | Promise<void>
  onError: (msg: string) => void
  onSelectProvider: (slug: string) => void
}) {
  const [data, setData] = useState<SkillCredStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [customValues, setCustomValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await api.credentialsMissingForSkills()
      setData(r)
    } catch (e: any) {
      // Silent : si le user n'a pas encore de skills, c'est normal
      setData({ skills: [], total_missing_count: 0 })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const saveCustom = async (skillSlug: string, envName: string) => {
    const key = `${skillSlug}__${envName}`
    const val = (customValues[key] || '').trim()
    if (!val) {
      props.onError('Valeur vide')
      return
    }
    setSaving(key)
    try {
      await api.credentialsSaveCustomSkillEnv(skillSlug, envName, val)
      await props.onSaved(`${envName} enregistrée pour ${skillSlug}`)
      setCustomValues(v => ({ ...v, [key]: '' }))
      await load()
    } catch (e: any) {
      props.onError(e?.message || 'Échec')
    } finally {
      setSaving(null)
    }
  }

  // Skills sans rien a faire (tout OK) — masques. Focus sur ceux qui ont missing.
  const skillsWithMissing = useMemo(() => {
    if (!data) return []
    return data.skills.filter(s => s.missing.some(m => !m.has_credential))
  }, [data])

  if (loading || !data) return null
  if (data.skills.length === 0) return null  // aucun skill avec required_env

  return (
    <section style={{
      margin: '1.5rem 0',
      padding: '1rem 1.25rem',
      background: skillsWithMissing.length > 0
        ? 'rgba(245,158,11,0.06)'
        : 'rgba(16,185,129,0.04)',
      border: `1px solid ${skillsWithMissing.length > 0 ? 'rgba(245,158,11,0.3)' : 'rgba(16,185,129,0.2)'}`,
      borderRadius: 12,
    }}>
      <h2 style={{
        margin: '0 0 0.5rem 0', fontSize: '1rem',
        color: skillsWithMissing.length > 0 ? '#f59e0b' : '#10b981',
        fontWeight: 600,
      }}>
        {skillsWithMissing.length > 0
          ? `🧩 ${data.total_missing_count} credential(s) manquante(s) pour tes skills ClawHub`
          : `✓ Tes ${data.skills.length} skill(s) ClawHub avec credentials sont tous configurés`}
      </h2>
      <p style={{
        margin: '0 0 0.75rem 0', fontSize: '0.8rem',
        color: 'var(--text-muted)', lineHeight: 1.5,
      }}>
        Les skills ClawHub que tu as installés peuvent nécessiter des clés API.
        Configure-les ci-dessous — chaque skill a ses propres besoins.
      </p>

      {skillsWithMissing.length === 0 ? null : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {skillsWithMissing.map(skill => (
            <div key={skill.slug} style={{
              padding: '0.75rem 0.9rem',
              background: 'rgba(255,255,255,0.03)',
              border: '1px solid var(--border)',
              borderRadius: 8,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                <span style={{ fontSize: '1.1rem' }}>{skill.emoji}</span>
                <strong style={{ color: 'var(--text-primary)', fontSize: '0.9rem' }}>{skill.name}</strong>
                <code style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{skill.slug}</code>
              </div>
              {skill.missing.filter(m => !m.has_credential).map(m => {
                const key = `${skill.slug}__${m.env_name}`
                const isCustom = m.matched_provider === null
                return (
                  <div key={m.env_name} style={{
                    display: 'flex', alignItems: 'center', gap: '0.5rem',
                    padding: '0.4rem 0', borderTop: '1px solid rgba(255,255,255,0.03)',
                    flexWrap: 'wrap',
                  }}>
                    <code style={{ fontSize: '0.78rem', color: '#f59e0b', minWidth: 180 }}>
                      {m.env_name}
                    </code>
                    {isCustom ? (
                      <>
                        <input
                          type="password"
                          placeholder={`Valeur de ${m.env_name}`}
                          value={customValues[key] || ''}
                          onChange={(e) => setCustomValues(v => ({ ...v, [key]: e.target.value }))}
                          style={{
                            flex: 1, minWidth: 200,
                            padding: '0.35rem 0.6rem',
                            background: 'rgba(255,255,255,0.04)',
                            border: '1px solid var(--border)', borderRadius: 6,
                            color: 'var(--text-primary)', fontSize: '0.78rem',
                            fontFamily: '"Fira Code", monospace',
                            outline: 'none',
                          }}
                        />
                        <button
                          onClick={() => saveCustom(skill.slug, m.env_name)}
                          disabled={saving === key || !customValues[key]}
                          style={{
                            padding: '0.35rem 0.75rem',
                            background: '#6366f1', border: 'none', borderRadius: 6,
                            color: '#fff', fontSize: '0.75rem', fontWeight: 500,
                            cursor: (saving === key || !customValues[key]) ? 'not-allowed' : 'pointer',
                            opacity: (saving === key || !customValues[key]) ? 0.5 : 1,
                          }}
                        >
                          {saving === key ? '…' : 'Enregistrer'}
                        </button>
                        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>custom</span>
                      </>
                    ) : (
                      <>
                        <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', flex: 1 }}>
                          → provider <b>{m.matched_provider}</b>
                        </span>
                        <button
                          onClick={() => props.onSelectProvider(m.matched_provider!)}
                          style={{
                            padding: '0.35rem 0.75rem',
                            background: 'rgba(99,102,241,0.15)',
                            border: '1px solid rgba(99,102,241,0.3)', borderRadius: 6,
                            color: '#6366f1', fontSize: '0.75rem', fontWeight: 500,
                            cursor: 'pointer',
                          }}
                        >
                          Configurer {m.matched_provider}
                        </button>
                      </>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
