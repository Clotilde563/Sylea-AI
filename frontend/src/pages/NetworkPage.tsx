// Page Réseau — Premium social network experience
import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '../api/client'
import { WorkspacesSection } from './WorkspacesPage'

/* ── Animations ───────────────────────────────────────────────────────────── */

const animationStyles = `
@keyframes fadeInUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
@keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.05); } }
@keyframes shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }
@keyframes glow { 0%, 100% { box-shadow: 0 0 5px rgba(139,92,246,0.3); } 50% { box-shadow: 0 0 20px rgba(139,92,246,0.6); } }
@keyframes slideIn { from { opacity: 0; transform: translateX(-10px); } to { opacity: 1; transform: translateX(0); } }
@keyframes countUp { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
@keyframes celebrate { 0% { transform: scale(1); } 25% { transform: scale(1.3); } 50% { transform: scale(0.9); } 100% { transform: scale(1); } }
@keyframes gradientShift { 0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; } }
@keyframes ringPulse { 0%, 100% { opacity: 0.6; } 50% { opacity: 1; } }
@keyframes progressFill { from { width: 0%; } }
@keyframes float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }
@keyframes modalIn { from { opacity: 0; transform: scale(0.9) translateY(20px); } to { opacity: 1; transform: scale(1) translateY(0); } }
`

/* ── Icônes SVG inline ────────────────────────────────────────────────────── */

function IconFeed({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 11a9 9 0 0 1 9 9" /><path d="M4 4a16 16 0 0 1 16 16" /><circle cx="5" cy="19" r="1" />
    </svg>
  )
}

function IconSearch({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  )
}

function IconUsers({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  )
}

function IconStar({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  )
}

function IconStarFilled({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="#f59e0b" stroke="#f59e0b" strokeWidth="1">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  )
}

function IconTrophy({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6" /><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18" />
      <path d="M4 22h16" /><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20 7 22" />
      <path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20 17 22" />
      <path d="M18 2H6v7a6 6 0 0 0 12 0V2Z" />
    </svg>
  )
}

