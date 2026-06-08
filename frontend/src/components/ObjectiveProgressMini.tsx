// Mini-graphique de progression de l'objectif final, affiché dans le hero
// du Dashboard entre la bio et le logo Syléa. Échelle MAX (toute l'historique
// depuis profil.cree_le ou objectif_modifie_le). Couleurs Sylea (cyan→bleu→
// violet) avec transparence pour s'intégrer au dashboard.

import { useMemo } from 'react'
import { buildHistoricalPoints } from '../utils/statsBuild'
import type { ProfilUtilisateur, Decision } from '../types'

interface Props {
  profil: ProfilUtilisateur
  decisions: Decision[]
  width?: number
  height?: number
}

export function ObjectiveProgressMini({
  profil,
  decisions,
  width = 400,
  height = 170,
}: Props) {
  // Identifiant unique pour les <defs> SVG (évite collisions si le composant
  // est monté plusieurs fois).
  const uid = useMemo(() => Math.random().toString(36).slice(2, 8), [])

  const { histPoints, totalElapsedMs } = useMemo(
    () => buildHistoricalPoints(profil as any, decisions as any),
    [profil, decisions]
  )

  const PAD_X = 6
  const PAD_Y = 14
  const innerW = width - PAD_X * 2
  const innerH = height - PAD_Y * 2

  // Helpers de projection. yFromProb : prob∈[0,100] → y SVG (haut = 100%).
  const xFromMs = (ms: number) =>
    PAD_X + (ms / Math.max(totalElapsedMs, 1)) * innerW
  const yFromProb = (prob: number) => {
    const clamped = Math.min(100, Math.max(0, prob))
    return PAD_Y + innerH * (1 - clamped / 100)
  }

  // Cas dégradé : pas assez de points (compte tout neuf, aucun temps écoulé).
  const hasEnoughData = histPoints.length >= 2 && totalElapsedMs > 1

  const baseY = height - PAD_Y
  const leftX = PAD_X
  const rightX = width - PAD_X

  let pathD = ''
  let areaD = ''
  // Coords du PREMIER point reellement echantillonne par la sigmoide :
  // important pour ancrer le dot de depart SUR la courbe (sinon le sigmoide
  // melange les deltas futurs et la courbe demarre au-dessus de baseY).
  let firstX = leftX
  let firstY = baseY
  let lastX = rightX
  let lastY = baseY
  let progressionActuelle = 0

  if (hasEnoughData) {
    // Mode LISSE (sigmoide) — meme logique que le mode smooth du Chart 2
    // de StatistiquesPage. Chaque decision cree une transition douce
    // (sigmoide) au lieu d'une marche d'escalier brutale.
    const last = histPoints[histPoints.length - 1]
    const first = histPoints[0]

    if (histPoints.length >= 2) {
      const baseProb = first.prob
      const totalRange = totalElapsedMs || 1
      const avgGap =
        histPoints.length > 1
          ? (last.elapsedMs - first.elapsedMs) / (histPoints.length - 1)
          : totalRange
      const transWidth = Math.max(avgGap * 0.6, totalRange * 0.06)

      // Fonction continue : a l'instant ems, quelle est la proba lissee ?
      const smoothProb = (ems: number): number => {
        let prob = baseProb
        for (let i = 1; i < histPoints.length; i++) {
          const delta = histPoints[i].prob - histPoints[i - 1].prob
          const center = histPoints[i].elapsedMs
          const x = (ems - center) / transWidth
          const sig = 1 / (1 + Math.exp(-3 * x))
          prob += delta * sig
        }
        return prob
      }

      // Echantillonnage uniforme — 80 points suffisent pour un mini chart
      const numSamples = 80
      const startEms = first.elapsedMs
      const endEms = last.elapsedMs
      const rangeEms = endEms - startEms || 1

      const pts: { x: number; y: number }[] = []
      for (let s = 0; s <= numSamples; s++) {
        const ems = startEms + (rangeEms * s) / numSamples
        const prob = smoothProb(ems)
        pts.push({ x: xFromMs(ems), y: yFromProb(prob) })
      }

      pathD = pts
        .map((p, i) =>
          i === 0
            ? `M ${p.x.toFixed(1)} ${p.y.toFixed(1)}`
            : `L ${p.x.toFixed(1)} ${p.y.toFixed(1)}`
        )
        .join(' ')

      // Aire sous la courbe (ferme la courbe au baseline)
      const lastPt = pts[pts.length - 1]
      const firstPt = pts[0]
      areaD =
        pathD +
        ` L ${lastPt.x.toFixed(1)} ${baseY.toFixed(1)}` +
        ` L ${firstPt.x.toFixed(1)} ${baseY.toFixed(1)} Z`

      firstX = firstPt.x
      firstY = firstPt.y
      lastX = lastPt.x
      lastY = lastPt.y
      progressionActuelle = last.prob
    }
  } else {
    // Baseline plate à prob=0 sur toute la largeur.
    pathD = `M ${leftX} ${baseY} L ${rightX} ${baseY}`
    areaD = ''
    firstX = leftX
    firstY = baseY
    lastX = rightX
    lastY = baseY
    progressionActuelle = 0
  }

  // Décale le label "X%" pour qu'il ne chevauche pas le dot final.
  const labelOffset = 16

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ display: 'block', overflow: 'visible' }}
      aria-hidden
    >
      <defs>
        {/* Aire sous la courbe — gradient cyan→violet en userSpaceOnUse pour
            que le dégradé fonctionne même sur une aire plate. */}
        <linearGradient
          id={`mini-area-${uid}`}
          x1={width / 2} y1={PAD_Y}
          x2={width / 2} y2={baseY}
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.32" />
          <stop offset="100%" stopColor="#8b5cf6" stopOpacity="0.02" />
        </linearGradient>
        {/* Ligne — gradient horizontal cyan→bleu→violet du logo Syléa.
            CRUCIAL : userSpaceOnUse, sinon une ligne plate (bbox.height=0)
            collapse le gradient et le stroke devient invisible. */}
        <linearGradient
          id={`mini-line-${uid}`}
          x1={leftX} y1={0}
          x2={rightX} y2={0}
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0%" stopColor="#22d3ee" stopOpacity="1" />
          <stop offset="50%" stopColor="#3b82f6" stopOpacity="1" />
          <stop offset="100%" stopColor="#8b5cf6" stopOpacity="1" />
        </linearGradient>
      </defs>

      {/* Aire sous la courbe (uniquement si on a des données) */}
      {areaD && <path d={areaD} fill={`url(#mini-area-${uid})`} />}

      {/* Ligne de progression — épaisse pour rester très visible. */}
      <path
        d={pathD}
        fill="none"
        stroke={`url(#mini-line-${uid})`}
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Dot de depart — ancre SUR la courbe (pas au coin bas-gauche), pour
          que la sigmoide qui peut demarrer au-dessus de baseY ne cree pas
          un decalage visuel entre le dot et l'amorce de la ligne. */}
      <circle
        cx={firstX}
        cy={firstY}
        r={3}
        fill="#22d3ee"
        opacity={0.85}
      />

      {/* Dot final (état actuel) — repère lumineux violet */}
      <circle cx={lastX} cy={lastY} r={10} fill="#8b5cf6" opacity={0.18} />
      <circle cx={lastX} cy={lastY} r={4} fill="#8b5cf6" opacity={1} />

      {/* Pourcentage en petit, à côté du dot final. */}
      <text
        x={lastX + labelOffset}
        y={lastY + 4}
        fontSize="12"
        fontWeight="600"
        fill="#a78bfa"
        opacity="0.9"
        style={{ fontFamily: 'Inter, system-ui, sans-serif', letterSpacing: '-0.01em' }}
      >
        {progressionActuelle.toFixed(0)}%
      </text>
    </svg>
  )
}
