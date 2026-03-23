import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useT, useLocale } from '../i18n/LanguageContext'
import { LANGUAGES } from '../i18n/languages'
import { api } from '../api/client'
import { useStore } from '../store/useStore'
import { useAuthStore } from '../auth/authStore'
import SecurityGauge from '../security/SecurityGauge'
import PatternGrid from '../security/PatternGrid'
import {
  hashString, hashPattern, passwordStrength, computeSecurityLevel,
} from '../security/hashUtils'
import type { Decision } from '../types'

// ─── Chevron icon ─────────────────────────────────────────────────────────────
function ChevronDown({ open }: { open: boolean }) {
  return (
    <svg width={18} height={18} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
      style={{ transition: 'transform 0.25s', transform: open ? 'rotate(180deg)' : 'rotate(0deg)' }}>
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

// ─── Settings card (accordion item) ───────────────────────────────────────────
function SettingsCard({
  title, description, icon, open, onClick, children,
}: {
  title: string; description: string; icon: React.ReactNode
  open: boolean; onClick: () => void; children: React.ReactNode
}) {
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border)',
      borderRadius: '1rem', overflow: 'hidden', transition: 'all 0.2s',
      marginBottom: '0.75rem',
    }}>
      <button onClick={onClick} style={{
        width: '100%', display: 'flex', alignItems: 'center', gap: '0.85rem',
        padding: '1.1rem 1.25rem', background: 'transparent', border: 'none',
        cursor: 'pointer', color: 'var(--text-primary)', textAlign: 'left',
      }}>
        <div style={{
          width: 40, height: 40, borderRadius: '0.75rem',
          background: open ? 'rgba(59,130,246,0.15)' : 'rgba(255,255,255,0.04)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: open ? '#3b82f6' : 'var(--text-muted)', transition: 'all 0.2s',
          flexShrink: 0,
        }}>
          {icon}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>{title}</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 2 }}>{description}</div>
        </div>
        <ChevronDown open={open} />
      </button>
      <div style={{
        maxHeight: open ? '2000px' : '0',
        opacity: open ? 1 : 0,
        overflow: 'hidden',
        transition: 'max-height 0.35s ease, opacity 0.25s ease',
      }}>
        <div style={{ padding: '0 1.25rem 1.25rem', borderTop: '1px solid var(--border)' }}>
          {children}
        </div>
      </div>
    </div>
  )
}

// ─── Section icons ────────────────────────────────────────────────────────────
const IconUser = (
  <svg width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx={12} cy={7} r={4}/></svg>
)
const IconGlobe = (
  <svg width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"><circle cx={12} cy={12} r={10}/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
)
const IconShield = (
  <svg width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
)
const IconArchive = (
  <svg width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"><polyline points="21 8 21 21 3 21 3 8"/><rect x={1} y={3} width={22} height={5}/><line x1={10} y1={12} x2={14} y2={12}/></svg>
)

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════════════════════════════════════════
export default function ParametresPage() {
  const t = useT()
  const { locale, setLocale } = useLocale()
  const profil = useStore(s => s.profil)
  const authUser = useAuthStore(s => s.user)
  const authToken = useAuthStore(s => s.token)
  const [openSection, setOpenSection] = useState<string | null>(null)

  const toggle = (key: string) => setOpenSection(prev => prev === key ? null : key)

  return (
    <div className="page animate-fade-in">
      <div className="container page-content" style={{ maxWidth: 680, margin: '0 auto', padding: '2rem 1rem' }}>
        <h2 style={{
          fontSize: '1.5rem', fontWeight: 800, marginBottom: '0.25rem',
          background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
          WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
        }}>
          {t('settings.title')}
        </h2>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginBottom: '1.5rem' }}>
          {t('settings.subtitle')}
        </p>

        {/* 1. Mon profil */}
        <SettingsCard
          title={t('settings.profil')} description={t('settings.profil_desc')}
          icon={IconUser} open={openSection === 'profil'} onClick={() => toggle('profil')}
        >
          <ProfilSection profil={profil} t={t} authUser={authUser} authToken={authToken} />
        </SettingsCard>

        {/* 2. Langue */}
        <SettingsCard
          title={t('settings.langue')} description={t('settings.langue_desc')}
          icon={IconGlobe} open={openSection === 'langue'} onClick={() => toggle('langue')}
        >
          <LangueSection locale={locale} setLocale={setLocale} t={t} />
        </SettingsCard>

        {/* 3. Securite */}
        <SettingsCard
          title={t('settings.securite')} description={t('settings.securite_desc')}
          icon={IconShield} open={openSection === 'securite'} onClick={() => toggle('securite')}
        >
          <SecuriteSection t={t} authUser={authUser} />
        </SettingsCard>

        {/* 4. Archives */}
        <SettingsCard
          title={t('settings.archives')} description={t('settings.archives_desc')}
          icon={IconArchive} open={openSection === 'archives'} onClick={() => toggle('archives')}
        >
          <ArchivesSection t={t} />
        </SettingsCard>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1 : Mon profil
