// Page Marketplace -- ClawHub skills catalogue + installation locale
// Phase 2 : consommation de clawhub.ai depuis l'UI Syléa (Agent 3 OpenClaw).
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'

// ── Types locaux ────────────────────────────────────────────────────────────
interface FeaturedSkill {
  slug: string
  owner: string
  name: string
  description: string
  url: string
  tags: string[]
  highlight?: boolean
  homepage?: string
}

type SkillRow = {
  slug?: string
  owner?: string
  name?: string
  title?: string
  description?: string
  tags?: string[]
  url?: string
  path?: string
  [k: string]: any
}

type TabKey = 'featured' | 'search' | 'installed'

// ── Icones SVG inline ───────────────────────────────────────────────────────
function IconSearch({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  )
}

function IconDownload({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  )
}

function IconTrash({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
    </svg>
  )
}

function IconExternal({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  )
}

function IconStar({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  )
}

// ── Carte de skill unifiée ─────────────────────────────────────────────────

function SkillCard({
  skill,
  installed,
  onInstall,
  onUninstall,
  onView,
  busy,
  highlight,
}: {
  skill: SkillRow
  installed: boolean
  onInstall?: (slug: string) => void
  onUninstall?: (slug: string) => void
  onView?: (slug: string) => void
  busy?: boolean
  highlight?: boolean
}) {
  const title = skill.name || skill.title || skill.slug || '(skill sans nom)'
  const slug = skill.slug || ''
  const desc = skill.description || ''
  const owner = skill.owner || ''
  const url = skill.url || (owner && slug ? `https://clawhub.ai/${owner}/${slug}` : '')
  const tags = Array.isArray(skill.tags) ? skill.tags : []

  return (
    <div
      style={{
        background: highlight
          ? 'linear-gradient(135deg, rgba(59,130,246,0.10), rgba(139,92,246,0.08))'
          : 'rgba(8, 14, 28, 0.6)',
        border: highlight
          ? '1px solid rgba(139,92,246,0.40)'
          : '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)',
        padding: '1.1rem 1.1rem 0.9rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.65rem',
        boxShadow: highlight
          ? '0 0 24px rgba(139,92,246,0.12)'
          : 'none',
        transition: 'transform 0.15s, box-shadow 0.15s',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.transform = 'translateY(-2px)'
        e.currentTarget.style.boxShadow = highlight
          ? '0 6px 32px rgba(139,92,246,0.22)'
          : '0 4px 18px rgba(0,0,0,0.35)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.transform = 'translateY(0)'
        e.currentTarget.style.boxShadow = highlight
          ? '0 0 24px rgba(139,92,246,0.12)'
          : 'none'
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
            <h3 style={{
              margin: 0,
              fontSize: '1.02rem',
              color: 'var(--text-primary)',
              fontWeight: 600,
              letterSpacing: '0.01em',
            }}>
              {title}
            </h3>
            {highlight && (
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
                padding: '0.12rem 0.45rem',
                borderRadius: '999px',
                background: 'rgba(245,158,11,0.15)',
                color: '#f59e0b',
                fontSize: '0.68rem',
                fontWeight: 600,
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
              }}>
                <IconStar size={11} /> Vedette
              </span>
            )}
            {installed && (
              <span style={{
                padding: '0.12rem 0.45rem',
                borderRadius: '999px',
                background: 'rgba(34,197,94,0.15)',
                color: '#22c55e',
                fontSize: '0.68rem',
                fontWeight: 600,
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
              }}>
                Installé
              </span>
            )}
          </div>
          {owner && (
            <div style={{
              fontSize: '0.72rem',
              color: 'var(--text-muted)',
              marginTop: '0.15rem',
              letterSpacing: '0.02em',
            }}>
              @{owner}{slug && ` / ${slug}`}
            </div>
          )}
        </div>
      </div>

      {desc && (
        <p style={{
          margin: 0,
          fontSize: '0.82rem',
          color: 'var(--text-secondary)',
          lineHeight: 1.5,
          display: '-webkit-box',
          WebkitLineClamp: 3,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
        }}>
          {desc}
        </p>
      )}

      {tags.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem' }}>
          {tags.slice(0, 5).map(tag => (
            <span key={tag} style={{
              padding: '0.12rem 0.5rem',
              borderRadius: '999px',
              background: 'rgba(26,111,216,0.12)',
              color: 'var(--accent-violet-light)',
              fontSize: '0.68rem',
              border: '1px solid rgba(26,111,216,0.22)',
            }}>
              {tag}
            </span>
          ))}
        </div>
      )}

      <div style={{
        marginTop: 'auto',
        paddingTop: '0.3rem',
        display: 'flex',
        gap: '0.5rem',
        alignItems: 'center',
        flexWrap: 'wrap',
      }}>
        {!installed && onInstall && slug && (
          <button
            onClick={() => onInstall(slug)}
            disabled={busy}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
              padding: '0.42rem 0.75rem',
              borderRadius: '6px',
              border: '1px solid rgba(26,111,216,0.40)',
              background: 'rgba(26,111,216,0.14)',
              color: 'var(--accent-violet-light)',
              fontSize: '0.78rem',
              fontWeight: 600,
              cursor: busy ? 'wait' : 'pointer',
              opacity: busy ? 0.6 : 1,
              transition: 'all 0.15s',
            }}
          >
            <IconDownload size={14} /> {busy ? 'Installation...' : 'Installer'}
          </button>
        )}
        {installed && onUninstall && slug && (
          <button
            onClick={() => onUninstall(slug)}
            disabled={busy}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
              padding: '0.42rem 0.75rem',
              borderRadius: '6px',
              border: '1px solid rgba(239,68,68,0.35)',
              background: 'transparent',
              color: '#ef4444',
              fontSize: '0.78rem',
              fontWeight: 500,
              cursor: busy ? 'wait' : 'pointer',
              opacity: busy ? 0.6 : 1,
              transition: 'all 0.15s',
            }}
          >
            <IconTrash size={14} /> Desinstaller
          </button>
        )}
        {onView && slug && (
          <button
            onClick={() => onView(slug)}
            style={{
              padding: '0.42rem 0.6rem',
              borderRadius: '6px',
              border: '1px solid var(--border)',
              background: 'transparent',
              color: 'var(--text-secondary)',
              fontSize: '0.76rem',
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
          >
            Details
          </button>
        )}
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
              marginLeft: 'auto',
              color: 'var(--text-muted)',
              fontSize: '0.72rem',
              textDecoration: 'none',
            }}
          >
            ClawHub <IconExternal size={12} />
          </a>
        )}
      </div>
    </div>
  )
}

