// Animation d'intro Syléa — 8 secondes
// Logo fidèle : double-S tube creux, gradient violet→cyan, fond noir pur
import { useEffect } from 'react'

const SPLASH_DURATION = 8000

// Particules de fond minimalistes (très subtiles)
const PARTICLES = Array.from({ length: 24 }, (_, i) => ({
  cx:     (i * 137.5 + 30) % 380,
  cy:     (i * 211.3 + 25) % 380,
  r:       i % 5 === 0 ? 1.3 : 0.65,
  opacity: 0.05 + (i % 5) * 0.03,
  dur:     2.0 + (i % 4) * 0.7,
  delay:  (i * 0.23) % 5.5,
}))

// ─────────────────────────────────────────────────────────────────────────────
// Chemin S central — double-S symétrique, hauteur 210px, bulges ±90px
// Centre à (190, 170) dans un viewBox 380×380
// ─────────────────────────────────────────────────────────────────────────────
const CX = 190, CY = 170
const S  = `M ${CX} ${CY-105} C ${CX+90} ${CY-105}, ${CX+90} ${CY-28}, ${CX} ${CY} C ${CX-90} ${CY+28}, ${CX-90} ${CY+105}, ${CX} ${CY+105}`
// → M 190 65  C 280 65,  280 142, 190 170  C 100 198, 100 275, 190 275

