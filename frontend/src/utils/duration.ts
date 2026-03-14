// Conversion probabilité → durée estimée d'atteinte d'objectif
//
// Formule log-logistique :  totalJours = 900 × ((100 - p) / p)^0.675
// Inverse               :  p = 100 / (1 + (totalJours / 900)^(1 / 0.675))
//
// Calibration clé :
//   p = 1.67 %  →  ~38 ans    (objectif milliardaire, très difficile)
//   p = 5 %     →  ~19 ans    (objectif extrêmement ambitieux)
//   p = 10 %    →  ~11 ans    (objectif très ambitieux)
//   p = 31 %    →  ~4,3 ans   (objectif ambitieux, quasi inchangé)
//   p = 50 %    →  ~2,5 ans   (objectif réaliste)
//   p = 90 %    →  ~4 mois    (objectif accessible)
//
// Cap : 73 000 jours (~200 ans) pour les probabilités extrêmement basses.

const _K     = 900
const _ALPHA = 0.675          // exposant log-logistique
const _MAX_J = 73000          // ~200 ans plafond

export interface DureeEstimee {
  annees:     number
  mois:       number
  jours:      number
  totalJours: number
  /** Ligne principale dans la jauge, ex. "8 ANS" ou "3 MOIS" ou "12 JOURS" */
  ligne1:     string
  /** Ligne secondaire dans la jauge, ex. "3 MOIS 1 J" ou "6 JOURS" ou "" */
  ligne2:     string
  /** Label texte complet pour affichage hors jauge */
  label:      string
}

export function dureeFromProb(prob: number): DureeEstimee {
  const p      = Math.max(0.01, Math.min(99.99, prob))
  const ratio  = (100 - p) / p
  const totalJ = Math.min(_MAX_J, Math.max(1, Math.round(_K * Math.pow(ratio, _ALPHA))))

  const annees   = Math.floor(totalJ / 365)
  const restJ    = totalJ % 365
  const mois     = Math.floor(restJ / 30)
  const jours    = restJ % 30

  // ── Ligne principale ──────────────────────────────────────────────────
  let ligne1: string
  let ligne2: string
  let label: string

  if (annees >= 1) {
    ligne1 = `${annees} AN${annees > 1 ? 'S' : ''}`
    // Ligne 2 : mois + jours si présents
    if (mois > 0 && jours > 0) {
      ligne2 = `${mois} MOIS ${jours} J`
    } else if (mois > 0) {
      ligne2 = `${mois} MOIS`
    } else if (jours > 0) {
      ligne2 = `${jours} JOURS`
    } else {
      ligne2 = ''
    }
    label = `${annees} an${annees > 1 ? 's' : ''}${mois > 0 ? ` ${mois} mois` : ''}${jours > 0 ? ` ${jours} jour${jours > 1 ? 's' : ''}` : ''}`
  } else if (mois >= 1) {
    ligne1 = `${mois} MOIS`
    ligne2 = jours > 0 ? `${jours} JOUR${jours > 1 ? 'S' : ''}` : ''
    label  = `${mois} mois${jours > 0 ? ` ${jours} jour${jours > 1 ? 's' : ''}` : ''}`
  } else {
    ligne1 = `${jours} JOUR${jours > 1 ? 'S' : ''}`
    ligne2 = ''
    label  = `${jours} jour${jours > 1 ? 's' : ''}`
  }

  return { annees, mois, jours, totalJours: totalJ, ligne1, ligne2, label }
}

/**
 * Inverse de dureeFromProb : probabilité en % pour un nombre de jours donné.
 * p = 100 / (1 + (totalJours / K)^(1 / alpha))
 */
export function probFromJours(totalJ: number): number {
  if (totalJ <= 0)      return 100
  if (totalJ >= _MAX_J) return 0
  const r = Math.pow(totalJ / _K, 1 / _ALPHA)
  return Math.max(0, Math.min(100, 100 / (1 + r)))
}

/**
 * Calcule le gain/perte de temps correspondant à un impact en points de probabilité.
 * Retourne un label court : "+1a 6m", "-45j", "+12h", etc.
 * La durée inclut des heures si le delta est inférieur à 1 jour.
 */
export function deltaFromImpact(probActuelle: number, impactPoints: number): string {
  const pAvant = Math.max(0, Math.min(100, probActuelle))
  const pApres = Math.max(0, Math.min(100, probActuelle + impactPoints))
  const dAvant = dureeFromProb(pAvant)
  const dApres = dureeFromProb(pApres)
  // positif = gain de temps (bonne décision), négatif = perte
  const deltaFloat = dAvant.totalJours - dApres.totalJours
  const sign = deltaFloat >= 0 ? '+' : '-'
  const abs  = Math.abs(deltaFloat)

  if (abs < 1) {
    const h = Math.round(abs * 24)
    return h === 0 ? '0h' : `${sign}${h}h`
  }

  const absJ  = Math.round(abs)
  const ans   = Math.floor(absJ / 365)
  const restJ = absJ % 365
  const mois  = Math.floor(restJ / 30)
  const jours = restJ % 30

  if (ans >= 1) {
    return `${sign}${ans}a${mois > 0 ? ` ${mois}m` : ''}`
  } else if (mois >= 1) {
    return `${sign}${mois}m${jours > 0 ? ` ${jours}j` : ''}`
  } else {
    return `${sign}${absJ}j`
  }
}

/**
 * Génère des ticks adaptés pour un axe X de durée réelle.
 * @param elapsedDays  durée totale en jours (fractionnaire autorisé)
 * @returns tableau { valueDays, label }
 */
export function buildTimeTicks(elapsedDays: number): { valueDays: number; label: string }[] {
  const ticks: { valueDays: number; label: string }[] = []
  const add = (d: number, l: string) => ticks.push({ valueDays: d, label: l })

  if (elapsedDays < 1) {
    // Moins d'un jour → heures
    const totalH = elapsedDays * 24
    const step   = totalH <= 2 ? 0.5 : totalH <= 6 ? 1 : totalH <= 12 ? 2 : 4
    for (let h = 0; h <= totalH + 0.01; h += step) {
      const rounded = Math.round(h * 10) / 10
      add(h / 24, rounded === 0 ? '0' : `${rounded}h`)
    }
  } else if (elapsedDays < 30) {
    // Jours — ticks entiers uniquement pour éviter les doublons
    const n    = Math.min(6, Math.floor(elapsedDays))
    const step = Math.max(1, Math.ceil(elapsedDays / 6))
    add(0, '0')
    for (let d = step; d <= elapsedDays; d += step) {
      add(d, `J+${Math.round(d)}`)
    }
  } else if (elapsedDays < 365) {
    // Mois
    const months = elapsedDays / 30.44
    const n      = Math.min(6, Math.ceil(months))
    const step   = months / n
    for (let i = 0; i <= n; i++) {
      const m = i * step
      add(m * 30.44, m < 0.5 ? '0' : `${Math.round(m)}m`)
    }
  } else {
    // Années + mois
    const totalMonths = elapsedDays / 30.44
    const n           = Math.min(6, Math.ceil(totalMonths / 6))
    const stepMonths  = totalMonths / n
    for (let i = 0; i <= n; i++) {
      const m = i * stepMonths
      const a = Math.floor(m / 12)
      const r = Math.round(m % 12)
      const label =
        m < 0.5 ? '0'
        : a === 0 ? `${r}m`
        : r === 0 ? `${a}a`
        : `${a}a${r}m`
      add(m * 30.44, label)
    }
  }
  return ticks
}
