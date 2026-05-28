// Types TypeScript miroir des schémas Pydantic de l'API Syléa.AI

export interface AgentProposal {
  id: string
  agent_label: string         // 'agent1' | 'agent2'
  type: string                // 'evenement' | 'decision_majeure' | 'info_profil_critique'
  description: string
  impact_jours: number
  resume: string
  rationale: string
  target_so_hint: string
  statut: string              // 'pending' | 'confirmed' | 'rejected'
  created_at: string
}

export interface DeviceContext {
  heure: number
  minute: number
  fuseau_horaire: string
  latitude: number
  longitude: number
  ville: string
  temperature: number
  meteo: string
}

export interface Objectif {
  description: string
  categorie: string
  deadline: string | null
  probabilite_base?: number
  probabilite_calculee?: number
}

export interface Profil {
  id: string
  nom: string
  age: number
  genre: string
  profession: string
  ville: string
  situation_familiale: string
  revenu_annuel: number
  patrimoine_estime: number
  charges_mensuelles: number
  objectif_financier: number | null
  heures_travail: number
  heures_sommeil: number
  heures_loisirs: number
  heures_transport: number
  heures_objectif: number
  niveau_sante: number
  niveau_stress: number
  niveau_energie: number
  niveau_bonheur: number
  competences: string[]
  diplomes: string[]
  langues: string[]
  objectif: Objectif | null
  probabilite_actuelle: number
  temps_initial_jours: number
  temps_gagne_jours: number
  cree_le: string
  mis_a_jour_le: string
  objectif_modifie_le: string | null
  photo_url?: string | null
}

export interface ProfilIn {
  nom: string
  age: number
  genre?: string
  profession: string
  ville: string
  situation_familiale: string
  revenu_annuel: number
  patrimoine_estime: number
  charges_mensuelles: number
  objectif_financier?: number | null
  heures_travail?: number
  heures_sommeil?: number
  heures_loisirs?: number
  heures_transport?: number
  heures_objectif?: number
  niveau_sante?: number
  niveau_stress?: number
  niveau_energie?: number
  niveau_bonheur?: number
  competences?: string[]
  diplomes?: string[]
  langues?: string[]
  objectif?: {
    description: string
    categorie: string
    deadline?: string | null
    probabilite_base?: number
  } | null
  reset_historique?: boolean
}

export interface AnalyseOption {
  lettre: string
  description: string
  pros: string[]
  cons: string[]
  impact_probabilite: number
  impact_jours: number
  resume: string
  impact_jours_brut?: number
}

export interface AnalyseDilemme {
  question: string
  options: { lettre: string; description: string; pros: string[]; cons: string[]; impact_probabilite: number; resume: string; impact_jours_brut?: number }[]
  verdict: string
  option_recommandee: string  // "A", "B", "C"...
  etude_scientifique?: string
}

export interface OptionDilemme {
  id: string
  description: string
  impact_score: number
  explication_impact: string
  est_delegable: boolean
  temps_estime: number
}

export interface ActionAgent {
  id: string
  instruction: string
  skill_utilise: string
  statut: string
  resultat: string
  temps_passe: number
  execute_le: string
}

export interface Decision {
  id: string
  user_id: string
  question: string
  options: OptionDilemme[]
  probabilite_avant: number
  option_choisie_id: string | null
  probabilite_apres: number | null
  temps_gagne_avant: number
  temps_gagne_apres: number
  action_agent: ActionAgent | null
  cree_le: string
  option_choisie_description: string | null
  impact_net: number | null
  sous_objectif_impacte?: string | null
  sous_objectif_id?: string | null
  impact_sous_objectif?: number | null
}

export interface ProbabiliteResult {
  probabilite: number
  temps_initial_jours: number
  resume: string
  points_forts: string[]
  points_faibles: string[]
  facteurs_cles: string[]
  conseil_prioritaire: string
}

export interface BienEtreScores {
  niveau_sante: number
  niveau_stress: number
  niveau_energie: number
  niveau_bonheur: number
}

export const CATEGORIES_OBJECTIF = ['carrière', 'santé', 'finance', 'relation', 'développement'] as const
export const SITUATIONS_FAMILIALES = ['célibataire', 'en couple', 'marié(e)', 'divorcé(e)', 'veuf/veuve'] as const

export interface AnalyseEvenement {
  resume: string
  impact_probabilite: number
  impact_jours: number
  explication: string
  conseil: string
}


export interface BilanQuotidien {
  id: string
  date: string
  niveau_sante: number
  niveau_stress: number
  niveau_energie: number
  niveau_bonheur: number
  heures_travail: number
  heures_sommeil: number
  heures_loisirs: number
  heures_transport: number
  heures_objectif: number
  description: string
  cree_le: string
}

export interface BilanCheck {
  exists: boolean
  bilan?: BilanQuotidien
}


// Sous-objectifs
export interface SousObjectif {
  id: string
  titre: string
  description: string
  progression: number
  ordre: number
  temps_estime: number
}

// Taches quotidiennes
export interface TacheItem {
  id: string
  description: string
  completee: boolean
  titre?: string
  duree?: string
  type?: string
  lien?: string
  icone?: string
}

export interface TachesQuotidiennes {
  id: string
  date: string
  taches: TacheItem[]
  deadline: string
  statut: string
  cree_le: string
}

export interface TachesCheck {
  exists: boolean
  taches?: TachesQuotidiennes
}

export interface CompleterTacheResult {
  tache: TacheItem
  impact_principal: number
  impacts_sous_objectifs: { id: string; progression: number }[]
  sous_objectif_impacte?: string
}

// Personnalite IA
export interface PersonnaliteIA {
  phrase: string
}

// ─── Dilemme tracking (nouveau systeme) ───────────────────────────────────
export type TrackingStatus = 'tracking' | 'awaiting_validation' | 'validated' | 'cancelled'

export interface TrackingOption {
  lettre: string
  description: string
  impact_jours: number
  pros: string[]
  cons: string[]
  resume: string
}

export interface TrackingChoice {
  periode_idx: number
  choice: string | null  // "0", "1", ..., "none", ou null si pas encore repondu
  responded_at: string | null
  retry_count: number
}

export interface TrackingItem {
  id: string
  question: string
  options: TrackingOption[]
  verdict: string
  etude_scientifique: string
  impact_temporel_jours: number
  nb_periodes: number
  device_tz: string
  choices: TrackingChoice[]
  status: TrackingStatus
  impact_final_jours: number | null
  impact_final_probabilite: number | null
  so_impactes: { titre: string; progression_avant: number; progression_apres: number; est_cible: boolean }[]
  cancellation_mode: 'zero' | 'partial' | null
  next_notif_at: string | null
  created_at: string
  validated_at: string | null
  cancelled_at: string | null
}

export interface TrackingRecapBreakdown {
  option: string  // "0", "1", ..., "none"
  label: string
  nb_clicks: number
  percentage: number
  impact_pondere: number
}

export interface TrackingRecap {
  ok: boolean
  tracking_id: string
  status: TrackingStatus
  recap: {
    breakdown: TrackingRecapBreakdown[]
    impact_total_jours: number
    nb_periodes: number
  }
  delta_probabilite_preview: number
  probabilite_actuelle: number
}