// ═══════════════════════════════════════════════════════════════════════════════
function ProfilSection({ profil, t, authUser, authToken }: { profil: ReturnType<typeof useStore>['profil']; t: (k: string) => string; authUser: { id: string; email: string; provider: string } | null; authToken: string | null }) {
  const navigate = useNavigate()
  const logout = useAuthStore(s => s.logout)

  const Field = ({ label, value }: { label: string; value: string | number | null | undefined }) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0.45rem 0', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
      <span style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>{label}</span>
      <span style={{ color: 'var(--text-primary)', fontSize: '0.82rem', fontWeight: 500 }}>{value ?? t('settings.non_renseigne')}</span>
    </div>
  )

  const Tags = ({ items }: { items: string[] }) => (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem', marginTop: '0.3rem' }}>
      {items.length > 0 ? items.map((s, i) => (
        <span key={i} style={{
          padding: '0.2rem 0.6rem', borderRadius: '999px', fontSize: '0.72rem', fontWeight: 500,
          background: 'rgba(59,130,246,0.12)', color: '#93c5fd', border: '1px solid rgba(59,130,246,0.2)',
        }}>{s}</span>
      )) : <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>{t('settings.non_renseigne')}</span>}
    </div>
  )

  const ScoreBar = ({ label, value }: { label: string; value: number }) => (
    <div style={{ marginBottom: '0.5rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', marginBottom: 3 }}>
        <span style={{ color: 'var(--text-muted)' }}>{label}</span>
        <span style={{ color: '#93c5fd', fontWeight: 600 }}>{value}/10</span>
      </div>
      <div style={{ height: 6, borderRadius: 3, background: 'rgba(255,255,255,0.06)' }}>
        <div style={{
          height: '100%', borderRadius: 3, width: `${value * 10}%`,
          background: 'linear-gradient(90deg, #3b82f6, #8b5cf6)',
          transition: 'width 0.3s',
        }} />
      </div>
    </div>
  )

  return (
    <div style={{ paddingTop: '0.75rem' }}>
      {/* Compte */}
      {authUser && (
        <>
          <h4 style={sectionTitle}>COMPTE</h4>
          <Field label="E-mail" value={authUser.email} />
          <Field label="Connexion via" value={authUser.provider === 'google' ? 'Google' : authUser.provider === 'github' ? 'GitHub' : 'E-mail / Mot de passe'} />
          <Field label="Statut" value={authToken ? 'Connecté' : 'Déconnecté'} />
          <button
            onClick={() => { logout(); navigate('/login', { replace: true }) }}
            style={{
              marginTop: '0.75rem', width: '100%', padding: '0.65rem',
              background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
              borderRadius: '0.6rem', color: '#ef4444', fontSize: '0.85rem',
              fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.2)' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.1)' }}
          >
            Se déconnecter
          </button>
          <div style={{ height: 1, background: 'rgba(255,255,255,0.06)', margin: '0.75rem 0' }} />
        </>
      )}

      {/* Si pas de profil Syléa */}
      {!profil && (
        <p style={{ color: 'var(--text-muted)', padding: '0.5rem 0', fontSize: '0.85rem', fontStyle: 'italic' }}>
          Profil Syléa non créé. Rendez-vous sur le tableau de bord pour créer votre profil.
        </p>
      )}

      {/* Identite + tout le profil Syléa */}
      {profil && (
        <>
          <h4 style={sectionTitle}>{t('settings.identite')}</h4>
          <Field label={t('settings.genre')} value={profil.genre || t('settings.non_renseigne')} />
          <Field label={t('settings.nom')} value={profil.nom} />
          <Field label={t('settings.age')} value={`${profil.age} ${t('settings.ans')}`} />
          <Field label={t('settings.profession')} value={profil.profession} />
          <Field label={t('settings.ville')} value={profil.ville} />
          <Field label={t('settings.situation')} value={profil.situation_familiale} />

          {/* Objectif */}
          {profil.objectif && (
            <>
              <h4 style={{ ...sectionTitle, marginTop: '1rem' }}>{t('settings.objectif')}</h4>
              <Field label={t('settings.categorie')} value={profil.objectif.categorie} />
              <Field label={t('settings.deadline')} value={profil.objectif.deadline || t('settings.non_renseigne')} />
              <Field label={t('settings.probabilite')} value={`${profil.probabilite_actuelle?.toFixed(1) ?? 0}%`} />
              <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '0.4rem', lineHeight: 1.5 }}>
                {profil.objectif.description?.slice(0, 200)}{(profil.objectif.description?.length ?? 0) > 200 ? '...' : ''}
              </div>
            </>
          )}

          {/* Competences, diplomes, langues */}
          <h4 style={{ ...sectionTitle, marginTop: '1rem' }}>{t('settings.competences')}</h4>
          <Tags items={profil.competences || []} />
          <h4 style={{ ...sectionTitle, marginTop: '0.75rem' }}>{t('settings.diplomes')}</h4>
          <Tags items={profil.diplomes || []} />
          <h4 style={{ ...sectionTitle, marginTop: '0.75rem' }}>{t('settings.langues')}</h4>
          <Tags items={profil.langues || []} />

          {/* Bien-etre */}
          <h4 style={{ ...sectionTitle, marginTop: '1rem' }}>{t('settings.bien_etre')}</h4>
      <ScoreBar label={t('settings.sante')} value={profil.niveau_sante} />
      <ScoreBar label={t('settings.stress')} value={profil.niveau_stress} />
      <ScoreBar label={t('settings.energie')} value={profil.niveau_energie} />
      <ScoreBar label={t('settings.bonheur')} value={profil.niveau_bonheur} />

      {/* Temps */}
      <h4 style={{ ...sectionTitle, marginTop: '1rem' }}>{t('settings.repartition_temps')}</h4>
      <Field label={t('settings.travail')} value={`${profil.heures_travail} ${t('settings.h_jour')}`} />
      <Field label={t('settings.sommeil')} value={`${profil.heures_sommeil} ${t('settings.h_jour')}`} />
      <Field label={t('settings.loisirs')} value={`${profil.heures_loisirs} ${t('settings.h_jour')}`} />
      <Field label={t('settings.transport')} value={`${profil.heures_transport} ${t('settings.h_jour')}`} />
      <Field label={t('settings.objectif_h')} value={`${profil.heures_objectif} ${t('settings.h_jour')}`} />
        </>
      )}
    </div>
  )
}

