// Page Workspace — Projets, Documents, Templates, Base de connaissances
import { useState, useEffect } from 'react'
import { api } from '../api/client'

// ── Types locaux ────────────────────────────────────────────────────────────
interface Project {
  id: string
  name: string
  description: string
  category: string
  file_count: number
  created_at: string
}

interface Document {
  id: string
  title: string
  type: string
  project_name: string
  date: string
  size: number
}

interface Template {
  id: string
  name: string
  description: string
  category: string
  created_at: string
}

interface KnowledgeEntry {
  id: string
  title: string
  content: string
  category: string
  created_at: string
}

// ── Icones SVG inline ────────────────────────────────────────────────────────
function IconFolder({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
    </svg>
  )
}

function IconPlus({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  )
}

function IconTrash({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  )
}

function IconSearch({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  )
}

function IconFile({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  )
}

function IconTemplate({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <line x1="3" y1="9" x2="21" y2="9" />
      <line x1="9" y1="21" x2="9" y2="9" />
    </svg>
  )
}

function IconBook({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </svg>
  )
}

function IconDownload({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  )
}

function IconX({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' })
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} o`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`
}

function fileTypeColor(type: string): string {
  switch (type.toLowerCase()) {
    case 'pdf': return '#ef4444'
    case 'docx': return '#3b82f6'
    case 'xlsx': return '#22c55e'
    case 'pptx': return '#f59e0b'
    default: return 'var(--text-muted)'
  }
}

// ── Styles partages ─────────────────────────────────────────────────────────
const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: '0.75rem',
  padding: '1.25rem',
  transition: 'border-color 0.2s',
  cursor: 'default',
}

const btnPrimary: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '0.4rem',
  padding: '0.5rem 1rem',
  borderRadius: '0.5rem',
  border: '1px solid var(--accent-violet)',
  background: 'rgba(139,92,246,0.15)',
  color: '#a78bfa',
  fontSize: '0.8rem',
  fontWeight: 600,
  cursor: 'pointer',
  transition: 'all 0.15s',
}

const btnDanger: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '0.3rem',
  padding: '0.35rem 0.6rem',
  borderRadius: '0.4rem',
  border: '1px solid rgba(239,68,68,0.3)',
  background: 'rgba(239,68,68,0.1)',
  color: '#f87171',
  fontSize: '0.7rem',
  fontWeight: 600,
  cursor: 'pointer',
  transition: 'all 0.15s',
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '0.6rem 0.75rem',
  borderRadius: '0.5rem',
  border: '1px solid var(--border)',
  background: 'var(--bg-surface)',
  color: 'var(--text-primary)',
  fontSize: '0.85rem',
  outline: 'none',
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: '0.75rem',
  fontWeight: 600,
  color: 'var(--text-muted)',
  marginBottom: '0.35rem',
  textTransform: 'uppercase' as const,
  letterSpacing: '0.05em',
}

// ── Composant principal ─────────────────────────────────────────────────────
type TabKey = 'projets' | 'documents' | 'templates' | 'knowledge'

