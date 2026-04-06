import { useState, useEffect, useCallback } from 'react';
import { api, API_BASE, getAuthHeaders } from '../api/client';

/* ── SVG Icons ─────────────────────────────────────────────────────────────── */

const IconFlask = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--accent-violet)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 3h6M10 3v7.4a2 2 0 0 1-.5 1.3L4 19a2 2 0 0 0 1.5 3h13a2 2 0 0 0 1.5-3l-5.5-7.3a2 2 0 0 1-.5-1.3V3" />
  </svg>
);

const IconFlaskSmall = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 3h6M10 3v7.4a2 2 0 0 1-.5 1.3L4 19a2 2 0 0 0 1.5 3h13a2 2 0 0 0 1.5-3l-5.5-7.3a2 2 0 0 1-.5-1.3V3" />
  </svg>
);

const IconDownload = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="7 10 12 15 17 10" />
    <line x1="12" y1="15" x2="12" y2="3" />
  </svg>
);

const IconTrash = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
    <path d="M10 11v6M14 11v6" />
    <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
  </svg>
);

const IconSpinner = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--accent-violet)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ animation: 'spin 1s linear infinite' }}>
    <path d="M12 2a10 10 0 0 1 10 10" />
  </svg>
);

const IconDiamond = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="var(--accent-violet)" stroke="var(--accent-violet)" strokeWidth="1">
    <polygon points="12 2 22 12 12 22 2 12" />
  </svg>
);

const IconFileText = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent-silver)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ display: 'inline', verticalAlign: 'middle', marginRight: 6 }}>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
    <line x1="16" y1="13" x2="8" y2="13" />
    <line x1="16" y1="17" x2="8" y2="17" />
    <line x1="10" y1="9" x2="8" y2="9" />
  </svg>
);

/* ── Types ──────────────────────────────────────────────────────────────────── */

interface Plan {
  name: string;
  duration_months: number;
  difficulty: string;
  color: string;
}

interface Scenario {
  id: string;
  title: string;
  hypothesis: string;
  created_at: string;
  result_json?: string;
  summary?: string;
  ai_analysis?: string;
}

/* ── Component ─────────────────────────────────────────────────────────────── */