const sectionTitle: React.CSSProperties = {
  fontSize: '0.72rem', fontWeight: 700, letterSpacing: '0.1em',
  color: '#3b82f6', textTransform: 'uppercase', marginBottom: '0.4rem',
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 2 : Langue
// ═══════════════════════════════════════════════════════════════════════════════
function LangueSection({ locale, setLocale, t }: { locale: string; setLocale: (c: string) => void; t: (k: string) => string }) {
  const [filter, setFilter] = useState('')
  const filtered = LANGUAGES.filter(l =>
    l.label.toLowerCase().includes(filter.toLowerCase()) ||
    l.labelEn.toLowerCase().includes(filter.toLowerCase()) ||
    l.code.toLowerCase().includes(filter.toLowerCase())
  )

  return (
    <div style={{ paddingTop: '0.75rem' }}>
      <input
        type="text" value={filter}
        onChange={e => setFilter(e.target.value)}
        placeholder={t('settings.rechercher_langue')}
        style={{
          width: '100%', padding: '0.6rem 0.85rem', marginBottom: '0.75rem',
          background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)',
          borderRadius: '0.6rem', color: 'var(--text-primary)', fontSize: '0.85rem',
          outline: 'none',
        }}
      />
      <div style={{ maxHeight: 320, overflowY: 'auto', borderRadius: '0.5rem' }}>
        {filtered.map(lang => (
          <button key={lang.code} onClick={() => setLocale(lang.code)} style={{
            width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '0.6rem 0.85rem', background: locale === lang.code ? 'rgba(59,130,246,0.1)' : 'transparent',
            border: 'none', borderBottom: '1px solid rgba(255,255,255,0.03)',
            cursor: 'pointer', color: 'var(--text-primary)', fontSize: '0.85rem',
            transition: 'background 0.15s',
          }}>
            <div>
              <span style={{ fontWeight: locale === lang.code ? 600 : 400 }}>{lang.label}</span>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginLeft: '0.5rem' }}>
                {lang.labelEn}
              </span>
            </div>
            {locale === lang.code && (
              <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="#3b82f6" strokeWidth={3} strokeLinecap="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3 : Securite
// ═══════════════════════════════════════════════════════════════════════════════
function SecuriteSection({ t, authUser }: { t: (k: string) => string; authUser: { id: string; email: string; provider: string } | null }) {
  const [secLevel, setSecLevel] = useState(computeSecurityLevel)
  const [lockType, setLockType] = useState<string | null>(localStorage.getItem('sylea-lock-type'))
  const [mode, setMode] = useState<'idle' | 'password' | 'pattern'>('idle')
  const [pwd, setPwd] = useState('')
  const [pwdConfirm, setPwdConfirm] = useState('')
  const [pwdError, setPwdError] = useState('')
  const [patternStep, setPatternStep] = useState<'draw' | 'confirm'>('draw')
  const [firstPattern, setFirstPattern] = useState<number[]>([])
  const [patternError, setPatternError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')

  const refresh = () => {
    setSecLevel(computeSecurityLevel())
    setLockType(localStorage.getItem('sylea-lock-type'))
  }

  const handleSetPassword = async () => {
    setPwdError('')
    if (pwd.length < 4) { setPwdError(t('settings.mdp_trop_court')); return }
    if (pwd !== pwdConfirm) { setPwdError(t('settings.mdp_mismatch')); return }
    const hash = await hashString(pwd)
    const strength = passwordStrength(pwd)
    localStorage.setItem('sylea-lock-type', 'password')
    localStorage.setItem('sylea-lock-hash', hash)
    localStorage.setItem('sylea-pwd-strength', String(strength))
    setMode('idle'); setPwd(''); setPwdConfirm('')
    setSuccessMsg(t('settings.verrou_cree'))
    refresh()
    setTimeout(() => setSuccessMsg(''), 3000)
  }

  const handlePatternComplete = async (pattern: number[]) => {
    setPatternError('')
    if (pattern.length < 4) { setPatternError(t('settings.schema_trop_court')); return }
    if (patternStep === 'draw') {
      setFirstPattern(pattern)
      setPatternStep('confirm')
    } else {
      // confirm
      if (pattern.join('-') !== firstPattern.join('-')) {
        setPatternError(t('settings.mdp_mismatch'))
        setPatternStep('draw')
        setFirstPattern([])
        return
      }
      const hash = await hashPattern(pattern)
      localStorage.setItem('sylea-lock-type', 'pattern')
      localStorage.setItem('sylea-lock-hash', hash)
      localStorage.removeItem('sylea-pwd-strength')
      setMode('idle'); setPatternStep('draw'); setFirstPattern([])
      setSuccessMsg(t('settings.verrou_cree'))
      refresh()
      setTimeout(() => setSuccessMsg(''), 3000)
    }
  }

  const removeLock = () => {
    localStorage.removeItem('sylea-lock-type')
    localStorage.removeItem('sylea-lock-hash')
    localStorage.removeItem('sylea-pwd-strength')
    sessionStorage.removeItem('sylea-unlocked')
    setMode('idle')
    setSuccessMsg(t('settings.verrou_supprime'))
    refresh()
    setTimeout(() => setSuccessMsg(''), 3000)
  }

  return (
    <div style={{ paddingTop: '0.75rem', textAlign: 'center' }}>
      <SecurityGauge level={secLevel} />

      {/* Info compte connecté */}
      {authUser && (
        <div style={{
          marginTop: '0.75rem', padding: '0.75rem 1rem', borderRadius: '0.75rem',
          background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.2)',
          textAlign: 'left',
        }}>
          <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#3b82f6', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: '0.4rem' }}>
            Authentification
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', marginBottom: '0.2rem' }}>
            <span style={{ color: 'var(--text-muted)' }}>E-mail</span>
            <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{authUser.email}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', marginBottom: '0.2rem' }}>
            <span style={{ color: 'var(--text-muted)' }}>Methode</span>
            <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
              {authUser.provider === 'google' ? 'Google OAuth' : authUser.provider === 'github' ? 'GitHub OAuth' : 'E-mail / Mot de passe'}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem' }}>
            <span style={{ color: 'var(--text-muted)' }}>Statut</span>
            <span style={{ color: '#4ade80', fontWeight: 500, display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#4ade80' }} />
              Connecte
            </span>
          </div>
        </div>
      )}

      {lockType && (
        <div style={{
          marginTop: '0.5rem', display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
          padding: '0.3rem 0.8rem', borderRadius: '999px', fontSize: '0.72rem', fontWeight: 600,
          background: 'rgba(34,197,94,0.12)', color: '#4ade80', border: '1px solid rgba(34,197,94,0.25)',
        }}>
          <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}><polyline points="20 6 9 17 4 12"/></svg>
          {t('settings.verrou_actif')} ({lockType === 'password' ? t('settings.mot_de_passe') : t('settings.schema')})
        </div>
      )}

      {successMsg && (
        <div style={{ marginTop: '0.75rem', color: '#4ade80', fontSize: '0.8rem', fontWeight: 500 }}>
          {successMsg}
        </div>
      )}

      {mode === 'idle' && (
        <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', marginTop: '1.25rem', flexWrap: 'wrap' }}>
          <button onClick={() => setMode('password')} style={actionBtn}>
            <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><rect x={3} y={11} width={18} height={11} rx={2}/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            {lockType === 'password' ? t('settings.mot_de_passe') : t('settings.creer_mdp')}
          </button>
          <button onClick={() => { setMode('pattern'); setPatternStep('draw'); setFirstPattern([]) }} style={actionBtn}>
            <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><circle cx={5} cy={5} r={2}/><circle cx={12} cy={5} r={2}/><circle cx={19} cy={5} r={2}/><circle cx={5} cy={12} r={2}/><circle cx={12} cy={12} r={2}/><circle cx={19} cy={12} r={2}/><circle cx={5} cy={19} r={2}/><circle cx={12} cy={19} r={2}/><circle cx={19} cy={19} r={2}/></svg>
            {lockType === 'pattern' ? t('settings.schema') : t('settings.creer_schema')}
          </button>
        </div>
      )}

      {mode === 'password' && (
        <div style={{ marginTop: '1rem', maxWidth: 300, margin: '1rem auto' }}>
          <input type="password" value={pwd} onChange={e => setPwd(e.target.value)}
            placeholder={t('settings.mdp_placeholder')} autoFocus
            style={inputStyle} />
          <input type="password" value={pwdConfirm} onChange={e => setPwdConfirm(e.target.value)}
            placeholder={t('settings.mdp_confirmer_placeholder')}
            style={{ ...inputStyle, marginTop: '0.5rem' }} />
          {pwdError && <div style={{ color: '#ef4444', fontSize: '0.78rem', marginTop: '0.4rem' }}>{pwdError}</div>}
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem', justifyContent: 'center' }}>
            <button onClick={() => setMode('idle')} style={{ ...actionBtn, background: 'rgba(255,255,255,0.04)' }}>Annuler</button>
            <button onClick={handleSetPassword} style={{ ...actionBtn, background: 'rgba(59,130,246,0.15)', color: '#60a5fa' }}>Valider</button>
          </div>
        </div>
      )}

      {mode === 'pattern' && (
        <div style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>
            {patternStep === 'draw' ? t('settings.creer_schema') : t('settings.confirmer_schema')}
          </div>
          <PatternGrid onComplete={handlePatternComplete} size={200} />
          {patternError && <div style={{ color: '#ef4444', fontSize: '0.78rem', marginTop: '0.5rem' }}>{patternError}</div>}
          <button onClick={() => setMode('idle')} style={{ ...actionBtn, marginTop: '0.75rem', background: 'rgba(255,255,255,0.04)' }}>Annuler</button>
        </div>
      )}

      {lockType && mode === 'idle' && (
        <button onClick={removeLock} style={{
          ...actionBtn, marginTop: '1rem', color: '#ef4444', border: '1px solid rgba(239,68,68,0.25)',
        }}>
          {t('settings.supprimer_verrou')}
        </button>
      )}
    </div>
  )
}

const actionBtn: React.CSSProperties = {
  padding: '0.55rem 1.1rem', borderRadius: '0.75rem', fontSize: '0.8rem', fontWeight: 600,
  background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)',
  color: 'var(--text-primary)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem',
  transition: 'all 0.15s',
}

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '0.65rem 0.85rem',
  background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)',
  borderRadius: '0.6rem', color: 'var(--text-primary)', fontSize: '0.85rem', outline: 'none',
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 4 : Archives des decisions
// ═══════════════════════════════════════════════════════════════════════════════
function ArchivesSection({ t }: { t: (k: string) => string }) {
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pagesTotal, setPagesTotal] = useState(1)
  const [tri, setTri] = useState('recent')
  const [recherche, setRecherche] = useState('')
  const [loading, setLoading] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()

  const fetchPage = useCallback(async (p: number, t: string, r: string) => {
    setLoading(true)
    try {
      const res = await api.getHistoriquePagine({ page: p, par_page: 10, tri: t, recherche: r })
      setDecisions(res.decisions)
      setTotal(res.total)
      setPagesTotal(res.pages_total)
      setPage(res.page)
    } catch { /* ignore */ }
    setLoading(false)
  }, [])

  // Initial load
  useEffect(() => { fetchPage(1, tri, recherche) }, [])  // eslint-disable-line

  // Debounced search
  const handleSearch = (val: string) => {
    setRecherche(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => fetchPage(1, tri, val), 300)
  }

  const handleTri = (newTri: string) => {
    setTri(newTri)
    fetchPage(1, newTri, recherche)
  }

  // Pagination numbers
  const pageNumbers = buildPageNumbers(page, pagesTotal)

  return (
    <div style={{ paddingTop: '0.75rem' }}>
      {/* Search + Sort */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
        <input
          type="text" value={recherche} onChange={e => handleSearch(e.target.value)}
          placeholder={t('settings.rechercher')}
          style={{ ...inputStyle, flex: 1, minWidth: 180 }}
        />
        <div style={{ display: 'flex', gap: '0.25rem' }}>
          {(['recent', 'ancien', 'impact'] as const).map(key => (
            <button key={key} onClick={() => handleTri(key)} style={{
              padding: '0.4rem 0.65rem', borderRadius: '999px', fontSize: '0.68rem', fontWeight: 600,
              letterSpacing: '0.04em',
              border: tri === key ? '1px solid #3b82f6' : '1px solid var(--border)',
              background: tri === key ? 'rgba(59,130,246,0.12)' : 'transparent',
              color: tri === key ? '#60a5fa' : 'var(--text-muted)',
              cursor: 'pointer', transition: 'all 0.15s', whiteSpace: 'nowrap',
            }}>
              {t(`settings.tri_${key}`)}
            </button>
          ))}
        </div>
      </div>

      {/* Decisions list */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: '2rem 0', color: 'var(--text-muted)' }}>...</div>
      ) : decisions.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '2rem 0', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
          {t('settings.aucune_decision')}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {decisions.map(d => (
            <DecisionCard key={d.id} decision={d} t={t} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {pagesTotal > 1 && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: '0.25rem', marginTop: '1rem',
        }}>
          <PagBtn onClick={() => fetchPage(page - 1, tri, recherche)} disabled={page <= 1}>&lt;</PagBtn>
          {pageNumbers.map((n, i) =>
            n === '...' ? (
              <span key={`e${i}`} style={{ color: 'var(--text-muted)', fontSize: '0.8rem', padding: '0 0.25rem' }}>...</span>
            ) : (
              <PagBtn key={n} active={n === page} onClick={() => fetchPage(n as number, tri, recherche)}>{n}</PagBtn>
            )
          )}
          <PagBtn onClick={() => fetchPage(page + 1, tri, recherche)} disabled={page >= pagesTotal}>&gt;</PagBtn>
        </div>
      )}

      {total > 0 && (
        <div style={{ textAlign: 'center', marginTop: '0.5rem', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
          {total} {t('settings.archives_desc').toLowerCase().includes('decision') ? 'decisions' : 'decisions'}
        </div>
      )}
    </div>
  )
}

// ─── Decision card ────────────────────────────────────────────────────────────
function DecisionCard({ decision: d, t }: { decision: Decision; t: (k: string) => string }) {
  const impact = d.impact_net ?? 0
  const isPositive = impact >= 0
  const dateStr = new Date(d.cree_le).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' })

  return (
    <div style={{
      background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)',
      borderRadius: '0.75rem', padding: '0.85rem 1rem',
    }}>
      <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.35rem', lineHeight: 1.4 }}>
        {d.question}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        {d.option_choisie_description && (
          <span style={{
            fontSize: '0.72rem', padding: '0.15rem 0.5rem', borderRadius: '999px',
            background: 'rgba(139,92,246,0.1)', color: '#c4b5fd', border: '1px solid rgba(139,92,246,0.2)',
          }}>
            {d.option_choisie_description.slice(0, 50)}{d.option_choisie_description.length > 50 ? '...' : ''}
          </span>
        )}
        <span style={{
          fontSize: '0.72rem', fontWeight: 700,
          color: isPositive ? '#4ade80' : '#f87171',
        }}>
          {isPositive ? '+' : ''}{impact.toFixed(2)}%
        </span>
        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginLeft: 'auto' }}>
          {dateStr}
        </span>
      </div>
    </div>
  )
}

// ─── Pagination button ────────────────────────────────────────────────────────
function PagBtn({
  children, active, disabled, onClick,
}: {
  children: React.ReactNode; active?: boolean; disabled?: boolean; onClick?: () => void
}) {
  return (
    <button onClick={onClick} disabled={disabled} style={{
      width: 32, height: 32, borderRadius: '0.5rem',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: '0.78rem', fontWeight: active ? 700 : 500,
      background: active ? '#3b82f6' : 'transparent',
      color: active ? 'white' : disabled ? 'rgba(255,255,255,0.15)' : 'var(--text-muted)',
      border: active ? 'none' : '1px solid rgba(255,255,255,0.06)',
      cursor: disabled ? 'default' : 'pointer',
      transition: 'all 0.15s',
    }}>
      {children}
    </button>
  )
}

// ─── Build page numbers with ellipsis ─────────────────────────────────────────
function buildPageNumbers(current: number, total: number): (number | '...')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const pages: (number | '...')[] = []
  const near = [current - 1, current, current + 1].filter(n => n >= 1 && n <= total)

  // Always show page 1
  pages.push(1)

  // Ellipsis before current range
  if (near[0] > 2) pages.push('...')
  else if (near[0] === 2) pages.push(2) // no ellipsis for gap of 1

  // Current range (excluding 1 and total if already added)
  for (const n of near) {
    if (n !== 1 && n !== total && !pages.includes(n)) pages.push(n)
  }

  // Ellipsis after current range
  const lastNear = near[near.length - 1]
  if (lastNear < total - 1) pages.push('...')
  else if (lastNear === total - 1) pages.push(total - 1)

  // Always show last page
  if (!pages.includes(total)) pages.push(total)

  return pages
}