export function SyleaSplash({ onDone }: { onDone: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDone, SPLASH_DURATION)
    return () => clearTimeout(t)
  }, [onDone])

  return (
    <>
      <style>{`
        /* ── Cycle de vie complet 8s ── */
        @keyframes sp-life {
          0%   { opacity: 0 }
          5%   { opacity: 1 }
          87%  { opacity: 1 }
          100% { opacity: 0 }
        }
        /* ── Logo : scale-in depuis le centre ── */
        @keyframes sp-logo-in {
          0%   { opacity: 0; transform: scale(0.78) }
          100% { opacity: 1; transform: scale(1) }
        }
        /* ── Halo pulsant ── */
        @keyframes sp-halo-pulse {
          0%,100% { opacity: 0.16 }
          50%     { opacity: 0.28 }
        }
        /* ── Brillance du S ── */
        @keyframes sp-glow {
          0%,100% { filter: drop-shadow(0 0 10px rgba(0,170,255,0.5)) }
          50%     { filter: drop-shadow(0 0 28px rgba(0,200,255,0.85)) }
        }
        /* ── Texte slide-up ── */
        @keyframes sp-text {
          from { opacity: 0; transform: translateY(20px) }
          to   { opacity: 1; transform: translateY(0) }
        }
        /* ── Sous-titre fondu ── */
        @keyframes sp-sub {
          from { opacity: 0 }
          to   { opacity: 1 }
        }
        /* ── Particules scintillantes ── */
        @keyframes sp-dot {
          0%,100% { opacity: 0.03 }
          50%     { opacity: 0.28 }
        }
      `}</style>

      {/* ── Overlay plein écran ── */}
      <div
        style={{
          position: 'fixed', inset: 0, zIndex: 9999,
          background: '#050810',
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          animation: 'sp-life 8s ease forwards',
        }}
      >
        <svg
          width="380" height="380"
          viewBox="0 0 380 380"
          style={{ overflow: 'visible' }}
        >
          <defs>
            {/* ── Gradient violet → cyan (bas → haut) ── */}
            <linearGradient id="sp-g" x1="50%" y1="100%" x2="50%" y2="0%">
              <stop offset="0%"   stopColor="#5520b8"/>
              <stop offset="30%"  stopColor="#1848d8"/>
              <stop offset="65%"  stopColor="#0090e0"/>
              <stop offset="100%" stopColor="#00c8ff"/>
            </linearGradient>

            {/* ── Filtre halo flou ── */}
            <filter id="sp-blur-halo" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="24"/>
            </filter>
          </defs>

          {/* Particules de fond */}
          {PARTICLES.map((p, i) => (
            <circle
              key={i} cx={p.cx} cy={p.cy} r={p.r}
              fill="white" opacity={p.opacity}
              style={{ animation: `sp-dot ${p.dur}s ease-in-out ${p.delay}s infinite` }}
            />
          ))}

          {/* Halo atmosphérique derrière le S */}
          <path
            d={S}
            stroke="url(#sp-g)" strokeWidth="100"
            fill="none" strokeLinecap="round"
            style={{
              filter: 'url(#sp-blur-halo)',
              opacity: 0.20,
              animation: 'sp-halo-pulse 3.5s ease-in-out 3s infinite',
            }}
          />

          {/* ──────────────────────────────────────────────────────────────
              LOGO S — apparaît à 1.2s (scale-in)
              Technique : multi-couches pour créer le tube creux double-rail
          ────────────────────────────────────────────────────────────── */}
          <g
            style={{
              transformOrigin: `${CX}px ${CY}px`,
              animation: 'sp-logo-in 1.4s cubic-bezier(0.16,1,0.3,1) 1.2s both, sp-glow 3s ease-in-out 4s infinite',
            }}
          >
            {/*
              Couche 1 — Bordure extérieure noire (contour sombre du tube)
              strokeWidth 58 : donne ~6px de bordure sombre de chaque côté
            */}
            <path d={S}
              stroke="rgba(2,4,16,0.98)" strokeWidth="58"
              fill="none" strokeLinecap="round"
            />

            {/*
              Couche 2 — Corps gradient (remplit les deux rails + espace entre)
              strokeWidth 46 : tous les pixels visibles de gradient
            */}
            <path d={S}
              stroke="url(#sp-g)" strokeWidth="46"
              fill="none" strokeLinecap="round"
            />

            {/*
              Couche 3 — Creusement central (crée le canal vide entre les deux rails)
              strokeLinecap="butt" : ne s'étend pas aux extrémités →
              les caps (haut/bas du S) restent solides en gradient ✓
              strokeWidth 18 → chaque rail visible = (46-18)/2 = 14px
            */}
            <path d={S}
              stroke="#050810" strokeWidth="18"
              fill="none" strokeLinecap="butt"
            />

            {/*
              Couche 4 — Reflet spéculaire sur le bord intérieur des rails
              Donne l'impression de brillance sur le dessus du tube
            */}
            <path d={S}
              stroke="rgba(160,225,255,0.55)" strokeWidth="2.5"
              fill="none" strokeLinecap="round"
            />
          </g>
        </svg>

        {/* ── Texte "Syléa" avec le même gradient ── */}
        <div
          style={{
            marginTop: '-1.3rem',
            animation: 'sp-text 1s cubic-bezier(0.16,1,0.3,1) 4.2s both',
          }}
        >
          <span
            style={{
              fontFamily: '"Inter", system-ui, sans-serif',
              fontWeight: 600,
              fontSize: '3.1rem',
              letterSpacing: '0.04em',
              background: 'linear-gradient(180deg, #00c8ff 0%, #0090e0 45%, #5520b8 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
              filter: 'drop-shadow(0 0 22px rgba(0,160,240,0.55))',
            }}
          >
            Syléa
          </span>
        </div>

        {/* ── Sous-titre ── */}
        <p
          style={{
            marginTop: '0.55rem',
            fontFamily: '"Inter", system-ui, sans-serif',
            fontSize: '0.7rem',
            letterSpacing: '0.30em',
            color: 'rgba(80,155,230,0.45)',
            textTransform: 'uppercase',
            animation: 'sp-sub 1s ease 5.3s both',
          }}
        >
          Votre coach de vie IA
        </p>

        {/* ── Bouton passer ── */}
        <button
          onClick={onDone}
          style={{
            position: 'absolute', bottom: '2.5rem', right: '2.5rem',
            background: 'none',
            border: '1px solid rgba(0,150,240,0.20)',
            color: 'rgba(0,200,255,0.35)',
            padding: '0.45rem 1.25rem', borderRadius: '20px',
            cursor: 'pointer', fontSize: '0.72rem',
            letterSpacing: '0.12em',
            fontFamily: '"Inter", system-ui, sans-serif',
            transition: 'all 0.25s',
          }}
          onMouseEnter={e => {
            e.currentTarget.style.borderColor = 'rgba(0,150,240,0.55)'
            e.currentTarget.style.color       = 'rgba(0,200,255,0.75)'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.borderColor = 'rgba(0,150,240,0.20)'
            e.currentTarget.style.color       = 'rgba(0,200,255,0.35)'
          }}
        >
          PASSER ›
        </button>
      </div>
    </>
  )
}