export default function WorkspacePage() {
  const [activeTab, setActiveTab] = useState<TabKey>('projets')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Data
  const [projects, setProjects] = useState<Project[]>([])
  const [documents, setDocuments] = useState<Document[]>([])
  const [templates, setTemplates] = useState<Template[]>([])
  const [knowledge, setKnowledge] = useState<KnowledgeEntry[]>([])

  // Modals
  const [showNewProject, setShowNewProject] = useState(false)
  const [showNewDoc, setShowNewDoc] = useState(false)
  const [showNewKnowledge, setShowNewKnowledge] = useState(false)

  // Forms
  const [projectForm, setProjectForm] = useState({ name: '', description: '', category: 'general' })
  const [docForm, setDocForm] = useState({ title: '', type: 'pdf', project_name: '' })
  const [knowledgeForm, setKnowledgeForm] = useState({ title: '', content: '', category: 'note' })
  const [knowledgeSearch, setKnowledgeSearch] = useState('')

  // Export dropdown
  const [exportDropdown, setExportDropdown] = useState<string | null>(null)

  useEffect(() => {
    loadData()
  }, [])

  async function loadData() {
    setLoading(true)
    setError(null)
    try {
      const [p, d, t, k] = await Promise.all([
        api.getProjects().catch(() => []),
        api.getDocuments().catch(() => []),
        api.getTemplates().catch(() => []),
        api.getKnowledge().catch(() => []),
      ])
      setProjects(p)
      setDocuments(d)
      setTemplates(t)
      setKnowledge(k)
    } catch (e: any) {
      setError(e.message || 'Erreur de chargement')
    } finally {
      setLoading(false)
    }
  }

  async function handleCreateProject() {
    if (!projectForm.name.trim()) return
    try {
      const created = await api.createProject(projectForm)
      setProjects(prev => [created, ...prev])
      setProjectForm({ name: '', description: '', category: 'general' })
      setShowNewProject(false)
    } catch (e: any) {
      setError(e.message)
    }
  }

  async function handleDeleteProject(id: string) {
    try {
      await api.deleteProject(id)
      setProjects(prev => prev.filter(p => p.id !== id))
    } catch (e: any) {
      setError(e.message)
    }
  }

  async function handleDeleteDocument(id: string) {
    try {
      await api.deleteDocument(id)
      setDocuments(prev => prev.filter(d => d.id !== id))
    } catch (e: any) {
      setError(e.message)
    }
  }

  async function handleAddKnowledge() {
    if (!knowledgeForm.title.trim()) return
    try {
      const created = await api.addKnowledge(knowledgeForm)
      setKnowledge(prev => [created, ...prev])
      setKnowledgeForm({ title: '', content: '', category: 'note' })
      setShowNewKnowledge(false)
    } catch (e: any) {
      setError(e.message)
    }
  }

  async function handleSearchKnowledge() {
    if (!knowledgeSearch.trim()) {
      const k = await api.getKnowledge().catch(() => [])
      setKnowledge(k)
      return
    }
    try {
      const results = await api.searchKnowledge(knowledgeSearch)
      setKnowledge(results)
    } catch (e: any) {
      setError(e.message)
    }
  }

  async function handleDeleteKnowledge(id: string) {
    try {
      await api.deleteKnowledge(id)
      setKnowledge(prev => prev.filter(k => k.id !== id))
    } catch (e: any) {
      setError(e.message)
    }
  }

  const tabs: { key: TabKey; label: string; icon: React.ReactNode }[] = [
    { key: 'projets', label: 'Projets', icon: <IconFolder size={14} /> },
    { key: 'documents', label: 'Documents', icon: <IconFile size={14} /> },
    { key: 'templates', label: 'Templates', icon: <IconTemplate size={14} /> },
    { key: 'knowledge', label: 'Base de connaissances', icon: <IconBook size={14} /> },
  ]

  const categoryColors: Record<string, string> = {
    general: '#8b5cf6',
    carriere: '#3b82f6',
    finance: '#22c55e',
    sante: '#ef4444',
    relation: '#f59e0b',
    developpement: '#06b6d4',
  }

  return (
    <div className="page animate-fade-in">
      <div className="container page-content">

        {/* Header */}
        <div style={{ marginBottom: '2rem' }}>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', marginBottom: '0.25rem' }}>
            Espace de travail
          </p>
          <h1 style={{ fontSize: '1.75rem', color: 'var(--accent-silver)', marginBottom: '0.25rem' }}>
            Mon Workspace
          </h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
            Gerez vos projets, documents, templates et base de connaissances
          </p>
        </div>

        {/* Tab navigation */}
        <div style={{
          display: 'flex',
          gap: '0.25rem',
          marginBottom: '1.5rem',
          borderBottom: '1px solid var(--border)',
          paddingBottom: '0',
          overflowX: 'auto',
        }}>
          {tabs.map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.4rem',
                padding: '0.6rem 1rem',
                borderRadius: '0.5rem 0.5rem 0 0',
                border: 'none',
                borderBottom: activeTab === tab.key ? '2px solid var(--accent-violet)' : '2px solid transparent',
                background: activeTab === tab.key ? 'rgba(139,92,246,0.08)' : 'transparent',
                color: activeTab === tab.key ? '#a78bfa' : 'var(--text-muted)',
                fontSize: '0.8rem',
                fontWeight: activeTab === tab.key ? 600 : 400,
                cursor: 'pointer',
                transition: 'all 0.15s',
                whiteSpace: 'nowrap',
              }}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>

        {/* Error banner */}
        {error && (
          <div style={{
            padding: '0.75rem 1rem',
            borderRadius: '0.5rem',
            background: 'rgba(239,68,68,0.1)',
            border: '1px solid rgba(239,68,68,0.3)',
            color: '#f87171',
            fontSize: '0.8rem',
            marginBottom: '1rem',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}>
            <span>{error}</span>
            <button onClick={() => setError(null)} style={{ background: 'none', border: 'none', color: '#f87171', cursor: 'pointer' }}>
              <IconX size={14} />
            </button>
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
            <div className="spinner" style={{ margin: '0 auto 1rem' }} />
            Chargement...
          </div>
        )}

        {/* ── Tab: Projets ── */}
        {!loading && activeTab === 'projets' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                {projects.length} projet{projects.length !== 1 ? 's' : ''}
              </span>
              <button style={btnPrimary} onClick={() => setShowNewProject(true)}>
                <IconPlus size={14} /> Nouveau projet
              </button>
            </div>

            {projects.length === 0 ? (
              <div style={{ ...cardStyle, textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
                <IconFolder size={36} />
                <p style={{ marginTop: '0.75rem', fontSize: '0.85rem' }}>Aucun projet pour le moment</p>
                <p style={{ fontSize: '0.75rem' }}>Creez votre premier projet pour organiser vos documents</p>
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '1rem' }}>
                {projects.map(p => (
                  <div key={p.id} style={{ ...cardStyle, position: 'relative' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ color: categoryColors[p.category] || '#8b5cf6' }}>
                          <IconFolder size={20} />
                        </span>
                        <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
                          {p.name}
                        </h3>
                      </div>
                      <button style={{ ...btnDanger, padding: '0.25rem' }} onClick={() => handleDeleteProject(p.id)}>
                        <IconTrash size={12} />
                      </button>
                    </div>
                    {p.description && (
                      <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '0.5rem', lineHeight: 1.4 }}>
                        {p.description}
                      </p>
                    )}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '0.5rem' }}>
                      <span style={{
                        fontSize: '0.65rem',
                        padding: '0.15rem 0.5rem',
                        borderRadius: '999px',
                        background: `${categoryColors[p.category] || '#8b5cf6'}20`,
                        color: categoryColors[p.category] || '#8b5cf6',
                        fontWeight: 600,
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                      }}>
                        {p.category}
                      </span>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                        {p.file_count} fichier{p.file_count !== 1 ? 's' : ''} {'\u00B7'} {formatDate(p.created_at)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Tab: Documents ── */}
        {!loading && activeTab === 'documents' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                {documents.length} document{documents.length !== 1 ? 's' : ''}
              </span>
              <button style={btnPrimary} onClick={() => setShowNewDoc(true)}>
                <IconPlus size={14} /> Nouveau document
              </button>
            </div>

            {documents.length === 0 ? (
              <div style={{ ...cardStyle, textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
                <IconFile size={36} />
                <p style={{ marginTop: '0.75rem', fontSize: '0.85rem' }}>Aucun document</p>
                <p style={{ fontSize: '0.75rem' }}>Ajoutez des documents a vos projets</p>
              </div>
            ) : (
              <div style={{ ...cardStyle, padding: 0, overflow: 'hidden' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)' }}>
                      {['Titre', 'Type', 'Projet', 'Date', 'Taille', 'Actions'].map(h => (
                        <th key={h} style={{
                          padding: '0.75rem 1rem',
                          fontSize: '0.7rem',
                          fontWeight: 600,
                          color: 'var(--text-muted)',
                          textTransform: 'uppercase',
                          letterSpacing: '0.06em',
                          textAlign: 'left',
                        }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {documents.map(doc => (
                      <tr key={doc.id} style={{ borderBottom: '1px solid var(--border)' }}>
                        <td style={{ padding: '0.7rem 1rem', fontSize: '0.82rem', color: 'var(--text-primary)', fontWeight: 500 }}>
                          {doc.title}
                        </td>
                        <td style={{ padding: '0.7rem 1rem' }}>
                          <span style={{
                            fontSize: '0.65rem',
                            padding: '0.15rem 0.45rem',
                            borderRadius: '0.25rem',
                            background: `${fileTypeColor(doc.type)}20`,
                            color: fileTypeColor(doc.type),
                            fontWeight: 700,
                            textTransform: 'uppercase',
                          }}>
                            {doc.type}
                          </span>
                        </td>
                        <td style={{ padding: '0.7rem 1rem', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                          {doc.project_name || '---'}
                        </td>
                        <td style={{ padding: '0.7rem 1rem', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                          {formatDate(doc.date)}
                        </td>
                        <td style={{ padding: '0.7rem 1rem', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                          {formatSize(doc.size)}
                        </td>
                        <td style={{ padding: '0.7rem 1rem' }}>
                          <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', position: 'relative' }}>
                            <button
                              style={{
                                ...btnPrimary,
                                padding: '0.25rem 0.5rem',
                                fontSize: '0.7rem',
                              }}
                              onClick={() => setExportDropdown(exportDropdown === doc.id ? null : doc.id)}
                            >
                              <IconDownload size={12} /> Exporter
                            </button>
                            {exportDropdown === doc.id && (
                              <div style={{
                                position: 'absolute',
                                top: '100%',
                                right: 0,
                                marginTop: '0.25rem',
                                background: 'var(--bg-card)',
                                border: '1px solid var(--border)',
                                borderRadius: '0.5rem',
                                padding: '0.25rem',
                                zIndex: 10,
                                minWidth: '100px',
                                boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
                              }}>
                                {['PDF', 'DOCX', 'XLSX', 'PPTX'].map(fmt => (
                                  <button
                                    key={fmt}
                                    onClick={() => setExportDropdown(null)}
                                    style={{
                                      display: 'block',
                                      width: '100%',
                                      padding: '0.4rem 0.75rem',
                                      fontSize: '0.75rem',
                                      color: fileTypeColor(fmt),
                                      background: 'transparent',
                                      border: 'none',
                                      textAlign: 'left',
                                      cursor: 'pointer',
                                      borderRadius: '0.3rem',
                                      fontWeight: 600,
                                    }}
                                    onMouseEnter={e => (e.currentTarget.style.background = 'rgba(139,92,246,0.1)')}
                                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                                  >
                                    {fmt}
                                  </button>
                                ))}
                              </div>
                            )}
                            <button style={{ ...btnDanger, padding: '0.25rem 0.4rem' }} onClick={() => handleDeleteDocument(doc.id)}>
                              <IconTrash size={12} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ── Tab: Templates ── */}
        {!loading && activeTab === 'templates' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                {templates.length} template{templates.length !== 1 ? 's' : ''}
              </span>
            </div>

            {templates.length === 0 ? (
              <div style={{ ...cardStyle, textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
                <IconTemplate size={36} />
                <p style={{ marginTop: '0.75rem', fontSize: '0.85rem' }}>Aucun template</p>
                <p style={{ fontSize: '0.75rem' }}>Sauvegardez un document comme template pour le reutiliser</p>
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '1rem' }}>
                {templates.map(tpl => (
                  <div key={tpl.id} style={cardStyle}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                      <span style={{ color: 'var(--accent-violet)' }}><IconTemplate size={18} /></span>
                      <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
                        {tpl.name}
                      </h3>
                    </div>
                    {tpl.description && (
                      <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', lineHeight: 1.4, marginBottom: '0.5rem' }}>
                        {tpl.description}
                      </p>
                    )}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{
                        fontSize: '0.65rem',
                        padding: '0.15rem 0.5rem',
                        borderRadius: '999px',
                        background: 'rgba(139,92,246,0.15)',
                        color: '#a78bfa',
                        fontWeight: 600,
                      }}>
                        {tpl.category}
                      </span>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                        {formatDate(tpl.created_at)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Tab: Base de connaissances ── */}
        {!loading && activeTab === 'knowledge' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', gap: '0.75rem', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1, minWidth: '200px' }}>
                <div style={{ position: 'relative', flex: 1 }}>
                  <input
                    type="text"
                    placeholder="Rechercher..."
                    value={knowledgeSearch}
                    onChange={e => setKnowledgeSearch(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleSearchKnowledge()}
                    style={{ ...inputStyle, paddingLeft: '2rem' }}
                  />
                  <span style={{ position: 'absolute', left: '0.6rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }}>
                    <IconSearch size={14} />
                  </span>
                </div>
                <button
                  style={{ ...btnPrimary, padding: '0.6rem 0.75rem' }}
                  onClick={handleSearchKnowledge}
                >
                  <IconSearch size={14} />
                </button>
              </div>
              <button style={btnPrimary} onClick={() => setShowNewKnowledge(true)}>
                <IconPlus size={14} /> Ajouter
              </button>
            </div>

            {knowledge.length === 0 ? (
              <div style={{ ...cardStyle, textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
                <IconBook size={36} />
                <p style={{ marginTop: '0.75rem', fontSize: '0.85rem' }}>Base de connaissances vide</p>
                <p style={{ fontSize: '0.75rem' }}>Ajoutez des notes, contacts, analyses et recherches</p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {knowledge.map(k => (
                  <div key={k.id} style={{ ...cardStyle, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.3rem' }}>
                        <h4 style={{ fontSize: '0.88rem', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
                          {k.title}
                        </h4>
                        <span style={{
                          fontSize: '0.6rem',
                          padding: '0.1rem 0.4rem',
                          borderRadius: '999px',
                          background: 'rgba(139,92,246,0.12)',
                          color: '#a78bfa',
                          fontWeight: 600,
                          textTransform: 'uppercase',
                        }}>
                          {k.category}
                        </span>
                      </div>
                      <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', lineHeight: 1.4, margin: 0 }}>
                        {k.content.length > 180 ? k.content.slice(0, 180) + '...' : k.content}
                      </p>
                      <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '0.3rem', display: 'inline-block' }}>
                        {formatDate(k.created_at)}
                      </span>
                    </div>
                    <button style={btnDanger} onClick={() => handleDeleteKnowledge(k.id)}>
                      <IconTrash size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Modal: Nouveau projet ── */}
        {showNewProject && (
          <ModalOverlay onClose={() => setShowNewProject(false)}>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '1rem' }}>
              Nouveau projet
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              <div>
                <label style={labelStyle}>Nom du projet</label>
                <input
                  style={inputStyle}
                  placeholder="Mon projet..."
                  value={projectForm.name}
                  onChange={e => setProjectForm(p => ({ ...p, name: e.target.value }))}
                />
              </div>
              <div>
                <label style={labelStyle}>Description</label>
                <textarea
                  style={{ ...inputStyle, minHeight: '70px', resize: 'vertical' }}
                  placeholder="Description du projet..."
                  value={projectForm.description}
                  onChange={e => setProjectForm(p => ({ ...p, description: e.target.value }))}
                />
              </div>
              <div>
                <label style={labelStyle}>Categorie</label>
                <select
                  style={inputStyle}
                  value={projectForm.category}
                  onChange={e => setProjectForm(p => ({ ...p, category: e.target.value }))}
                >
                  {['general', 'carriere', 'finance', 'sante', 'relation', 'developpement'].map(c => (
                    <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
                  ))}
                </select>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                <button
                  style={{ ...btnPrimary, background: 'transparent', color: 'var(--text-muted)', border: '1px solid var(--border)' }}
                  onClick={() => setShowNewProject(false)}
                >
                  Annuler
                </button>
                <button style={btnPrimary} onClick={handleCreateProject}>
                  Creer
                </button>
              </div>
            </div>
          </ModalOverlay>
        )}

        {/* ── Modal: Nouveau document ── */}
        {showNewDoc && (
          <ModalOverlay onClose={() => setShowNewDoc(false)}>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '1rem' }}>
              Nouveau document
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              <div>
                <label style={labelStyle}>Titre</label>
                <input
                  style={inputStyle}
                  placeholder="Titre du document..."
                  value={docForm.title}
                  onChange={e => setDocForm(d => ({ ...d, title: e.target.value }))}
                />
              </div>
              <div>
                <label style={labelStyle}>Type</label>
                <select
                  style={inputStyle}
                  value={docForm.type}
                  onChange={e => setDocForm(d => ({ ...d, type: e.target.value }))}
                >
                  {['pdf', 'docx', 'xlsx', 'pptx'].map(t => (
                    <option key={t} value={t}>{t.toUpperCase()}</option>
                  ))}
                </select>
              </div>
              <div>
                <label style={labelStyle}>Projet</label>
                <select
                  style={inputStyle}
                  value={docForm.project_name}
                  onChange={e => setDocForm(d => ({ ...d, project_name: e.target.value }))}
                >
                  <option value="">-- Aucun --</option>
                  {projects.map(p => (
                    <option key={p.id} value={p.name}>{p.name}</option>
                  ))}
                </select>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                <button
                  style={{ ...btnPrimary, background: 'transparent', color: 'var(--text-muted)', border: '1px solid var(--border)' }}
                  onClick={() => setShowNewDoc(false)}
                >
                  Annuler
                </button>
                <button style={btnPrimary} onClick={() => setShowNewDoc(false)}>
                  Creer
                </button>
              </div>
            </div>
          </ModalOverlay>
        )}

        {/* ── Modal: Ajouter connaissance ── */}
        {showNewKnowledge && (
          <ModalOverlay onClose={() => setShowNewKnowledge(false)}>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '1rem' }}>
              Ajouter a la base de connaissances
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              <div>
                <label style={labelStyle}>Titre</label>
                <input
                  style={inputStyle}
                  placeholder="Titre..."
                  value={knowledgeForm.title}
                  onChange={e => setKnowledgeForm(k => ({ ...k, title: e.target.value }))}
                />
              </div>
              <div>
                <label style={labelStyle}>Contenu</label>
                <textarea
                  style={{ ...inputStyle, minHeight: '100px', resize: 'vertical' }}
                  placeholder="Contenu de la note..."
                  value={knowledgeForm.content}
                  onChange={e => setKnowledgeForm(k => ({ ...k, content: e.target.value }))}
                />
              </div>
              <div>
                <label style={labelStyle}>Categorie</label>
                <select
                  style={inputStyle}
                  value={knowledgeForm.category}
                  onChange={e => setKnowledgeForm(k => ({ ...k, category: e.target.value }))}
                >
                  {['note', 'recherche', 'contact', 'analyse'].map(c => (
                    <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
                  ))}
                </select>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                <button
                  style={{ ...btnPrimary, background: 'transparent', color: 'var(--text-muted)', border: '1px solid var(--border)' }}
                  onClick={() => setShowNewKnowledge(false)}
                >
                  Annuler
                </button>
                <button style={btnPrimary} onClick={handleAddKnowledge}>
                  Ajouter
                </button>
              </div>
            </div>
          </ModalOverlay>
        )}

      </div>
    </div>
  )
}

// ── Modal overlay ───────────────────────────────────────────────────────────
function ModalOverlay({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
        backdropFilter: 'blur(4px)',
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: '1rem',
        padding: '1.5rem',
        width: '90%',
        maxWidth: '420px',
        maxHeight: '80vh',
        overflowY: 'auto',
      }}>
        {children}
      </div>
    </div>
  )
}
