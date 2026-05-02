/**
 * MetricsPage — Dashboard de metrics Agent 3.
 *
 * Visualise le contenu de GET /api/agent3/metrics :
 *   - Gateway health (up/down + last error)
 *   - Circuit breakers par tool (state, failures)
 *   - Retries par (tool, event) : attempts/retry/success/failure/timeout/http_xxx/...
 *   - Couts externes du user courant (USD par tool)
 *
 * Auto-refresh toutes les 15s + bouton manuel.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'

type LatencyStats = {
  count: number
  p50_ms: number
  p95_ms: number
  p99_ms: number
  min_ms: number
  max_ms: number
  avg_ms: number
}

type MetricsResponse = {
  retries: Record<string, number>
  breakers: Record<string, {
    name: string
    state: 'closed' | 'open' | 'half_open'
    failures: number
    threshold: number
  }>
  gateway_health: {
    is_up: boolean | null
    checked_at: number
    ttl_s: number
    last_error: string
  }
  external_cost_global: {
    total_by_user: Record<string, number>
    total_calls: number
  }
  external_cost_mine: {
    total_usd: number
    by_tool: Record<string, { usd: number; calls: number }>
  }
  latencies?: Record<string, LatencyStats>
  daily_cost?: {
    used_usd: number
    cap_usd: number
    pct: number
  }
}

const REFRESH_INTERVAL_MS = 15_000

function formatTime(ts: number): string {
  if (!ts) return 'jamais'
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function parseRetryKey(key: string): { tool: string; event: string } {
  const idx = key.indexOf('__')
  if (idx === -1) return { tool: 'unknown', event: key }
  return { tool: key.slice(0, idx), event: key.slice(idx + 2) }
}

type ToolRetryStats = {
  tool: string
  attempt: number
  retry: number
  success: number
  failure: number
  timeout: number
  circuit_open_rejected: number
  retry_after_honored: number
  http_errors: Record<string, number>
  rawTotal: number
}

function aggregateRetries(retries: Record<string, number>): ToolRetryStats[] {
  const byTool: Record<string, ToolRetryStats> = {}
  for (const [key, count] of Object.entries(retries)) {
    const { tool, event } = parseRetryKey(key)
    if (!byTool[tool]) {
      byTool[tool] = {
        tool,
        attempt: 0,
        retry: 0,
        success: 0,
        failure: 0,
        timeout: 0,
        circuit_open_rejected: 0,
        retry_after_honored: 0,
        http_errors: {},
        rawTotal: 0,
      }
    }
    const t = byTool[tool]
    t.rawTotal += count
    if (event === 'attempt') t.attempt += count
    else if (event === 'retry') t.retry += count
    else if (event === 'success') t.success += count
    else if (event === 'failure') t.failure += count
    else if (event === 'timeout') t.timeout += count
    else if (event === 'circuit_open_rejected') t.circuit_open_rejected += count
    else if (event === 'retry_after_honored') t.retry_after_honored += count
    else if (event.startsWith('http_')) t.http_errors[event] = (t.http_errors[event] || 0) + count
  }
  return Object.values(byTool).sort((a, b) => b.attempt - a.attempt)
}

export default function MetricsPage() {
  const [data, setData] = useState<MetricsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastFetch, setLastFetch] = useState<number>(0)
  const timerRef = useRef<number | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const r = await api.agent3GetMetrics()
      setData(r)
      setLastFetch(Date.now())
    } catch (e: any) {
      setError(e?.message || 'Impossible de charger les metrics')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    timerRef.current = window.setInterval(load, REFRESH_INTERVAL_MS)
    return () => {
      if (timerRef.current !== null) window.clearInterval(timerRef.current)
    }
  }, [load])

  const retryStats = useMemo(() => data ? aggregateRetries(data.retries) : [], [data])

  const costByToolSorted = useMemo(() => {
    if (!data) return [] as Array<[string, { usd: number; calls: number }]>
    return Object.entries(data.external_cost_mine.by_tool).sort((a, b) => b[1].usd - a[1].usd)
  }, [data])

  const breakersOpen = useMemo(() => {
    if (!data) return []
    return Object.values(data.breakers).filter((b) => b.state === 'open')
  }, [data])

  const latencyStatsSorted = useMemo(() => {
    if (!data?.latencies) return [] as Array<[string, LatencyStats]>
    return Object.entries(data.latencies).sort((a, b) => b[1].p95_ms - a[1].p95_ms)
  }, [data])

  // Format ms -> "12ms" ou "1.3s"
  const fmtLatency = (ms: number): string => {
    if (ms < 1000) return `${Math.round(ms)}ms`
    return `${(ms / 1000).toFixed(1)}s`
  }

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '2rem 1rem' }}>
      {/* Header */}
      <div style={{ marginBottom: '1.5rem' }}>
        <p style={{
          color: 'var(--text-muted)', fontSize: '0.875rem',
          marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.1em',
        }}>
          Agent 3
        </p>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: '0.75rem' }}>
          <h1 style={{ fontSize: '1.75rem', color: 'var(--accent-silver)', margin: 0 }}>
            Observabilité OpenClaw
          </h1>
          <button
            onClick={load}
            disabled={loading}
            style={{
              padding: '0.4rem 0.9rem',
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid var(--border)',
              borderRadius: 6, color: 'var(--text-secondary)',
              fontSize: '0.8rem', cursor: loading ? 'not-allowed' : 'pointer',
            }}
          >
            ↻ Rafraîchir
          </button>
        </div>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', lineHeight: 1.5, marginTop: '0.3rem' }}>
          Metrics temps réel : santé du Gateway, retries par outil, circuit breakers, coûts APIs externes.
          Auto-refresh toutes les 15s.
          {lastFetch > 0 && <span style={{ marginLeft: '0.5rem', fontSize: '0.75rem' }}>
            (dernier fetch : {new Date(lastFetch).toLocaleTimeString('fr-FR')})
          </span>}
        </p>
      </div>

      {loading && !data && (
        <div style={{ textAlign: 'center', padding: '3rem 0', color: 'var(--text-muted)' }}>
          Chargement…
        </div>
      )}

      {error && !data && (
        <div style={{
          padding: '0.9rem', background: 'rgba(239,68,68,0.08)',
          border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8,
          color: '#ef4444', fontSize: '0.85rem',
        }}>
          {error}
        </div>
      )}

      {data && (
        <>
          {/* ── Budget du jour ──────────────────────────────────────── */}
          {data.daily_cost && (
            <section style={{
              ...sectionStyle,
              background: data.daily_cost.pct >= 100
                ? 'rgba(239,68,68,0.08)'
                : data.daily_cost.pct >= 80
                  ? 'rgba(245,158,11,0.08)'
                  : 'rgba(255,255,255,0.02)',
              border: data.daily_cost.pct >= 100
                ? '1px solid rgba(239,68,68,0.4)'
                : data.daily_cost.pct >= 80
                  ? '1px solid rgba(245,158,11,0.4)'
                  : '1px solid var(--border)',
            }}>
              <h2 style={sectionTitleStyle}>
                {data.daily_cost.pct >= 100 ? '🚨' : data.daily_cost.pct >= 80 ? '⚠️' : '💵'}
                {' '}Budget du jour (OpenClaw)
              </h2>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.75rem', flexWrap: 'wrap' }}>
                <span style={{ fontSize: '1.5rem', fontWeight: 700,
                  color: data.daily_cost.pct >= 100 ? '#ef4444' : data.daily_cost.pct >= 80 ? '#f59e0b' : 'var(--accent-silver)' }}>
                  ${data.daily_cost.used_usd.toFixed(4)}
                </span>
                <span style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                  / ${data.daily_cost.cap_usd.toFixed(2)} ({data.daily_cost.pct.toFixed(0)}%)
                </span>
                {data.daily_cost.pct >= 100 && (
                  <span style={{ color: '#ef4444', fontSize: '0.82rem', fontWeight: 600 }}>
                    · LIMITE ATTEINTE — les outils payants sont bloqués
                  </span>
                )}
                {data.daily_cost.pct >= 80 && data.daily_cost.pct < 100 && (
                  <span style={{ color: '#f59e0b', fontSize: '0.82rem', fontWeight: 600 }}>
                    · attention, bientôt à 100%
                  </span>
                )}
              </div>
              {/* Progress bar */}
              <div style={{
                marginTop: '0.75rem',
                height: 10, borderRadius: 5,
                background: 'rgba(255,255,255,0.05)', overflow: 'hidden',
              }}>
                <div style={{
                  width: `${Math.min(data.daily_cost.pct, 100)}%`,
                  height: '100%',
                  background: data.daily_cost.pct >= 100
                    ? '#ef4444'
                    : data.daily_cost.pct >= 80 ? '#f59e0b' : '#10b981',
                  transition: 'width 0.3s ease',
                }} />
              </div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>
                Reset à minuit UTC. Modifie le plafond dans les préférences user
                (`external_cost_cap_usd_per_day`).
              </div>
            </section>
          )}

          {/* ── 1. Gateway Health ──────────────────────────────────── */}
          <section style={sectionStyle}>
            <h2 style={sectionTitleStyle}>🏥 Santé du Gateway OpenClaw</h2>
            <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
              <div style={{
                padding: '0.6rem 1rem',
                borderRadius: 8,
                background: data.gateway_health.is_up === null
                  ? 'rgba(148,163,184,0.12)'
                  : data.gateway_health.is_up
                    ? 'rgba(16,185,129,0.12)'
                    : 'rgba(239,68,68,0.12)',
                border: `1px solid ${data.gateway_health.is_up === null
                  ? 'rgba(148,163,184,0.35)'
                  : data.gateway_health.is_up
                    ? 'rgba(16,185,129,0.4)'
                    : 'rgba(239,68,68,0.4)'}`,
                color: data.gateway_health.is_up === null
                  ? 'var(--text-muted)'
                  : data.gateway_health.is_up ? '#10b981' : '#ef4444',
                fontWeight: 600, fontSize: '0.92rem',
              }}>
                {data.gateway_health.is_up === null
                  ? '○ Jamais vérifié'
                  : data.gateway_health.is_up
                    ? '✓ Gateway UP'
                    : '✕ Gateway DOWN'}
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Dernier check : {formatTime(data.gateway_health.checked_at)} · TTL cache : {data.gateway_health.ttl_s}s
              </div>
            </div>
            {data.gateway_health.last_error && (
              <div style={{
                marginTop: '0.75rem', padding: '0.5rem 0.75rem',
                background: 'rgba(239,68,68,0.05)', borderRadius: 6,
                color: '#ef4444', fontSize: '0.78rem', fontFamily: 'monospace',
              }}>
                {data.gateway_health.last_error}
              </div>
            )}
          </section>

          {/* ── 2. Circuit Breakers ──────────────────────────────────── */}
          <section style={sectionStyle}>
            <h2 style={sectionTitleStyle}>
              ⚡ Circuit Breakers
              {breakersOpen.length > 0 && (
                <span style={{ marginLeft: '0.5rem', color: '#ef4444', fontSize: '0.85rem' }}>
                  ({breakersOpen.length} ouverts !)
                </span>
              )}
            </h2>
            {Object.keys(data.breakers).length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                Aucun breaker actif (aucun outil OpenClaw n'a encore été appelé).
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '0.5rem' }}>
                {Object.values(data.breakers).map((b) => (
                  <div key={b.name} style={{
                    padding: '0.6rem 0.8rem',
                    background: b.state === 'open'
                      ? 'rgba(239,68,68,0.08)'
                      : b.state === 'half_open'
                        ? 'rgba(245,158,11,0.08)'
                        : 'rgba(16,185,129,0.06)',
                    border: `1px solid ${b.state === 'open' ? 'rgba(239,68,68,0.3)' : b.state === 'half_open' ? 'rgba(245,158,11,0.3)' : 'rgba(16,185,129,0.2)'}`,
                    borderRadius: 8,
                  }}>
                    <div style={{
                      fontWeight: 600, fontSize: '0.85rem',
                      color: b.state === 'open' ? '#ef4444' : b.state === 'half_open' ? '#f59e0b' : '#10b981',
                    }}>
                      {b.name}
                    </div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                      {b.state.toUpperCase()} · {b.failures}/{b.threshold} échecs
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* ── 3. Retry stats par tool ──────────────────────────────── */}
          <section style={sectionStyle}>
            <h2 style={sectionTitleStyle}>📊 Retries par outil</h2>
            {retryStats.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                Aucun appel enregistré pour le moment.
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)' }}>
                      <th style={thStyle}>Tool</th>
                      <th style={thStyle}>Appels</th>
                      <th style={thStyle}>Succès</th>
                      <th style={thStyle}>Échecs</th>
                      <th style={thStyle}>Retries</th>
                      <th style={thStyle}>Timeouts</th>
                      <th style={thStyle}>Breaker bloqué</th>
                      <th style={thStyle}>Retry-After</th>
                      <th style={thStyle}>HTTP errors</th>
                    </tr>
                  </thead>
                  <tbody>
                    {retryStats.map((r) => {
                      const successRate = r.attempt > 0 ? (r.success / r.attempt) * 100 : 0
                      const httpSummary = Object.entries(r.http_errors).map(([k, v]) => `${k.replace('http_', '')}:${v}`).join(' ')
                      return (
                        <tr key={r.tool} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                          <td style={tdStyle}><b>{r.tool}</b></td>
                          <td style={tdStyle}>{r.attempt}</td>
                          <td style={{ ...tdStyle, color: r.success > 0 ? '#10b981' : undefined }}>
                            {r.success} {r.attempt > 0 && <span style={{ opacity: 0.6, fontSize: '0.72rem' }}>({successRate.toFixed(0)}%)</span>}
                          </td>
                          <td style={{ ...tdStyle, color: r.failure > 0 ? '#ef4444' : undefined }}>{r.failure}</td>
                          <td style={tdStyle}>{r.retry}</td>
                          <td style={{ ...tdStyle, color: r.timeout > 0 ? '#f59e0b' : undefined }}>{r.timeout}</td>
                          <td style={{ ...tdStyle, color: r.circuit_open_rejected > 0 ? '#ef4444' : undefined }}>
                            {r.circuit_open_rejected}
                          </td>
                          <td style={tdStyle}>{r.retry_after_honored}</td>
                          <td style={{ ...tdStyle, fontSize: '0.72rem', fontFamily: 'monospace', color: httpSummary ? '#f59e0b' : undefined }}>
                            {httpSummary || '—'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* ── Latences p50/p95/p99 ─────────────────────────────────── */}
          <section style={sectionStyle}>
            <h2 style={sectionTitleStyle}>⏱️ Latences par outil (100 derniers appels)</h2>
            {latencyStatsSorted.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                Aucune mesure de latence pour le moment.
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)' }}>
                      <th style={thStyle}>Tool</th>
                      <th style={thStyle}>Échantillons</th>
                      <th style={thStyle}>Médiane (p50)</th>
                      <th style={thStyle}>Moyenne</th>
                      <th style={thStyle}>p95</th>
                      <th style={thStyle}>p99</th>
                      <th style={thStyle}>Max</th>
                    </tr>
                  </thead>
                  <tbody>
                    {latencyStatsSorted.map(([tool, s]) => {
                      const slow = s.p95_ms > 5000  // > 5s en p95 = lent
                      const verySlow = s.p95_ms > 20000
                      const color = verySlow ? '#ef4444' : slow ? '#f59e0b' : undefined
                      return (
                        <tr key={tool} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                          <td style={tdStyle}><b>{tool}</b></td>
                          <td style={tdStyle}>{s.count}</td>
                          <td style={tdStyle}>{fmtLatency(s.p50_ms)}</td>
                          <td style={tdStyle}>{fmtLatency(s.avg_ms)}</td>
                          <td style={{ ...tdStyle, color }}>{fmtLatency(s.p95_ms)}</td>
                          <td style={{ ...tdStyle, color }}>{fmtLatency(s.p99_ms)}</td>
                          <td style={{ ...tdStyle, color: verySlow ? '#ef4444' : undefined }}>
                            {fmtLatency(s.max_ms)}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* ── 4. Coûts externes (user courant) ─────────────────────── */}
          <section style={sectionStyle}>
            <h2 style={sectionTitleStyle}>💰 Coûts externes OpenClaw (toi)</h2>
            <div style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--accent-silver)', marginBottom: '0.6rem' }}>
              Total : ${data.external_cost_mine.total_usd.toFixed(4)}
            </div>
            {costByToolSorted.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                Aucun appel outil OpenClaw payant enregistré.
              </div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    <th style={thStyle}>Tool</th>
                    <th style={thStyle}>Appels</th>
                    <th style={thStyle}>Coût cumulé (USD)</th>
                  </tr>
                </thead>
                <tbody>
                  {costByToolSorted.map(([tool, info]) => (
                    <tr key={tool} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                      <td style={tdStyle}><b>{tool}</b></td>
                      <td style={tdStyle}>{info.calls}</td>
                      <td style={{ ...tdStyle, color: info.usd > 0 ? '#f59e0b' : 'var(--text-muted)' }}>
                        ${info.usd.toFixed(4)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {/* ── 5. Stats globales (tous users) ───────────────────────── */}
          <section style={sectionStyle}>
            <h2 style={sectionTitleStyle}>🌍 Stats globales (tous users)</h2>
            <div style={{ fontSize: '0.88rem', color: 'var(--text-secondary)' }}>
              Total d'appels OpenClaw toutes sessions : <b>{data.external_cost_global.total_calls}</b>
            </div>
            {Object.keys(data.external_cost_global.total_by_user).length > 0 && (
              <table style={{ width: '100%', marginTop: '0.6rem', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    <th style={thStyle}>User</th>
                    <th style={thStyle}>Coût cumulé (USD)</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.external_cost_global.total_by_user).map(([u, usd]) => (
                    <tr key={u} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                      <td style={{ ...tdStyle, fontFamily: 'monospace' }}>{u.slice(0, 12)}…</td>
                      <td style={{ ...tdStyle, color: '#f59e0b' }}>${usd.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  )
}

const sectionStyle: React.CSSProperties = {
  marginTop: '1.5rem',
  padding: '1.25rem',
  background: 'rgba(255,255,255,0.02)',
  border: '1px solid var(--border)',
  borderRadius: 12,
}

const sectionTitleStyle: React.CSSProperties = {
  margin: '0 0 1rem 0',
  fontSize: '1.05rem',
  color: 'var(--accent-silver)',
  fontWeight: 600,
}

const thStyle: React.CSSProperties = {
  padding: '0.5rem 0.7rem',
  textAlign: 'left',
  fontSize: '0.75rem',
  fontWeight: 600,
  color: 'var(--text-muted)',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
}

const tdStyle: React.CSSProperties = {
  padding: '0.5rem 0.7rem',
  color: 'var(--text-secondary, #d0d0d0)',
}