// ── Page ────────────────────────────────────────────────────────────────────
export default function MarketplacePage() {
  const [tab, setTab] = useState<TabKey>('featured')

  // Featured (statique, inclut Syléa)
  const [featured, setFeatured] = useState<FeaturedSkill[]>([])
  const [loadingFeatured, setLoadingFeatured] = useState(true)

  // Search
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SkillRow[]>([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [hasSearched, setHasSearched] = useState(false)

  // Installed
  const [installed, setInstalled] = useState<SkillRow[]>([])
  const [loadingInstalled, setLoadingInstalled] = useState(false)
  const [installedError, setInstalledError] = useState<string | null>(null)

  // Busy state par slug pour install/uninstall
  const [busySlug, setBusySlug] = useState<string | null>(null)
  const [toast, setToast] = useState<{ kind: 'ok' | 'err'; message: string } | null>(null)

  // Détails modal
  const [detailsSkill, setDetailsSkill] = useState<{ slug: string; data: any } | null>(null)
  const [loadingDetails, setLoadingDetails] = useState(false)

  // Set installed slugs (pour marquer les featured/search)
  const installedSlugs = useMemo(() => {
    const s = new Set<string>()
    installed.forEach(it => { if (it.slug) s.add(it.slug) })
    return s
  }, [installed])

  // Charge featured au montage
  useEffect(() => {
    api.marketplaceFeatured()
      .then(r => setFeatured(r.featured || []))
      .catch(() => setFeatured([]))
      .finally(() => setLoadingFeatured(false))
  }, [])

  // Charge installed quand on ouvre l'onglet (ou après install/uninstall)
  const loadInstalled = async () => {
    setLoadingInstalled(true)
    setInstalledError(null)
    try {
      const r = await api.marketplaceListInstalled()
      if (r.success) {
        setInstalled(Array.isArray(r.skills) ? r.skills : [])
      } else {
        setInstalledError(r.error || 'Impossible de lister les skills installées.')
        setInstalled([])
      }
    } catch (e: any) {
      setInstalledError(e?.message || 'Erreur réseau.')
      setInstalled([])
    } finally {
      setLoadingInstalled(false)
    }
  }

  useEffect(() => {
    if (tab === 'installed') {
      loadInstalled()
    }
  }, [tab])

  // Charge une fois au montage pour avoir installedSlugs dispo dans Featured/Search
  useEffect(() => {
    loadInstalled()
  }, [])

  // Feedback toast auto-fade
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 3500)
    return () => clearTimeout(t)
  }, [toast])

  // ── Actions ────────────────────────────────────────────────────────────────

  const doSearch = async () => {
    const q = query.trim()
    if (!q) return
    setSearching(true)
    setSearchError(null)
    setHasSearched(true)
    try {
      const r = await api.marketplaceSearch(q, 30)
      if (r.success) {
        setSearchResults(Array.isArray(r.skills) ? r.skills : [])
      } else {
        setSearchError(r.error || 'Recherche indisponible.')
        setSearchResults([])
      }
    } catch (e: any) {
      setSearchError(e?.message || 'Erreur réseau.')
      setSearchResults([])
    } finally {
      setSearching(false)
    }
  }

  const doInstall = async (slug: string) => {
    setBusySlug(slug)
    try {
      const r = await api.marketplaceInstall(slug)
      if (r.success) {
        setToast({ kind: 'ok', message: `Skill "${slug}" installé.` })
        await loadInstalled()
      } else {
        setToast({ kind: 'err', message: r.error || `Installation de "${slug}" échouée.` })
      }
    } catch (e: any) {
      setToast({ kind: 'err', message: e?.message || 'Erreur réseau.' })
    } finally {
      setBusySlug(null)
    }
  }

  const doUninstall = async (slug: string) => {
    if (!confirm(`Désinstaller le skill "${slug}" ?`)) return
    setBusySlug(slug)
    try {
      const r = await api.marketplaceUninstall(slug)
      if (r.success) {
        setToast({ kind: 'ok', message: `Skill "${slug}" désinstallé.` })
        await loadInstalled()
      } else {
        setToast({ kind: 'err', message: r.error || `Désinstallation échouée.` })
      }
    } catch (e: any) {
      setToast({ kind: 'err', message: e?.message || 'Erreur réseau.' })
    } finally {
      setBusySlug(null)
    }
  }

  const doView = async (slug: string) => {
    setLoadingDetails(true)
    setDetailsSkill({ slug, data: null })
    try {
      const r = await api.marketplaceSkillInfo(slug)
      setDetailsSkill({ slug, data: r.data })
    } catch (e: any) {
      setDetailsSkill({ slug, data: { error: e?.message || 'Introuvable' } })
    } finally {
      setLoadingDetails(false)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="container" style={{ padding: '1.75rem 1rem 3rem' }}>
      {/* En-tête */}
      <div style={{ marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem' }}>
          <span style={{ fontSize: '1.35rem' }}>🛒</span>
          <h1 style={{
            margin: 0,
            fontSize: '1.5rem',
            letterSpacing: '0.03em',
            color: 'var(--text-primary)',
          }}>
            ClawHub Marketplace
          </h1>
        </div>
        <p style={{
          margin: 0,
          color: 'var(--text-muted)',
          fontSize: '0.88rem',
          lineHeight: 1.5,
        }}>
          Explorez les 52 700+ skills de l'écosystème ClawHub, installez-les dans votre Agent 3 OpenClaw,
          ou admirez que Syléa y figure déjà.
        </p>
      </div>

      {/* Tabs */}
      <div style={{
        display: 'flex',
        gap: '0.25rem',
        borderBottom: '1px solid var(--border)',
        marginBottom: '1.5rem',
      }}>
        {([
          { k: 'featured', label: 'Vedettes' },
          { k: 'search',   label: 'Recherche' },
          { k: 'installed', label: `Installées (${installed.length})` },
        ] as Array<{ k: TabKey; label: string }>).map(({ k, label }) => {
          const active = tab === k
          return (
            <button
              key={k}
              onClick={() => setTab(k)}
              style={{
                padding: '0.55rem 1rem',
                border: 'none',
                background: 'transparent',
                color: active ? 'var(--accent-violet-light)' : 'var(--text-muted)',
                fontSize: '0.9rem',
                fontWeight: active ? 600 : 400,
                cursor: 'pointer',
                position: 'relative',
                transition: 'color 0.15s',
              }}
            >
              {label}
              {active && (
                <span style={{
                  position: 'absolute',
                  bottom: -1,
                  left: 0,
                  right: 0,
                  height: 2,
                  background: 'linear-gradient(90deg, #3b82f6, #8b5cf6)',
                  borderRadius: '2px 2px 0 0',
                }} />
              )}
            </button>
          )
        })}
      </div>

      {/* Toast */}
      {toast && (
        <div style={{
          position: 'fixed',
          bottom: '1.5rem',
          right: '1.5rem',
          padding: '0.75rem 1.1rem',
          borderRadius: 'var(--radius-lg)',
          background: toast.kind === 'ok'
            ? 'rgba(34,197,94,0.15)'
            : 'rgba(239,68,68,0.15)',
          border: `1px solid ${toast.kind === 'ok' ? 'rgba(34,197,94,0.45)' : 'rgba(239,68,68,0.45)'}`,
          color: toast.kind === 'ok' ? '#22c55e' : '#ef4444',
          fontSize: '0.85rem',
          zIndex: 300,
          boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
          maxWidth: 380,
        }}>
          {toast.message}
        </div>
      )}

      {/* ── FEATURED ─────────────────────────────────────────────────── */}
      {tab === 'featured' && (
        <div>
          {loadingFeatured ? (
            <div style={{ color: 'var(--text-muted)', padding: '2rem', textAlign: 'center' }}>
              Chargement des vedettes...
            </div>
          ) : featured.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', padding: '2rem', textAlign: 'center' }}>
              Aucune vedette pour le moment.
            </div>
          ) : (
            <>
              <div style={{
                padding: '0.85rem 1rem',
                marginBottom: '1rem',
                borderRadius: 'var(--radius-lg)',
                background: 'linear-gradient(135deg, rgba(59,130,246,0.08), rgba(139,92,246,0.06))',
                border: '1px solid rgba(139,92,246,0.30)',
                fontSize: '0.82rem',
                color: 'var(--text-secondary)',
                lineHeight: 1.5,
              }}>
                <strong style={{ color: 'var(--accent-violet-light)' }}>Syléa est sur ClawHub.</strong>{' '}
                Notre skill coaching de vie est publié et téléchargeable par n'importe qui dans l'écosystème,
                comme n'importe quel autre skill du marketplace.
              </div>
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
                gap: '1rem',
              }}>
                {featured.map(f => (
                  <SkillCard
                    key={f.slug}
                    skill={f as SkillRow}
                    installed={installedSlugs.has(f.slug)}
                    onInstall={doInstall}
                    onUninstall={doUninstall}
                    onView={doView}
                    busy={busySlug === f.slug}
                    highlight={f.highlight}
                  />
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* ── SEARCH ───────────────────────────────────────────────────── */}
      {tab === 'search' && (
        <div>
          <form
            onSubmit={e => { e.preventDefault(); doSearch() }}
            style={{
              display: 'flex',
              gap: '0.5rem',
              marginBottom: '1.25rem',
            }}
          >
            <div style={{
              flex: 1,
              position: 'relative',
              display: 'flex',
              alignItems: 'center',
            }}>
              <span style={{
                position: 'absolute',
                left: '0.75rem',
                color: 'var(--text-muted)',
                pointerEvents: 'none',
              }}>
                <IconSearch />
              </span>
              <input
                type="text"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Cherche un skill (ex: traduction, markdown, pdf...)"
                style={{
                  width: '100%',
                  padding: '0.65rem 0.75rem 0.65rem 2.3rem',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  background: 'rgba(6, 12, 26, 0.6)',
                  color: 'var(--text-primary)',
                  fontSize: '0.9rem',
                  outline: 'none',
                }}
              />
            </div>
            <button
              type="submit"
              disabled={searching || !query.trim()}
              style={{
                padding: '0.65rem 1.2rem',
                borderRadius: '8px',
                border: '1px solid rgba(26,111,216,0.45)',
                background: 'rgba(26,111,216,0.18)',
                color: 'var(--accent-violet-light)',
                fontSize: '0.88rem',
                fontWeight: 600,
                cursor: searching ? 'wait' : 'pointer',
                opacity: !query.trim() ? 0.5 : 1,
              }}
            >
              {searching ? 'Recherche...' : 'Rechercher'}
            </button>
          </form>

          {searchError && (
            <div style={{
              padding: '0.75rem 1rem',
              borderRadius: 'var(--radius-md)',
              background: 'rgba(239,68,68,0.1)',
              border: '1px solid rgba(239,68,68,0.35)',
              color: '#ef4444',
              fontSize: '0.82rem',
              marginBottom: '1rem',
            }}>
              {searchError}
            </div>
          )}

          {!hasSearched && !searching && (
            <div style={{
              color: 'var(--text-muted)',
              padding: '2rem 1rem',
              textAlign: 'center',
              fontSize: '0.9rem',
            }}>
              Entrez un mot-clé pour chercher sur les 52 700+ skills ClawHub.
            </div>
          )}

          {hasSearched && !searching && searchResults.length === 0 && !searchError && (
            <div style={{
              color: 'var(--text-muted)',
              padding: '2rem 1rem',
              textAlign: 'center',
              fontSize: '0.9rem',
            }}>
              Aucun résultat pour « {query} ».
            </div>
          )}

          {searchResults.length > 0 && (
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
              gap: '1rem',
            }}>
              {searchResults.map((s, i) => (
                <SkillCard
                  key={s.slug || `res-${i}`}
                  skill={s}
                  installed={!!s.slug && installedSlugs.has(s.slug)}
                  onInstall={doInstall}
                  onUninstall={doUninstall}
                  onView={doView}
                  busy={busySlug === s.slug}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── INSTALLED ────────────────────────────────────────────────── */}
      {tab === 'installed' && (
        <div>
          {loadingInstalled ? (
            <div style={{ color: 'var(--text-muted)', padding: '2rem', textAlign: 'center' }}>
              Chargement des skills installées...
            </div>
          ) : installedError ? (
            <div style={{
              padding: '0.85rem 1rem',
              borderRadius: 'var(--radius-lg)',
              background: 'rgba(239,68,68,0.1)',
              border: '1px solid rgba(239,68,68,0.35)',
              color: '#ef4444',
              fontSize: '0.85rem',
              lineHeight: 1.5,
            }}>
              <strong>Impossible de lister les skills installées.</strong><br />
              {installedError}<br />
              <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                Vérifiez que le CLI <code>clawhub</code> est installé, ou utilisez l'onglet Recherche pour découvrir des skills.
              </span>
            </div>
          ) : installed.length === 0 ? (
            <div style={{
              color: 'var(--text-muted)',
              padding: '2.5rem 1rem',
              textAlign: 'center',
              fontSize: '0.9rem',
            }}>
              Aucun skill installé pour le moment.<br />
              <button
                onClick={() => setTab('search')}
                style={{
                  marginTop: '1rem',
                  padding: '0.55rem 1.1rem',
                  borderRadius: '8px',
                  border: '1px solid rgba(26,111,216,0.45)',
                  background: 'rgba(26,111,216,0.14)',
                  color: 'var(--accent-violet-light)',
                  fontSize: '0.85rem',
                  cursor: 'pointer',
                  fontWeight: 600,
                }}
              >
                Explorer le marketplace
              </button>
            </div>
          ) : (
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
              gap: '1rem',
            }}>
              {installed.map((s, i) => (
                <SkillCard
                  key={s.slug || `inst-${i}`}
                  skill={s}
                  installed={true}
                  onUninstall={doUninstall}
                  onView={doView}
                  busy={busySlug === s.slug}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── MODAL DETAILS ────────────────────────────────────────────── */}
      {detailsSkill && (
        <div
          onClick={() => setDetailsSkill(null)}
          style={{
            position: 'fixed', inset: 0,
            background: 'rgba(0,0,0,0.72)',
            backdropFilter: 'blur(6px)',
            zIndex: 400,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '1rem',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background: 'rgba(8, 14, 28, 0.98)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg)',
              maxWidth: 620,
              width: '100%',
              maxHeight: '80vh',
              overflow: 'auto',
              padding: '1.5rem',
              boxShadow: '0 20px 60px rgba(0,0,0,0.6)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h3 style={{ margin: 0, color: 'var(--text-primary)' }}>Détails : {detailsSkill.slug}</h3>
              <button
                onClick={() => setDetailsSkill(null)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  fontSize: '1.35rem',
                  padding: '0 0.3rem',
                }}
              >
                ×
              </button>
            </div>
            {loadingDetails ? (
              <div style={{ color: 'var(--text-muted)' }}>Chargement...</div>
            ) : (
              <pre style={{
                background: 'rgba(0,0,0,0.35)',
                padding: '0.85rem',
                borderRadius: '6px',
                fontSize: '0.78rem',
                color: 'var(--text-secondary)',
                overflow: 'auto',
                margin: 0,
                maxHeight: '55vh',
                lineHeight: 1.45,
              }}>
                {JSON.stringify(detailsSkill.data, null, 2)}
              </pre>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