export default function ScenariosPage() {
  const [title, setTitle] = useState('');
  const [hypothesis, setHypothesis] = useState('');
  const [loading, setLoading] = useState(false);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [lastResult, setLastResult] = useState<Scenario | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const fetchScenarios = useCallback(async () => {
    try {
      const data = await api.getScenarios();
      setScenarios(data || []);
    } catch {
      /* silent */
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    fetchScenarios();
  }, [fetchScenarios]);

  const handleSubmit = async () => {
    if (!title.trim() || !hypothesis.trim()) return;
    setLoading(true);
    setError(null);
    setLastResult(null);
    try {
      const result = await api.createScenario({
        title: title.trim(),
        hypothesis: hypothesis.trim(),
        variables: [],
      });
      setLastResult(result);
      setTitle('');
      setHypothesis('');
      fetchScenarios();
    } catch (err: any) {
      setError(err?.message || 'Erreur lors de la simulation');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.deleteScenario(id);
      setScenarios((prev) => prev.filter((s) => s.id !== id));
      if (lastResult?.id === id) setLastResult(null);
    } catch {
      /* silent */
    }
  };

  const handleDownloadPdf = async (scenarioId: string, scenarioTitle: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/scenarios/${scenarioId}/export`, {
        headers: getAuthHeaders(),
      });
      if (!res.ok) throw new Error('Erreur lors du téléchargement');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const safeTitle = scenarioTitle
        .replace(/[^a-zA-Z0-9àâäéèêëïîôùûüÿçÀÂÄÉÈÊËÏÎÔÙÛÜŸÇ _-]/g, '')
        .replace(/\s+/g, '_');
      // Méthode 1: lien programmatique
      const link = document.createElement('a');
      link.href = url;
      link.download = `${safeTitle}.pdf`;
      link.style.display = 'none';
      document.body.appendChild(link);
      link.click();
      setTimeout(() => {
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
      }, 1000);
      setToast('PDF telecharge et sauvegarde dans Hypotheses');
      setTimeout(() => setToast(null), 4000);
    } catch (e: any) {
      console.error('PDF download error:', e);
      window.open(`${API_BASE}/api/scenarios/${scenarioId}/export`, '_blank');
      setToast('PDF ouvert dans un nouvel onglet');
      setTimeout(() => setToast(null), 3000);
    }
  };

  const formatDate = (dateStr: string) => {
    try {
      return new Date(dateStr).toLocaleDateString('fr-FR', {
        day: 'numeric',
        month: 'long',
        year: 'numeric',
      });
    } catch {
      return dateStr;
    }
  };

  /* ── Styles ────────────────────────────────────────────────────────────── */

  const styles = {
    page: {
      maxWidth: 780,
      margin: '0 auto',
      padding: '2rem 1.5rem',
    } as React.CSSProperties,
    headerSection: {
      textAlign: 'center' as const,
      marginBottom: '2.5rem',
    } as React.CSSProperties,
    headerTitle: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '0.6rem',
      fontSize: '1.8rem',
      fontWeight: 700,
      color: '#fff',
      marginBottom: '0.5rem',
    } as React.CSSProperties,
    headerSubtitle: {
      color: 'var(--text-muted)',
      fontSize: '1rem',
      lineHeight: 1.5,
    } as React.CSSProperties,
    card: {
      background: 'var(--bg-card)',
      border: '1px solid var(--border)',
      borderRadius: 12,
      padding: '1.8rem',
      marginBottom: '1.5rem',
    } as React.CSSProperties,
    label: {
      display: 'block',
      color: 'var(--accent-silver)',
      fontSize: '0.85rem',
      fontWeight: 600,
      marginBottom: '0.4rem',
      letterSpacing: '0.03em',
    } as React.CSSProperties,
    input: {
      width: '100%',
      padding: '0.7rem 1rem',
      background: 'rgba(255,255,255,0.04)',
      border: '1px solid var(--border)',
      borderRadius: 8,
      color: '#fff',
      fontSize: '0.95rem',
      outline: 'none',
      transition: 'border-color 0.2s',
      boxSizing: 'border-box' as const,
    } as React.CSSProperties,
    textarea: {
      width: '100%',
      padding: '0.7rem 1rem',
      background: 'rgba(255,255,255,0.04)',
      border: '1px solid var(--border)',
      borderRadius: 8,
      color: '#fff',
      fontSize: '0.95rem',
      outline: 'none',
      resize: 'vertical' as const,
      minHeight: 120,
      fontFamily: 'inherit',
      lineHeight: 1.5,
      transition: 'border-color 0.2s',
      boxSizing: 'border-box' as const,
    } as React.CSSProperties,
    btnPrimary: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.5rem',
      padding: '0.75rem 1.8rem',
      background: 'linear-gradient(135deg, var(--accent-violet), var(--accent-violet-light))',
      color: '#fff',
      border: 'none',
      borderRadius: 8,
      fontSize: '0.95rem',
      fontWeight: 600,
      cursor: 'pointer',
      transition: 'opacity 0.2s, transform 0.1s',
      marginTop: '1rem',
    } as React.CSSProperties,
    btnDisabled: {
      opacity: 0.5,
      cursor: 'not-allowed',
    } as React.CSSProperties,
    loadingBox: {
      display: 'flex',
      alignItems: 'center',
      gap: '0.8rem',
      padding: '1.2rem 1.5rem',
      background: 'rgba(139,92,246,0.08)',
      border: '1px solid rgba(139,92,246,0.25)',
      borderRadius: 10,
      color: 'var(--accent-violet-light)',
      fontSize: '0.95rem',
      marginBottom: '1.5rem',
    } as React.CSSProperties,
    resultCard: {
      background: 'var(--bg-card)',
      border: '1px solid var(--accent-violet)',
      borderRadius: 12,
      padding: '1.5rem 1.8rem',
      marginBottom: '2rem',
    } as React.CSSProperties,
    resultHeader: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
      marginBottom: '1rem',
    } as React.CSSProperties,
    resultTitle: {
      fontSize: '1.15rem',
      fontWeight: 600,
      color: '#fff',
    } as React.CSSProperties,
    resultDate: {
      fontSize: '0.8rem',
      color: 'var(--text-muted)',
      marginTop: '0.2rem',
    } as React.CSSProperties,
    resultSummary: {
      color: 'var(--text-muted)',
      fontSize: '0.9rem',
      lineHeight: 1.6,
      marginBottom: '1.2rem',
    } as React.CSSProperties,
    btnDownload: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.5rem',
      padding: '0.6rem 1.4rem',
      background: 'linear-gradient(135deg, var(--accent-violet), var(--accent-violet-light))',
      color: '#fff',
      border: 'none',
      borderRadius: 8,
      fontSize: '0.9rem',
      fontWeight: 600,
      cursor: 'pointer',
      transition: 'opacity 0.2s',
    } as React.CSSProperties,
    sectionTitle: {
      display: 'flex',
      alignItems: 'center',
      gap: '0.5rem',
      fontSize: '1.2rem',
      fontWeight: 600,
      color: '#fff',
      marginBottom: '1rem',
      marginTop: '1rem',
    } as React.CSSProperties,
    scenarioCard: {
      background: 'var(--bg-card)',
      border: '1px solid var(--border)',
      borderRadius: 10,
      padding: '1.2rem 1.5rem',
      marginBottom: '0.8rem',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: '1rem',
    } as React.CSSProperties,
    scenarioInfo: {
      flex: 1,
      minWidth: 0,
    } as React.CSSProperties,
    scenarioTitle: {
      fontSize: '1rem',
      fontWeight: 600,
      color: '#fff',
      whiteSpace: 'nowrap' as const,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      display: 'flex',
      alignItems: 'center',
    } as React.CSSProperties,
    scenarioDate: {
      fontSize: '0.78rem',
      color: 'var(--text-muted)',
      marginTop: '0.2rem',
    } as React.CSSProperties,
    scenarioActions: {
      display: 'flex',
      alignItems: 'center',
      gap: '0.5rem',
      flexShrink: 0,
    } as React.CSSProperties,
    btnSmall: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.35rem',
      padding: '0.4rem 0.9rem',
      borderRadius: 6,
      fontSize: '0.82rem',
      fontWeight: 500,
      cursor: 'pointer',
      border: 'none',
      transition: 'opacity 0.2s',
    } as React.CSSProperties,
    btnSmallDownload: {
      background: 'rgba(139,92,246,0.15)',
      color: 'var(--accent-violet-light)',
    } as React.CSSProperties,
    btnSmallDelete: {
      background: 'rgba(239,68,68,0.1)',
      color: '#ef4444',
    } as React.CSSProperties,
    errorBox: {
      padding: '0.8rem 1.2rem',
      background: 'rgba(239,68,68,0.08)',
      border: '1px solid rgba(239,68,68,0.3)',
      borderRadius: 8,
      color: '#ef4444',
      fontSize: '0.9rem',
      marginBottom: '1rem',
    } as React.CSSProperties,
    emptyState: {
      textAlign: 'center' as const,
      color: 'var(--text-muted)',
      fontSize: '0.9rem',
      padding: '2rem 0',
    } as React.CSSProperties,
    fieldGroup: {
      marginBottom: '1.2rem',
    } as React.CSSProperties,
  };

  /* ── Render ────────────────────────────────────────────────────────────── */

  const canSubmit = title.trim().length > 0 && hypothesis.trim().length > 0 && !loading;

  return (
    <div className="animate-fade-in" style={styles.page}>
      {/* Keyframes for spinner */}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      {/* Toast notification */}
      {toast && (
        <div style={{
          position: 'fixed', bottom: '2rem', left: '50%', transform: 'translateX(-50%)',
          padding: '0.6rem 1.2rem', borderRadius: '10px', zIndex: 9999,
          background: 'rgba(16,185,129,0.15)', border: '1px solid rgba(16,185,129,0.3)',
          color: '#10b981', fontSize: '0.82rem', fontWeight: 600,
          backdropFilter: 'blur(12px)', boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
          animation: 'agent-msg-in 0.3s ease forwards',
        }}>
          {toast}
        </div>
      )}

      {/* Header */}
      <div style={styles.headerSection}>
        <div style={styles.headerTitle}>
          <IconFlask />
          Formuler une hypothèse
        </div>
        <p style={styles.headerSubtitle}>
          Formulez une hypothèse et obtenez 3 plans d'action personnalisés avec leurs délais
        </p>
      </div>

      {/* Simulation form */}
      <div style={styles.card}>
        <div style={styles.fieldGroup}>
          <label style={styles.label}>Titre</label>
          <input
            type="text"
            style={styles.input}
            placeholder="Ex: Changement de carrière..."
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={loading}
          />
        </div>

        <div style={styles.fieldGroup}>
          <label style={styles.label}>Description de l'événement</label>
          <textarea
            style={styles.textarea}
            placeholder="Décrivez en détail votre hypothèse et le contexte..."
            value={hypothesis}
            onChange={(e) => setHypothesis(e.target.value)}
            disabled={loading}
          />
        </div>

        <button
          style={{
            ...styles.btnPrimary,
            ...(canSubmit ? {} : styles.btnDisabled),
          }}
          disabled={!canSubmit}
          onClick={handleSubmit}
        >
          <IconFlaskSmall />
          Générer l'analyse
        </button>
      </div>

      {/* Loading */}
      {loading && (
        <div style={styles.loadingBox}>
          <IconSpinner />
          Analyse en cours... L'IA génère vos plans d'action personnalisés...
        </div>
      )}

      {/* Error */}
      {error && <div style={styles.errorBox}>{error}</div>}

      {/* Result */}
      {lastResult && (
        <div className="animate-fade-in" style={styles.resultCard}>
          <div style={styles.resultHeader}>
            <div>
              <div style={styles.resultTitle}>{lastResult.title}</div>
              <div style={styles.resultDate}>
                {lastResult.created_at ? formatDate(lastResult.created_at) : ''}
              </div>
            </div>
          </div>

          {/* Plans d'action */}
          {(() => {
            try {
              const result = JSON.parse(lastResult.result_json || '{}');
              const plans: Plan[] = result.plans || [];
              if (plans.length > 0) {
                const planColors: Record<string, string> = {
                  success: '#10b981', primary: '#6366f1', danger: '#ef4444',
                };
                return (
                  <div style={{ display: 'flex', gap: '0.8rem', marginBottom: '1.2rem', flexWrap: 'wrap' as const }}>
                    {plans.map((p, i) => (
                      <div key={i} style={{
                        flex: '1 1 140px',
                        background: `${planColors[p.color] || '#6366f1'}12`,
                        border: `1px solid ${planColors[p.color] || '#6366f1'}40`,
                        borderRadius: 10,
                        padding: '0.8rem 1rem',
                        borderTop: `3px solid ${planColors[p.color] || '#6366f1'}`,
                      }}>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' as const, letterSpacing: '0.05em' }}>
                          {p.name}
                        </div>
                        <div style={{ fontSize: '1.4rem', fontWeight: 700, color: planColors[p.color] || '#6366f1', marginTop: '0.3rem' }}>
                          {p.duration_months} mois
                        </div>
                      </div>
                    ))}
                  </div>
                );
              }
            } catch { /* ignore */ }
            return null;
          })()}

          <button
            style={styles.btnDownload}
            onClick={() => handleDownloadPdf(lastResult.id, lastResult.title)}
          >
            <IconDownload />
            Télécharger le rapport PDF
          </button>
        </div>
      )}

      {/* Saved list */}
      <div style={styles.sectionTitle}>
        <IconDiamond />
        Mes analyses sauvegardées
      </div>

      {loadingList ? (
        <div style={styles.emptyState}>Chargement...</div>
      ) : scenarios.length === 0 ? (
        <div style={styles.emptyState}>
          Aucune analyse sauvegardée. Formulez votre première hypothèse ci-dessus.
        </div>
      ) : (
        scenarios.map((s) => (
          <div key={s.id} className="animate-fade-in" style={styles.scenarioCard}>
            <div style={styles.scenarioInfo}>
              <div style={styles.scenarioTitle}>
                <IconFileText />
                {s.title}
              </div>
              <div style={styles.scenarioDate}>
                {s.created_at ? formatDate(s.created_at) : ''}
              </div>
            </div>
            <div style={styles.scenarioActions}>
              <button
                style={{ ...styles.btnSmall, ...styles.btnSmallDownload }}
                onClick={() => handleDownloadPdf(s.id, s.title)}
                title="Télécharger le PDF"
              >
                <IconDownload />
                PDF
              </button>
              <button
                style={{ ...styles.btnSmall, ...styles.btnSmallDelete }}
                onClick={() => handleDelete(s.id)}
                title="Supprimer"
              >
                <IconTrash />
              </button>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