function IconHeart({ size = 18, filled = false }: { size?: number; filled?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={filled ? '#ef4444' : 'none'} stroke={filled ? '#ef4444' : 'currentColor'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
    </svg>
  )
}

function IconCheck({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

function IconX({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

function IconLink({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </svg>
  )
}

function IconClock({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
    </svg>
  )
}

function IconFlame({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z" />
    </svg>
  )
}

function IconMedal({ size = 20, color = '#f59e0b' }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="6" fill={color} fillOpacity="0.2" />
      <path d="M15.477 12.89 17 22l-5-3-5 3 1.523-9.11" />
    </svg>
  )
}

function IconPlus({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  )
}

function IconTarget({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="2" />
    </svg>
  )
}

function IconSend({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  )
}

/* ── Composants utilitaires ───────────────────────────────────────────────── */

function Avatar({ name, size = 42, glowColor = '#7c3aed' }: { name: string; size?: number; glowColor?: string }) {
  const initials = name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase()
  const colors = ['#7c3aed', '#6366f1', '#3b82f6', '#ec4899', '#10b981', '#f59e0b']
  const idx = name.split('').reduce((a, c) => a + c.charCodeAt(0), 0) % colors.length
  const bg = colors[idx]
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      background: `linear-gradient(135deg, ${bg}, ${bg}cc)`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: '#fff', fontWeight: 700, fontSize: size * 0.36,
      boxShadow: `0 0 0 3px ${glowColor}33, 0 0 12px ${glowColor}22`,
      animation: 'ringPulse 3s ease-in-out infinite',
      flexShrink: 0,
    }}>
      {initials}
    </div>
  )
}

function CircularGauge({ value, size = 52 }: { value: number; size?: number }) {
  const r = (size - 8) / 2
  const circ = 2 * Math.PI * r
  const offset = circ * (1 - value / 100)
  const color = value >= 60 ? '#22c55e' : value >= 30 ? '#f59e0b' : '#ef4444'
  return (
    <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="4" />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="4"
        strokeDasharray={circ} strokeDashoffset={offset} strokeLinecap="round"
        style={{ transition: 'stroke-dashoffset 1.2s ease-out' }} />
      <text x={size / 2} y={size / 2} textAnchor="middle" dominantBaseline="central"
        fill={color} fontSize={size * 0.26} fontWeight="700"
        style={{ transform: 'rotate(90deg)', transformOrigin: 'center' }}>
        {Math.round(value)}%
      </text>
    </svg>
  )
}

function AnimatedCounter({ target, suffix = '' }: { target: number; suffix?: string }) {
  const [val, setVal] = useState(0)
  useEffect(() => {
    let frame: number
    const start = performance.now()
    const duration = 1200
    const step = (now: number) => {
      const p = Math.min((now - start) / duration, 1)
      setVal(Math.round(p * target))
      if (p < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [target])
  return <span style={{ animation: 'countUp 0.6s ease-out' }}>{val}{suffix}</span>
}

/* ── Types ────────────────────────────────────────────────────────────────── */

interface VictoryPost {
  id: number; user_name: string; title: string; description: string;
  objective?: string; created_at: string; reactions: number; reacted?: boolean
}
interface DiscoverUser {
  id: number; name: string; objective: string; probability: number; connected?: boolean
}
interface Connection {
  id: number; user_id: number; name: string; objective: string; status: string; created_at: string
}
interface Mentor {
  id: number; name: string; specialty: string; rating: number; mentees: number; bio: string
}
interface Challenge {
  id: number; title: string; description: string; participants: number;
  max_participants: number; end_date: string; progress: number; joined?: boolean; color?: string
}
interface LeaderboardEntry {
  rank: number; name: string; score: number
}

type Tab = 'feed' | 'discover' | 'connections' | 'mentoring' | 'challenges' | 'workspaces'

const TABS: { key: Tab; label: string; icon: (s: number) => JSX.Element; color: string }[] = [
  { key: 'feed', label: "Fil d'actualit\u00e9", icon: (s) => <IconFeed size={s} />, color: '#7c3aed' },
  { key: 'discover', label: 'D\u00e9couvrir', icon: (s) => <IconSearch size={s} />, color: '#3b82f6' },
  { key: 'connections', label: 'Connexions', icon: (s) => <IconUsers size={s} />, color: '#10b981' },
  { key: 'mentoring', label: 'Mentorat', icon: (s) => <IconStar size={s} />, color: '#f59e0b' },
  { key: 'challenges', label: 'D\u00e9fis', icon: (s) => <IconTrophy size={s} />, color: '#ec4899' },
  { key: 'workspaces', label: '\u00c9quipes', icon: (s) => <IconUsers size={s} />, color: '#06b6d4' },
]

const POST_BORDER_COLORS = ['#7c3aed', '#3b82f6', '#ec4899', '#10b981', '#f59e0b', '#6366f1']
const CHALLENGE_GRADIENTS = [
  'linear-gradient(135deg, #7c3aed22, #6366f122)',
  'linear-gradient(135deg, #3b82f622, #06b6d422)',
  'linear-gradient(135deg, #ec489922, #f43f5e22)',
  'linear-gradient(135deg, #10b98122, #22c55e22)',
  'linear-gradient(135deg, #f59e0b22, #fbbf2422)',
]

/* ── Formatage du temps ───────────────────────────────────────────────────── */

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "à l'instant"
  if (mins < 60) return `il y a ${mins} min`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `il y a ${hrs}h`
  const days = Math.floor(hrs / 24)
  if (days < 7) return `il y a ${days}j`
  return `il y a ${Math.floor(days / 7)} sem.`
}

function daysLeft(dateStr: string): number {
  return Math.max(0, Math.ceil((new Date(dateStr).getTime() - Date.now()) / 86400000))
}

/* ── Données de démonstration ─────────────────────────────────────────────── */

const DEMO_FEED: VictoryPost[] = [
  { id: 1, user_name: 'Marie Dupont', title: 'Premier chapitre terminé !', description: "J'ai enfin fini d'écrire le premier chapitre de mon roman.", objective: 'Devenir écrivaine', created_at: new Date(Date.now() - 3600000).toISOString(), reactions: 12 },
  { id: 2, user_name: 'Lucas Martin', title: 'Certification obtenue', description: "Après 6 mois d'études, j'ai décroché ma certification en data science !", objective: 'Reconversion tech', created_at: new Date(Date.now() - 7200000).toISOString(), reactions: 24 },
  { id: 3, user_name: 'Sophie Bernard', title: '10 km en moins de 50 min', description: "Mon meilleur temps personnel sur la course de ce matin.", objective: 'Courir un marathon', created_at: new Date(Date.now() - 18000000).toISOString(), reactions: 8 },
  { id: 4, user_name: 'Éloïse Moreau', title: 'Présentation réussie', description: "J'ai présenté mon projet devant 200 personnes sans stress !", objective: 'Confiance en soi', created_at: new Date(Date.now() - 86400000).toISOString(), reactions: 31 },
]

const DEMO_DISCOVER: DiscoverUser[] = [
  { id: 10, name: 'Antoine Lefèvre', objective: 'Lancer ma startup', probability: 42 },
  { id: 11, name: 'Camille Rousseau', objective: 'Apprendre le japonais', probability: 67 },
  { id: 12, name: 'Théo Girard', objective: 'Devenir musicien professionnel', probability: 28 },
  { id: 13, name: 'Léa Fontaine', objective: 'Écrire un livre de cuisine', probability: 55 },
  { id: 14, name: 'Hugo Mercier', objective: 'Obtenir un MBA', probability: 73 },
  { id: 15, name: 'Chloé Roux', objective: 'Créer une ONG', probability: 38 },
]

const DEMO_CONNECTIONS: Connection[] = [
  { id: 20, user_id: 10, name: 'Marie Dupont', objective: 'Devenir écrivaine', status: 'accepted', created_at: new Date(Date.now() - 604800000).toISOString() },
  { id: 21, user_id: 11, name: 'Lucas Martin', objective: 'Reconversion tech', status: 'accepted', created_at: new Date(Date.now() - 1209600000).toISOString() },
]

const DEMO_PENDING: Connection[] = [
  { id: 30, user_id: 12, name: 'Théo Girard', objective: 'Devenir musicien professionnel', status: 'pending', created_at: new Date(Date.now() - 86400000).toISOString() },
]

const DEMO_MENTORS: Mentor[] = [
  { id: 40, name: 'Dr. Claire Vasseur', specialty: 'Développement de carrière', rating: 4.8, mentees: 12, bio: 'Coach certifiée avec 15 ans d\'expérience en accompagnement professionnel.' },
  { id: 41, name: 'François Delorme', specialty: 'Entrepreneuriat', rating: 4.6, mentees: 8, bio: 'Fondateur de 3 startups, mentor pour accélérateurs tech.' },
  { id: 42, name: 'Nadia El Amrani', specialty: 'Bien-être et performance', rating: 4.9, mentees: 15, bio: 'Psychologue du travail spécialisée en optimisation personnelle.' },
]

const DEMO_CHALLENGES: Challenge[] = [
  { id: 50, title: '30 jours de discipline', description: 'Respectez votre routine quotidienne pendant 30 jours sans exception.', participants: 47, max_participants: 100, end_date: new Date(Date.now() + 2592000000).toISOString(), progress: 45 },
  { id: 51, title: 'Lecture intensive', description: 'Lisez 4 livres en un mois pour enrichir vos connaissances.', participants: 23, max_participants: 50, end_date: new Date(Date.now() + 1728000000).toISOString(), progress: 62 },
  { id: 52, title: 'Objectif réseau', description: 'Connectez-vous avec 10 nouvelles personnes partageant vos ambitions.', participants: 31, max_participants: 75, end_date: new Date(Date.now() + 864000000).toISOString(), progress: 80 },
]

/* ══════════════════════════════════════════════════════════════════════════ */
/*  COMPOSANT PRINCIPAL                                                      */
/* ══════════════════════════════════════════════════════════════════════════ */

export default function NetworkPage() {
  // Lit `?tab=workspaces` (ou autre) depuis l'URL pour pre-selectionner l'onglet.
  // Utile pour les liens externes (ex: NavBar bouton "Workspaces" -> /reseau?tab=workspaces).
  const _initialTab: Tab = (() => {
    try {
      const q = new URLSearchParams(window.location.search).get('tab')
      const valid: Tab[] = ['feed', 'discover', 'connections', 'mentoring', 'challenges', 'workspaces']
      if (q && (valid as string[]).includes(q)) return q as Tab
    } catch { /* SSR safe */ }
    return 'feed'
  })()
  const [tab, setTab] = useState<Tab>(_initialTab)

  // Data states
  const [feed, setFeed] = useState<VictoryPost[]>(DEMO_FEED)
  const [discover, setDiscover] = useState<DiscoverUser[]>(DEMO_DISCOVER)
  const [connections, setConnections] = useState<Connection[]>(DEMO_CONNECTIONS)
  const [pending, setPending] = useState<Connection[]>(DEMO_PENDING)
  const [mentors, setMentors] = useState<Mentor[]>(DEMO_MENTORS)
  const [challenges, setChallenges] = useState<Challenge[]>(DEMO_CHALLENGES)
  const [searchQuery, setSearchQuery] = useState('')
  const [leaderboardModal, setLeaderboardModal] = useState<{ challengeId: number; entries: LeaderboardEntry[] } | null>(null)
  const [celebratedIds, setCelebratedIds] = useState<Set<number>>(new Set())

  // Try loading from API, fall back to demo data
  useEffect(() => {
    api.getVictoriesFeed?.().then((d: any) => d?.length && setFeed(d)).catch(() => {})
    api.discoverUsers?.().then((d: any) => d?.length && setDiscover(d)).catch(() => {})
    api.getConnections?.().then((d: any) => d?.length && setConnections(d)).catch(() => {})
    api.getPendingConnections?.().then((d: any) => d?.length && setPending(d)).catch(() => {})
    api.getMentors?.().then((d: any) => d?.length && setMentors(d)).catch(() => {})
    api.getChallenges?.().then((d: any) => d?.length && setChallenges(d)).catch(() => {})
  }, [])

  /* ── Handlers ─────────────────────────────────────────────────────────── */

  const handleCelebrate = useCallback((id: number) => {
    setCelebratedIds(prev => { const s = new Set(prev); s.add(id); return s })
    setFeed(prev => prev.map(p => p.id === id ? { ...p, reactions: p.reactions + 1, reacted: true } : p))
    api.reactToVictory?.(id).catch(() => {})
  }, [])

  const handleConnect = useCallback((userId: number) => {
    setDiscover(prev => prev.map(u => u.id === userId ? { ...u, connected: true } : u))
    api.sendConnectionRequest?.(userId).catch(() => {})
  }, [])

  const handleAccept = useCallback((id: number) => {
    const conn = pending.find(c => c.id === id)
    if (conn) {
      setPending(prev => prev.filter(c => c.id !== id))
      setConnections(prev => [...prev, { ...conn, status: 'accepted' }])
    }
    api.acceptConnection?.(id).catch(() => {})
  }, [pending])

  const handleReject = useCallback((id: number) => {
    setPending(prev => prev.filter(c => c.id !== id))
    api.rejectConnection?.(id).catch(() => {})
  }, [])

  const handleRequestMentor = useCallback((mentorId: number) => {
    api.requestMentoring?.({ mentor_user_id: mentorId }).catch(() => {})
  }, [])

  const handleJoinChallenge = useCallback((id: number) => {
    setChallenges(prev => prev.map(c => c.id === id ? { ...c, joined: true, participants: c.participants + 1 } : c))
    api.joinChallenge?.(id).catch(() => {})
  }, [])

  const handleLeaderboard = useCallback(async (id: number) => {
    let entries: LeaderboardEntry[] = [
      { rank: 1, name: 'Marie Dupont', score: 980 },
      { rank: 2, name: 'Lucas Martin', score: 875 },
      { rank: 3, name: 'Sophie Bernard', score: 820 },
      { rank: 4, name: 'Antoine Lefèvre', score: 740 },
      { rank: 5, name: 'Camille Rousseau', score: 695 },
    ]
    try {
      const data = await api.getChallengeLeaderboard?.(id)
      if (data?.length) entries = data
    } catch {}
    setLeaderboardModal({ challengeId: id, entries })
  }, [])

  const filteredDiscover = searchQuery
    ? discover.filter(u =>
        u.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        u.objective.toLowerCase().includes(searchQuery.toLowerCase()))
    : discover

  /* ── Render ───────────────────────────────────────────────────────────── */

  return (
    <div className="page">
      <style>{animationStyles}</style>
      <div className="container page-content animate-fade-in">

        {/* ═══ HEADER BANNER ═══ */}
        <div style={{
          background: 'linear-gradient(135deg, #1a0533, #0f172a, #1e1b4b)',
          borderRadius: 16, padding: '36px 32px 28px', marginBottom: 28,
          position: 'relative', overflow: 'hidden',
        }}>
          {/* Decorative orbs */}
          <div style={{
            position: 'absolute', top: -40, right: -40, width: 180, height: 180,
            borderRadius: '50%', background: 'radial-gradient(circle, rgba(124,58,237,0.2), transparent)',
            animation: 'float 6s ease-in-out infinite',
          }} />
          <div style={{
            position: 'absolute', bottom: -30, left: 60, width: 120, height: 120,
            borderRadius: '50%', background: 'radial-gradient(circle, rgba(99,102,241,0.15), transparent)',
            animation: 'float 8s ease-in-out infinite 1s',
          }} />

          <h1 style={{
            fontSize: 32, fontWeight: 800, color: '#fff', marginBottom: 6,
            textShadow: '0 0 30px rgba(139,92,246,0.5), 0 0 60px rgba(139,92,246,0.2)',
            letterSpacing: '-0.02em',
          }}>
            R&eacute;seau Syl&eacute;a
          </h1>
          <p style={{
            color: 'rgba(255,255,255,0.6)', fontSize: 15, marginBottom: 24, fontWeight: 400,
          }}>
            Partagez vos victoires, trouvez des alli&eacute;s, progressez ensemble
          </p>

          {/* Stats row */}
          <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
            {[
              { icon: <IconUsers size={20} />, value: 1247, label: 'membres', color: '#7c3aed' },
              { icon: <IconFlame size={20} />, value: 89, label: 'd\u00e9fis actifs', color: '#22c55e' },
              { icon: <IconTrophy size={20} />, value: 3482, label: 'victoires partag\u00e9es', color: '#f59e0b' },
            ].map((stat, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 10,
                animation: `fadeInUp 0.6s ease-out ${0.2 + i * 0.15}s both`,
              }}>
                <div style={{
                  width: 38, height: 38, borderRadius: 10,
                  background: `${stat.color}22`, color: stat.color,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  {stat.icon}
                </div>
                <div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: '#fff' }}>
                    <AnimatedCounter target={stat.value} />
                  </div>
                  <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    {stat.label}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ═══ TABS ═══ */}
        <div style={{
          display: 'flex', gap: 4, marginBottom: 24, overflowX: 'auto',
          background: 'var(--bg-card)', borderRadius: 12, padding: 4,
          border: '1px solid var(--border)',
        }}>
          {TABS.map(t => {
            const active = tab === t.key
            return (
              <button key={t.key} onClick={() => setTab(t.key)} style={{
                flex: 1, minWidth: 0, padding: '10px 8px',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                background: active ? `${t.color}18` : 'transparent',
                border: 'none', borderRadius: 8, cursor: 'pointer',
                color: active ? t.color : 'var(--text-muted)',
                fontWeight: active ? 700 : 500, fontSize: 13,
                transition: 'all 0.25s ease',
                transform: active ? 'scale(1.02)' : 'scale(1)',
                borderBottom: active ? `3px solid ${t.color}` : '3px solid transparent',
                position: 'relative',
              }}>
                <span style={{ opacity: active ? 1 : 0.6 }}>{t.icon(16)}</span>
                <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{t.label}</span>
              </button>
            )
          })}
        </div>

        {/* ═══ TAB CONTENT ═══ */}

        {/* ── FIL D'ACTUALITÉ ── */}
        {tab === 'feed' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {feed.length === 0 ? (
              <div style={{
                background: 'linear-gradient(135deg, #7c3aed11, #6366f111)',
                border: '1px solid var(--border)', borderRadius: 14,
                padding: 40, textAlign: 'center',
              }}>
                <IconTrophy size={40} />
                <p style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 16, marginTop: 12 }}>
                  Aucune victoire pour le moment
                </p>
                <p style={{ color: 'var(--text-muted)', fontSize: 14, marginTop: 4 }}>
                  Soyez le premier à partager votre r&eacute;ussite !
                </p>
              </div>
            ) : (
              feed.map((post, idx) => {
                const borderColor = POST_BORDER_COLORS[idx % POST_BORDER_COLORS.length]
                const isCelebrated = celebratedIds.has(post.id) || post.reacted
                return (
                  <div key={post.id} style={{
                    background: 'var(--bg-card)', borderRadius: 14,
                    border: '1px solid var(--border)',
                    borderLeft: `4px solid ${borderColor}`,
                    padding: '18px 20px',
                    animation: `fadeInUp 0.5s ease-out ${idx * 0.1}s both`,
                    transition: 'box-shadow 0.3s, transform 0.3s',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.boxShadow = `0 4px 20px ${borderColor}22`; e.currentTarget.style.transform = 'translateY(-2px)' }}
                  onMouseLeave={e => { e.currentTarget.style.boxShadow = 'none'; e.currentTarget.style.transform = 'translateY(0)' }}
                  >
                    {/* Post header */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
                      <Avatar name={post.user_name} size={44} glowColor={borderColor} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 700, color: 'var(--text-primary)', fontSize: 15 }}>
                          {post.user_name}
                        </div>
                        {post.objective && (
                          <div style={{ fontSize: 13, color: '#7c3aed', fontStyle: 'italic', opacity: 0.8 }}>
                            {post.objective}
                          </div>
                        )}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--text-muted)', fontSize: 12 }}>
                        <IconClock size={12} />
                        {timeAgo(post.created_at)}
                      </div>
                    </div>

                    {/* Post content */}
                    <h3 style={{ fontWeight: 700, fontSize: 16, color: 'var(--text-primary)', marginBottom: 6 }}>
                      {post.title}
                    </h3>
                    <p style={{ color: 'var(--text-muted)', fontSize: 14, lineHeight: 1.5, marginBottom: 14 }}>
                      {post.description}
                    </p>

                    {/* Celebrate button */}
                    <button onClick={() => !isCelebrated && handleCelebrate(post.id)} style={{
                      display: 'inline-flex', alignItems: 'center', gap: 6,
                      padding: '8px 16px', borderRadius: 20,
                      background: isCelebrated ? '#ef444418' : 'var(--bg-surface)',
                      border: `1px solid ${isCelebrated ? '#ef444444' : 'var(--border)'}`,
                      color: isCelebrated ? '#ef4444' : 'var(--text-muted)',
                      cursor: isCelebrated ? 'default' : 'pointer',
                      fontWeight: 600, fontSize: 13,
                      transition: 'all 0.3s',
                      animation: isCelebrated ? 'celebrate 0.5s ease-out' : 'none',
                    }}
                    onMouseEnter={e => { if (!isCelebrated) { e.currentTarget.style.background = '#ef444412'; e.currentTarget.style.color = '#ef4444' } }}
                    onMouseLeave={e => { if (!isCelebrated) { e.currentTarget.style.background = 'var(--bg-surface)'; e.currentTarget.style.color = 'var(--text-muted)' } }}
                    >
                      <span style={{ animation: isCelebrated ? 'celebrate 0.5s ease-out' : 'none' }}>
                        <IconHeart size={16} filled={!!isCelebrated} />
                      </span>
                      C&eacute;l&eacute;brer
                      <span style={{ fontWeight: 700, marginLeft: 2 }}>{post.reactions}</span>
                    </button>
                  </div>
                )
              })
            )}
          </div>
        )}

        {/* ── DÉCOUVRIR ── */}
        {tab === 'discover' && (
          <div>
            {/* Search bar */}
            <div style={{
              position: 'relative', marginBottom: 20,
            }}>
              <div style={{
                position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)',
                color: 'var(--text-muted)', pointerEvents: 'none',
              }}>
                <IconSearch size={18} />
              </div>
              <input
                type="text"
                placeholder="Rechercher par nom ou objectif..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                style={{
                  width: '100%', padding: '12px 16px 12px 42px',
                  background: 'var(--bg-card)', border: '2px solid var(--border)',
                  borderRadius: 12, color: 'var(--text-primary)',
                  fontSize: 14, outline: 'none',
                  transition: 'border-color 0.3s, box-shadow 0.3s',
                }}
                onFocus={e => { e.currentTarget.style.borderColor = '#7c3aed'; e.currentTarget.style.boxShadow = '0 0 0 4px rgba(124,58,237,0.15)' }}
                onBlur={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.boxShadow = 'none' }}
              />
            </div>

            {/* User grid */}
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
              gap: 16,
            }}>
              {filteredDiscover.map((user, idx) => {
                const gradIdx = idx % 5
                const topColor = ['#7c3aed', '#6366f1', '#3b82f6', '#ec4899', '#10b981'][gradIdx]
                return (
                  <div key={user.id} style={{
                    background: 'var(--bg-card)', borderRadius: 14,
                    border: '1px solid var(--border)', overflow: 'hidden',
                    animation: `slideIn 0.4s ease-out ${idx * 0.08}s both`,
                    transition: 'transform 0.3s, box-shadow 0.3s',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-4px)'; e.currentTarget.style.boxShadow = `0 8px 24px ${topColor}22` }}
                  onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = 'none' }}
                  >
                    {/* Gradient accent bar */}
                    <div style={{
                      height: 4,
                      background: `linear-gradient(90deg, ${topColor}, ${topColor}88)`,
                    }} />

                    <div style={{ padding: '20px 18px', textAlign: 'center' }}>
                      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 12 }}>
                        <Avatar name={user.name} size={56} glowColor={topColor} />
                      </div>
                      <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)', marginBottom: 4 }}>
                        {user.name}
                      </div>
                      <div style={{ fontSize: 13, color: '#7c3aed', marginBottom: 14, fontStyle: 'italic' }}>
                        {user.objective}
                      </div>

                      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
                        <CircularGauge value={user.probability} size={56} />
                      </div>

                      <button
                        onClick={() => !user.connected && handleConnect(user.id)}
                        disabled={user.connected}
                        style={{
                          width: '100%', padding: '10px 16px',
                          background: user.connected
                            ? 'var(--bg-surface)'
                            : 'linear-gradient(135deg, #7c3aed, #6366f1)',
                          border: user.connected ? '1px solid var(--border)' : 'none',
                          borderRadius: 10, color: user.connected ? '#22c55e' : '#fff',
                          fontWeight: 600, fontSize: 13, cursor: user.connected ? 'default' : 'pointer',
                          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                          transition: 'transform 0.2s, box-shadow 0.3s',
                        }}
                        onMouseEnter={e => { if (!user.connected) { e.currentTarget.style.transform = 'scale(1.03)'; e.currentTarget.style.boxShadow = '0 4px 15px rgba(124,58,237,0.4)' } }}
                        onMouseLeave={e => { e.currentTarget.style.transform = 'scale(1)'; e.currentTarget.style.boxShadow = 'none' }}
                      >
                        {user.connected ? <><IconCheck size={14} /> Connect&eacute;</> : <><IconLink size={14} /> Se connecter</>}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* ── CONNEXIONS ── */}
        {tab === 'connections' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>

            {/* Pending */}
            {pending.length > 0 && (
              <div>
                <h3 style={{
                  fontSize: 14, fontWeight: 700, color: 'var(--text-muted)',
                  textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 12,
                }}>
                  Demandes en attente ({pending.length})
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {pending.map((conn, idx) => (
                    <div key={conn.id} style={{
                      background: 'var(--bg-card)', borderRadius: 12,
                      border: '2px solid rgba(124,58,237,0.3)',
                      padding: '14px 18px',
                      display: 'flex', alignItems: 'center', gap: 14,
                      animation: `pulse 3s ease-in-out infinite, fadeInUp 0.4s ease-out ${idx * 0.1}s both`,
                    }}>
                      <Avatar name={conn.name} size={44} glowColor="#7c3aed" />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 700, color: 'var(--text-primary)', fontSize: 14 }}>{conn.name}</div>
                        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{conn.objective}</div>
                      </div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button onClick={() => handleAccept(conn.id)} style={{
                          padding: '8px 16px', borderRadius: 8, border: 'none',
                          background: 'linear-gradient(135deg, #22c55e, #10b981)',
                          color: '#fff', fontWeight: 600, fontSize: 13, cursor: 'pointer',
                          display: 'flex', alignItems: 'center', gap: 4,
                          transition: 'transform 0.2s',
                        }}
                        onMouseEnter={e => e.currentTarget.style.transform = 'scale(1.05)'}
                        onMouseLeave={e => e.currentTarget.style.transform = 'scale(1)'}
                        >
                          <IconCheck size={14} /> Accepter
                        </button>
                        <button onClick={() => handleReject(conn.id)} style={{
                          padding: '8px 16px', borderRadius: 8,
                          border: '1px solid var(--border)', background: 'var(--bg-surface)',
                          color: 'var(--text-muted)', fontWeight: 600, fontSize: 13, cursor: 'pointer',
                          display: 'flex', alignItems: 'center', gap: 4,
                          transition: 'transform 0.2s',
                        }}
                        onMouseEnter={e => e.currentTarget.style.transform = 'scale(1.05)'}
                        onMouseLeave={e => e.currentTarget.style.transform = 'scale(1)'}
                        >
                          <IconX size={14} /> Refuser
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Connected */}
            <div>
              <h3 style={{
                fontSize: 14, fontWeight: 700, color: 'var(--text-muted)',
                textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 12,
              }}>
                Vos connexions ({connections.length})
              </h3>
              {connections.length === 0 ? (
                <div style={{
                  background: 'linear-gradient(135deg, #10b98111, #22c55e11)',
                  border: '1px solid var(--border)', borderRadius: 14,
                  padding: 40, textAlign: 'center',
                }}>
                  <IconUsers size={36} />
                  <p style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 15, marginTop: 10 }}>
                    Pas encore de connexions
                  </p>
                  <p style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 4 }}>
                    D&eacute;couvrez des personnes qui partagent vos ambitions
                  </p>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {connections.map((conn, idx) => (
                    <div key={conn.id} style={{
                      background: 'var(--bg-card)', borderRadius: 12,
                      border: '1px solid var(--border)', padding: '14px 18px',
                      display: 'flex', alignItems: 'center', gap: 14,
                      animation: `fadeInUp 0.4s ease-out ${idx * 0.08}s both`,
                      transition: 'transform 0.2s, box-shadow 0.2s',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 4px 12px rgba(16,185,129,0.12)' }}
                    onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = 'none' }}
                    >
                      <div style={{ position: 'relative' }}>
                        <Avatar name={conn.name} size={44} glowColor="#10b981" />
                        {/* Online dot */}
                        <div style={{
                          position: 'absolute', bottom: 0, right: 0, width: 12, height: 12,
                          borderRadius: '50%', background: '#22c55e',
                          border: '2px solid var(--bg-card)',
                          boxShadow: '0 0 6px rgba(34,197,94,0.5)',
                        }} />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 700, color: 'var(--text-primary)', fontSize: 14 }}>{conn.name}</div>
                        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{conn.objective}</div>
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {timeAgo(conn.created_at)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── MENTORAT ── */}
        {tab === 'mentoring' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {mentors.map((mentor, idx) => (
              <div key={mentor.id} style={{
                background: 'var(--bg-card)', borderRadius: 14,
                border: '1px solid var(--border)', overflow: 'hidden',
                animation: `fadeInUp 0.5s ease-out ${idx * 0.12}s both`,
                transition: 'transform 0.3s, box-shadow 0.3s',
              }}
              onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-3px)'; e.currentTarget.style.boxShadow = '0 6px 20px rgba(245,158,11,0.15)' }}
              onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = 'none' }}
              >
                {/* Gold/violet accent bar */}
                <div style={{
                  height: 4,
                  background: 'linear-gradient(90deg, #f59e0b, #7c3aed)',
                }} />

                <div style={{ padding: '20px 22px' }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
                    <Avatar name={mentor.name} size={52} glowColor="#f59e0b" />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 700, fontSize: 16, color: 'var(--text-primary)', marginBottom: 2 }}>
                        {mentor.name}
                      </div>
                      <div style={{ fontSize: 13, color: '#f59e0b', fontWeight: 600, marginBottom: 6 }}>
                        {mentor.specialty}
                      </div>

                      {/* Star rating */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: 2, marginBottom: 8 }}>
                        {[1, 2, 3, 4, 5].map(s => (
                          <span key={s}>
                            {s <= Math.floor(mentor.rating)
                              ? <IconStarFilled size={14} />
                              : <IconStar size={14} />}
                          </span>
                        ))}
                        <span style={{ fontSize: 13, color: 'var(--text-muted)', marginLeft: 4, fontWeight: 600 }}>
                          {mentor.rating}
                        </span>
                      </div>

                      <p style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 14 }}>
                        {mentor.bio}
                      </p>

                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
                        {/* Mentee badge */}
                        <div style={{
                          display: 'inline-flex', alignItems: 'center', gap: 4,
                          padding: '4px 10px', borderRadius: 20,
                          background: '#f59e0b18', color: '#f59e0b',
                          fontSize: 12, fontWeight: 600,
                          animation: 'countUp 0.6s ease-out',
                        }}>
                          <IconUsers size={13} />
                          {mentor.mentees} mentorés
                        </div>

                        <button onClick={() => handleRequestMentor(mentor.id)} style={{
                          padding: '10px 20px', borderRadius: 10, border: 'none',
                          background: 'linear-gradient(135deg, #f59e0b, #fbbf24)',
                          color: '#1a0533', fontWeight: 700, fontSize: 13, cursor: 'pointer',
                          display: 'flex', alignItems: 'center', gap: 6,
                          transition: 'transform 0.2s, box-shadow 0.3s',
                          backgroundSize: '200% 100%',
                          position: 'relative', overflow: 'hidden',
                        }}
                        onMouseEnter={e => {
                          e.currentTarget.style.transform = 'scale(1.04)'
                          e.currentTarget.style.boxShadow = '0 4px 15px rgba(245,158,11,0.4)'
                        }}
                        onMouseLeave={e => {
                          e.currentTarget.style.transform = 'scale(1)'
                          e.currentTarget.style.boxShadow = 'none'
                        }}
                        >
                          <IconSend size={14} />
                          Demander un mentorat
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── DÉFIS ── */}
        {tab === 'challenges' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            {challenges.map((ch, idx) => {
              const grad = CHALLENGE_GRADIENTS[idx % CHALLENGE_GRADIENTS.length]
              const remaining = daysLeft(ch.end_date)
              const progressPct = Math.min(100, (ch.participants / ch.max_participants) * 100)
              const urgentColor = remaining <= 3 ? '#ef4444' : remaining <= 10 ? '#f59e0b' : '#3b82f6'

              return (
                <div key={ch.id} style={{
                  background: grad, borderRadius: 14,
                  border: '1px solid var(--border)', padding: '22px 22px 18px',
                  animation: `fadeInUp 0.5s ease-out ${idx * 0.12}s both`,
                  transition: 'transform 0.3s, box-shadow 0.3s',
                }}
                onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-3px)'; e.currentTarget.style.boxShadow = '0 6px 20px rgba(124,58,237,0.15)' }}
                onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = 'none' }}
                >
                  {/* Header row */}
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 10, gap: 12 }}>
                    <div style={{ flex: 1 }}>
                      <h3 style={{ fontWeight: 700, fontSize: 17, color: 'var(--text-primary)', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 8 }}>
                        <IconTarget size={18} />
                        {ch.title}
                      </h3>
                      <p style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                        {ch.description}
                      </p>
                    </div>

                    {/* Timer badge */}
                    <div style={{
                      padding: '6px 12px', borderRadius: 20,
                      background: `${urgentColor}18`, color: urgentColor,
                      fontSize: 12, fontWeight: 700, whiteSpace: 'nowrap',
                      display: 'flex', alignItems: 'center', gap: 4,
                      animation: remaining <= 3 ? 'pulse 2s ease-in-out infinite' : 'none',
                    }}>
                      <IconClock size={13} />
                      {remaining}j restants
                    </div>
                  </div>

                  {/* Progress bar */}
                  <div style={{ marginBottom: 14 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
                      <span>{ch.participants} / {ch.max_participants} participants</span>
                      <span style={{ fontWeight: 600 }}>{Math.round(progressPct)}%</span>
                    </div>
                    <div style={{
                      height: 8, borderRadius: 4, background: 'rgba(255,255,255,0.08)', overflow: 'hidden',
                    }}>
                      <div style={{
                        height: '100%', borderRadius: 4,
                        background: 'linear-gradient(90deg, #7c3aed, #6366f1, #3b82f6)',
                        backgroundSize: '200% 100%',
                        animation: `shimmer 2s linear infinite, progressFill 1.2s ease-out`,
                        width: `${progressPct}%`,
                        transition: 'width 0.8s ease-out',
                      }} />
                    </div>
                  </div>

                  {/* Participant avatars + buttons */}
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
                    {/* Stacked avatars */}
                    <div style={{ display: 'flex' }}>
                      {['A', 'B', 'C', 'D'].map((letter, i) => (
                        <div key={i} style={{
                          width: 30, height: 30, borderRadius: '50%',
                          background: `linear-gradient(135deg, ${POST_BORDER_COLORS[i]}, ${POST_BORDER_COLORS[i]}aa)`,
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          color: '#fff', fontSize: 11, fontWeight: 700,
                          border: '2px solid var(--bg-card)',
                          marginLeft: i > 0 ? -10 : 0,
                          position: 'relative', zIndex: 4 - i,
                        }}>
                          {letter}
                        </div>
                      ))}
                      {ch.participants > 4 && (
                        <div style={{
                          width: 30, height: 30, borderRadius: '50%',
                          background: 'var(--bg-surface)', display: 'flex',
                          alignItems: 'center', justifyContent: 'center',
                          color: 'var(--text-muted)', fontSize: 10, fontWeight: 700,
                          border: '2px solid var(--bg-card)', marginLeft: -10,
                        }}>
                          +{ch.participants - 4}
                        </div>
                      )}
                    </div>

                    <div style={{ display: 'flex', gap: 8 }}>
                      <button onClick={() => handleLeaderboard(ch.id)} style={{
                        padding: '9px 16px', borderRadius: 10,
                        border: '1px solid var(--border)', background: 'var(--bg-card)',
                        color: 'var(--text-primary)', fontWeight: 600, fontSize: 13,
                        cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5,
                        transition: 'all 0.2s',
                      }}
                      onMouseEnter={e => { e.currentTarget.style.borderColor = '#f59e0b'; e.currentTarget.style.color = '#f59e0b' }}
                      onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text-primary)' }}
                      >
                        <IconTrophy size={14} /> Classement
                      </button>

                      <button
                        onClick={() => !ch.joined && handleJoinChallenge(ch.id)}
                        disabled={ch.joined}
                        style={{
                          padding: '9px 18px', borderRadius: 10, border: 'none',
                          background: ch.joined
                            ? '#22c55e22'
                            : 'linear-gradient(135deg, #7c3aed, #6366f1)',
                          color: ch.joined ? '#22c55e' : '#fff',
                          fontWeight: 700, fontSize: 13,
                          cursor: ch.joined ? 'default' : 'pointer',
                          display: 'flex', alignItems: 'center', gap: 5,
                          transition: 'transform 0.2s, box-shadow 0.3s',
                        }}
                        onMouseEnter={e => { if (!ch.joined) { e.currentTarget.style.transform = 'scale(1.04)'; e.currentTarget.style.boxShadow = '0 4px 15px rgba(124,58,237,0.4)' } }}
                        onMouseLeave={e => { e.currentTarget.style.transform = 'scale(1)'; e.currentTarget.style.boxShadow = 'none' }}
                      >
                        {ch.joined
                          ? <><IconCheck size={14} /> Inscrit</>
                          : <><IconPlus size={14} /> Rejoindre</>}
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* ── ÉQUIPES (workspaces partagés) ── */}
        {tab === 'workspaces' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{
              background: 'linear-gradient(135deg, #06b6d411, #0891b211)',
              border: '1px solid var(--border)', borderRadius: 14,
              padding: '14px 18px', display: 'flex', alignItems: 'center', gap: 12,
            }}>
              <IconUsers size={22} />
              <div>
                <div style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 14 }}>
                  Équipes Syléa — collaboration partagée
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 2 }}>
                  Crée un espace pour ton équipe, partagez objectifs, mémoire et contexte commun.
                </div>
              </div>
            </div>
            <WorkspacesSection embedded />
          </div>
        )}

        {/* ═══ LEADERBOARD MODAL ═══ */}
        {leaderboardModal && (
          <div
            onClick={() => setLeaderboardModal(null)}
            style={{
              position: 'fixed', inset: 0, zIndex: 1000,
              background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              padding: 20,
              animation: 'fadeInUp 0.3s ease-out',
            }}
          >
            <div
              onClick={e => e.stopPropagation()}
              style={{
                background: 'var(--bg-card)', borderRadius: 18,
                border: '1px solid var(--border)',
                width: '100%', maxWidth: 440, padding: '28px 24px',
                animation: 'modalIn 0.4s ease-out',
                boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
              }}
            >
              {/* Modal header */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
                <h2 style={{
                  fontSize: 20, fontWeight: 800, color: 'var(--text-primary)',
                  display: 'flex', alignItems: 'center', gap: 8,
                }}>
                  <IconTrophy size={22} /> Classement
                </h2>
                <button onClick={() => setLeaderboardModal(null)} style={{
                  background: 'var(--bg-surface)', border: '1px solid var(--border)',
                  borderRadius: 8, padding: 6, cursor: 'pointer', color: 'var(--text-muted)',
                  transition: 'all 0.2s',
                }}
                onMouseEnter={e => { e.currentTarget.style.background = '#ef444422'; e.currentTarget.style.color = '#ef4444' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-surface)'; e.currentTarget.style.color = 'var(--text-muted)' }}
                >
                  <IconX size={16} />
                </button>
              </div>

              {/* Entries */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {leaderboardModal.entries.map((entry, idx) => {
                  const medalColors = ['#f59e0b', '#9ca3af', '#cd7f32']
                  const isMedal = idx < 3
                  return (
                    <div key={entry.rank} style={{
                      display: 'flex', alignItems: 'center', gap: 12,
                      padding: '12px 14px', borderRadius: 10,
                      background: isMedal ? `${medalColors[idx]}11` : 'var(--bg-surface)',
                      border: isMedal ? `1px solid ${medalColors[idx]}33` : '1px solid var(--border)',
                      animation: `slideIn 0.3s ease-out ${idx * 0.08}s both`,
                      transition: 'transform 0.2s',
                    }}
                    onMouseEnter={e => e.currentTarget.style.transform = 'scale(1.02)'}
                    onMouseLeave={e => e.currentTarget.style.transform = 'scale(1)'}
                    >
                      {/* Rank */}
                      {isMedal ? (
                        <IconMedal size={24} color={medalColors[idx]} />
                      ) : (
                        <div style={{
                          width: 24, height: 24, borderRadius: '50%',
                          background: 'var(--bg-card)', display: 'flex',
                          alignItems: 'center', justifyContent: 'center',
                          fontSize: 12, fontWeight: 700, color: 'var(--text-muted)',
                        }}>
                          {entry.rank}
                        </div>
                      )}

                      <Avatar name={entry.name} size={36} glowColor={isMedal ? medalColors[idx] : '#7c3aed'} />

                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{
                          fontWeight: isMedal ? 700 : 600, fontSize: 14,
                          color: isMedal ? medalColors[idx] : 'var(--text-primary)',
                        }}>
                          {entry.name}
                        </div>
                      </div>

                      <div style={{
                        fontWeight: 800, fontSize: 15,
                        color: isMedal ? medalColors[idx] : 'var(--text-muted)',
                        fontVariantNumeric: 'tabular-nums',
                      }}>
                        {entry.score} pts
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}
