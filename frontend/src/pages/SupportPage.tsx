// Page de support et résolution d'incidents — Syléa.AI
// Document exhaustif couvrant tous les problèmes susceptibles d'être rencontrés
// avec leur procédure de résolution pas-à-pas.

import { useState } from 'react'
import { Link } from 'react-router-dom'

interface FAQItem {
  category: string
  question: string
  steps: string[]
  severity?: 'info' | 'warning' | 'critical'
}

const FAQ_DATA: FAQItem[] = [
  // ─── Catégorie : Compte et connexion ─────────────────────────────────────
  {
    category: 'Compte et connexion',
    question: 'Je n\'arrive pas à me connecter (mot de passe incorrect)',
    steps: [
      'Vérifiez que les majuscules ne sont pas activées (touche Verr. Maj.).',
      'Vérifiez que vous utilisez la même adresse électronique que lors de l\'inscription.',
      'Si vous avez oublié le mot de passe, cliquez sur « Mot de passe oublié » depuis la page de connexion. Un courrier de réinitialisation sera envoyé à votre adresse.',
      'Vérifiez votre dossier de courriers indésirables (spam) si le message ne semble pas arrivé.',
      'Si vous vous êtes inscrit via Google ou GitHub, utilisez le bouton OAuth correspondant au lieu du formulaire e-mail.',
      'Après 5 tentatives infructueuses, votre compte est temporairement verrouillé pendant 15 minutes pour des raisons de sécurité.',
      'Si le problème persiste, contactez sylea.ai.assistance@gmail.com en précisant votre adresse e-mail.',
    ],
  },
  {
    category: 'Compte et connexion',
    question: 'Je n\'ai pas reçu le code de vérification par e-mail',
    steps: [
      'Patientez 1 à 2 minutes : la délivrance peut être différée par votre fournisseur de messagerie.',
      'Vérifiez votre dossier « courriers indésirables » ou « spam ».',
      'Vérifiez que l\'adresse renseignée est exacte (sans faute de frappe).',
      'Ajoutez sylea.ai.assistance@gmail.com à vos contacts pour éviter le filtrage.',
      'Cliquez sur « Renvoyer le code » depuis l\'écran de vérification. Notez qu\'un délai de 60 secondes s\'applique entre deux envois pour limiter les abus.',
      'Si après 10 minutes vous n\'avez toujours rien reçu, essayez avec une autre adresse e-mail.',
      'Pour les adresses professionnelles, certains pare-feux d\'entreprise bloquent les e-mails transactionnels : utilisez une adresse personnelle (Gmail, Outlook).',
    ],
    severity: 'info',
  },
  {
    category: 'Compte et connexion',
    question: 'Je veux supprimer mon compte définitivement',
    steps: [
      'Connectez-vous à votre compte.',
      'Accédez à « Paramètres » via le menu de navigation.',
      'Faites défiler jusqu\'à la section « Zone de danger ».',
      'Cliquez sur « Supprimer mon compte » et confirmez en saisissant votre mot de passe.',
      'Un courrier de confirmation final vous sera adressé. Cliquez sur le lien dans les 24 heures pour confirmer la suppression.',
      'Conformément au RGPD, vos données personnelles seront effacées dans les 30 jours suivant la confirmation.',
      'Les données comptables et fiscales (factures) seront conservées 10 ans conformément au code de commerce.',
      'Si vous souhaitez exporter vos données avant suppression, utilisez « Exporter mes données » dans la même section.',
    ],
    severity: 'warning',
  },
  {
    category: 'Compte et connexion',
    question: 'Mon compte a été suspendu — que faire ?',
    steps: [
      'Lisez attentivement le courrier électronique de notification qui vous a été envoyé : il précise le motif de la suspension.',
      'Si vous estimez la suspension injustifiée, contactez sylea.ai.assistance@gmail.com en exposant vos arguments et en joignant toute pièce utile.',
      'Vos données restent conservées pendant la durée de l\'examen de votre contestation.',
      'Délai de réponse cible : 5 jours ouvrés.',
      'Si la suspension est confirmée, vous pourrez demander la portabilité de vos données conformément à l\'article 20 du RGPD.',
    ],
    severity: 'warning',
  },

  // ─── Catégorie : Profil et wizard ────────────────────────────────────────
  {
    category: 'Profil et création',
    question: 'Le wizard de création de profil ne valide pas mes données',
    steps: [
      'Vérifiez que tous les champs marqués d\'un astérisque (*) sont remplis.',
      'L\'âge doit être compris entre 15 et 120 ans.',
      'Le revenu annuel, le patrimoine et les charges doivent être des nombres positifs (utilisez le point comme séparateur décimal, pas la virgule).',
      'La description de l\'objectif doit comporter au moins 10 caractères.',
      'La deadline de l\'objectif doit être postérieure à la date du jour.',
      'Les volumes horaires (travail, sommeil, etc.) ne doivent pas dépasser 24 heures au total.',
      'Si une erreur 422 apparaît, vérifiez que la catégorie de l\'objectif est bien choisie parmi : carrière, santé, finance, relation, développement.',
    ],
  },
  {
    category: 'Profil et création',
    question: 'Je veux modifier mon profil après création',
    steps: [
      'Connectez-vous et accédez à « Paramètres ».',
      'Section « Profil » : modifiez les champs souhaités puis cliquez sur « Enregistrer ».',
      'Pour modifier votre objectif principal, accédez à « Mon objectif » dans le menu principal.',
      'Attention : une modification substantielle de l\'objectif réinitialise le calcul de progression et invalide les sous-objectifs existants. Vous serez prévenu avant validation.',
      'Les modifications sont enregistrées en temps réel et synchronisées sur tous vos appareils.',
    ],
  },

  // ─── Catégorie : Agents Syléa ─────────────────────────────────────────────
  {
    category: 'Agents Syléa',
    question: 'L\'Agent Syléa 1 (Compagnon) ne me répond pas ou répond très lentement',
    steps: [
      'Vérifiez votre connexion Internet (test sur un autre site web).',
      'Patientez 30 à 60 secondes : la génération par IA peut prendre du temps selon la longueur de la réponse.',
      'Rechargez la page (F5 ou Ctrl+R).',
      'Si l\'agent répond « Agent indisponible — clé API manquante », il s\'agit d\'un problème de configuration côté serveur : signalez-le à sylea.ai.assistance@gmail.com.',
      'Si vous obtenez « Quota quotidien atteint », vous avez utilisé votre limite journalière. Patientez jusqu\'à minuit (UTC) ou passez à un plan supérieur.',
      'Vérifiez que l\'Agent Syléa 1 est bien activé dans la section « Mes agents Syléa ».',
    ],
  },
  {
    category: 'Agents Syléa',
    question: 'L\'Agent Syléa 2 (Assistant) est inaccessible',
    steps: [
      'L\'Agent Syléa 2 est réservé aux plans payants (Avancé et supérieurs). Avec le plan Gratuit, vous obtenez une erreur 403.',
      'Pour y accéder, passez à un plan payant depuis la page « Quotas et abonnements ».',
      'Si vous êtes déjà sur un plan payant et obtenez 403, vérifiez que votre abonnement est actif (page Quotas).',
      'En cas de problème de paiement, contactez sylea.ai.assistance@gmail.com.',
    ],
  },
  {
    category: 'Agents Syléa',
    question: 'L\'agent me répète les mêmes messages proactifs',
    steps: [
      'Ce comportement est désormais corrigé : un délai minimum de 24 heures est appliqué entre deux messages proactifs.',
      'Si vous voyez encore d\'anciens messages dupliqués, ils ont été générés avant la correction. Vous pouvez les ignorer ou effacer la conversation depuis le menu « Effacer la conversation » dans l\'agent.',
      'Pour désactiver complètement les notifications proactives : Paramètres > Notifications > Désactiver « Messages proactifs ».',
    ],
  },
  {
    category: 'Agents Syléa',
    question: 'Les recommandations de l\'IA me semblent incohérentes ou erronées',
    steps: [
      'Les analyses produites par l\'intelligence artificielle peuvent comporter des erreurs, biais ou imprécisions. Elles constituent une AIDE À LA DÉCISION et non une décision en elle-même.',
      'Vérifiez que votre profil est complet et à jour (nom, âge, profession, objectif). Plus le profil est précis, plus les recommandations sont pertinentes.',
      'Reformulez votre question en étant plus spécifique (contexte, contraintes, alternatives).',
      'Utilisez le bouton « pouce vers le bas » sous chaque message pour signaler une réponse insatisfaisante : Syléa s\'appuie sur ces retours pour améliorer la qualité au fil du temps.',
      'Pour les décisions importantes (santé, finances, juridique), consultez systématiquement un professionnel qualifié. Le Service ne remplace en aucun cas un avis professionnel.',
    ],
    severity: 'warning',
  },

  // ─── Catégorie : Dilemmes et analyses ────────────────────────────────────
  {
    category: 'Dilemmes et analyses',
    question: 'L\'analyse d\'un dilemme retourne une erreur 503 « Analyse IA indisponible »',
    steps: [
      'Patientez 30 secondes puis réessayez : l\'API Claude peut être temporairement surchargée.',
      'Vérifiez votre connexion Internet.',
      'Si l\'erreur persiste plus de 5 minutes, l\'API tierce (Anthropic) est probablement en panne. Vérifiez status.anthropic.com.',
      'En attendant le rétablissement, vous pouvez tout de même créer le dilemme : il sera analysé localement sans IA.',
      'Signaler la panne prolongée à sylea.ai.assistance@gmail.com.',
    ],
  },
  {
    category: 'Dilemmes et analyses',
    question: 'Le calcul de probabilité ne change pas après mes décisions',
    steps: [
      'Vérifiez que vous avez bien validé votre choix (bouton « Confirmer ce choix »).',
      'La probabilité est recalculée immédiatement après validation. Rechargez la page si le changement ne s\'affiche pas.',
      'Si vous avez validé une option à impact temporel nul (0 jour), aucune variation n\'apparaîtra.',
      'L\'impact d\'une décision sur la probabilité est plafonné par les contraintes du moteur (PROB_MIN=0.01, PROB_MAX=99.9). Une probabilité saturée à 99.9 % ne pourra pas augmenter davantage.',
      'Consultez la page « Statistiques » pour voir l\'évolution graphique de votre probabilité dans le temps.',
    ],
  },
  {
    category: 'Dilemmes et analyses',
    question: 'Mes décisions passées ont disparu de l\'historique',
    steps: [
      'L\'historique conserve toutes vos décisions tant que votre compte est actif.',
      'Si l\'historique semble vide après reconnexion, vérifiez que vous êtes bien sur le bon compte (l\'icône de profil en haut à droite).',
      'En cas de disparition réelle, contactez sylea.ai.assistance@gmail.com en précisant la date approximative de vos dernières décisions.',
      'Si vous avez exporté vos données puis supprimé votre compte, l\'historique a été effacé conformément à votre demande RGPD : il ne peut être restauré.',
    ],
    severity: 'warning',
  },

  // ─── Catégorie : Paiement et abonnement ──────────────────────────────────
  {
    category: 'Paiement et abonnement',
    question: 'Mon paiement a échoué',
    steps: [
      'Vérifiez les informations de votre carte bancaire (numéro, date d\'expiration, CVV).',
      'Vérifiez le solde de votre compte bancaire et l\'éventuel plafond de carte.',
      'Si votre banque utilise l\'authentification 3D Secure, validez la transaction via votre application bancaire mobile.',
      'Essayez avec une autre carte bancaire.',
      'Si vous voyez une erreur Stripe, notez le code d\'erreur et contactez sylea.ai.assistance@gmail.com.',
      'Pour les paiements internationaux, vérifiez auprès de votre banque que les paiements à destination des États-Unis (Stripe) sont autorisés.',
    ],
  },
  {
    category: 'Paiement et abonnement',
    question: 'Je veux résilier mon abonnement payant',
    steps: [
      'Accédez à « Paramètres » > « Abonnement ».',
      'Cliquez sur « Résilier mon abonnement ».',
      'Confirmez votre choix. Vous conservez l\'accès aux fonctionnalités premium jusqu\'à la fin de la période en cours.',
      'À l\'échéance, votre compte basculera automatiquement sur le plan Gratuit.',
      'Conformément aux CGU, aucun remboursement au prorata n\'est effectué sauf disposition impérative contraire (consommateurs UE).',
      'Vos données restent conservées : vous pouvez réactiver votre abonnement à tout moment.',
    ],
  },
  {
    category: 'Paiement et abonnement',
    question: 'Je veux obtenir une facture',
    steps: [
      'Toutes les factures sont disponibles dans « Paramètres » > « Abonnement » > « Historique de facturation ».',
      'Cliquez sur « Télécharger PDF » pour la facture souhaitée.',
      'Les factures sont au nom et à l\'adresse fournis lors de la souscription. Pour modifier ces informations, contactez sylea.ai.assistance@gmail.com.',
      'Les factures sont conservées 10 ans, conformément aux obligations comptables.',
    ],
  },

  // ─── Catégorie : Intégrations tierces ────────────────────────────────────
  {
    category: 'Intégrations tierces',
    question: 'Google Calendar / Gmail / Drive ne fonctionne pas',
    steps: [
      'Accédez à « Intégrations » dans le menu.',
      'Cliquez sur « Reconnecter » pour le service concerné.',
      'Lors de la nouvelle autorisation Google, vérifiez que vous cochez bien tous les scopes demandés (Calendar, Gmail, Drive).',
      'Si Google affiche « Cette application n\'est pas vérifiée », c\'est normal en phase bêta : cliquez sur « Avancé » puis « Continuer (non sûr) » — l\'application est légitime, simplement en attente de validation Google formelle.',
      'En cas d\'erreur 403 lors de l\'utilisation, votre jeton OAuth a peut-être expiré : reconnectez-vous.',
      'Si certains scopes sont refusés (par exemple gmail.send), les fonctionnalités correspondantes ne seront pas disponibles.',
    ],
  },
  {
    category: 'Intégrations tierces',
    question: 'GitHub / Notion / Slack ne se connecte pas',
    steps: [
      'Pour GitHub : créez un Personal Access Token avec les scopes repo, user, read:org depuis github.com/settings/tokens, puis collez-le dans Intégrations > GitHub.',
      'Pour Notion : créez une intégration interne sur notion.so/my-integrations, copiez le token interne, puis ajoutez l\'intégration aux pages que vous souhaitez exposer.',
      'Pour Slack : créez un Incoming Webhook depuis votre espace Slack (Settings > Apps > Incoming Webhooks), puis collez l\'URL du webhook.',
      'Si vous obtenez une erreur 401 « Token invalide », le jeton a probablement expiré ou été révoqué : recréez-en un nouveau.',
      'Les tokens sont chiffrés (AES-128) avant stockage. Jamais en clair.',
    ],
  },

  // ─── Catégorie : Données et confidentialité ──────────────────────────────
  {
    category: 'Données et confidentialité',
    question: 'Comment exporter mes données (RGPD article 20) ?',
    steps: [
      'Accédez à « Paramètres » > « Confidentialité ».',
      'Cliquez sur « Exporter mes données ».',
      'Un fichier JSON contenant toutes vos données sera téléchargé automatiquement.',
      'Le fichier inclut : profil, décisions, sous-objectifs, bilans, conversations agents, mémoires, intégrations (sans les tokens), et l\'historique de facturation.',
      'Les données de carte bancaire ne sont jamais exportées (elles ne sont jamais collectées par Syléa).',
      'L\'export est instantané pour les comptes standards. Pour les comptes Enterprise avec gros volumes, il peut prendre quelques minutes : vous recevrez un lien de téléchargement par e-mail.',
    ],
  },
  {
    category: 'Données et confidentialité',
    question: 'Je veux exercer mon droit à l\'oubli (RGPD article 17)',
    steps: [
      'Méthode 1 (rapide) : Paramètres > Zone de danger > Supprimer mon compte. Effacement dans les 30 jours.',
      'Méthode 2 (manuelle) : envoyez un courrier à sylea.ai.assistance@gmail.com avec pour objet « Demande d\'effacement RGPD ». Précisez votre identité (nom, e-mail du compte).',
      'Une vérification d\'identité peut être requise pour les demandes non authentifiées.',
      'L\'effacement est effectué sous 30 jours maximum.',
      'Les données comptables et fiscales sont conservées 10 ans (obligation légale, article L.123-22 du code de commerce).',
      'Vous recevrez une confirmation écrite de l\'effacement.',
    ],
  },
  {
    category: 'Données et confidentialité',
    question: 'Mes données sont-elles utilisées pour entraîner des IA ?',
    steps: [
      'NON. Aucune de vos données n\'est utilisée pour entraîner des modèles d\'intelligence artificielle généraux.',
      'Vos données sont uniquement utilisées pour le fonctionnement personnalisé du Service.',
      'Anthropic (Claude) reçoit vos requêtes pour les traiter mais s\'engage contractuellement (DPA signé) à ne pas les utiliser pour l\'entraînement.',
      'OpenAI (TTS) ne reçoit que le texte à synthétiser, pas vos données personnelles.',
      'Nous pouvons utiliser des données anonymisées et agrégées (sans aucun identifiant) à des fins d\'amélioration du Service.',
    ],
  },

  // ─── Catégorie : Application desktop ─────────────────────────────────────
  {
    category: 'Application desktop',
    question: 'L\'application desktop affiche « Serveur inaccessible (localhost:8000) »',
    steps: [
      'Vérifiez que le backend Syléa tourne sur votre machine.',
      'Ouvrez un terminal et tapez : uvicorn api.main:app --port 8000',
      'Vérifiez que le pare-feu de votre OS n\'empêche pas la communication locale.',
      'Si vous souhaitez utiliser le backend cloud (hébergé), modifiez l\'URL en console Tauri (Ctrl+Shift+I) : localStorage.setItem(\'sylea_api_base\', \'https://api.sylea.ai\') puis rechargez.',
      'Pour les builds packagés, définissez VITE_API_BASE au build : echo "VITE_API_BASE=https://api.sylea.ai" > desktop/.env',
    ],
  },
  {
    category: 'Application desktop',
    question: 'L\'application desktop plante au lancement',
    steps: [
      'Vérifiez la compatibilité OS : Windows 10+, macOS 11+, Ubuntu 22.04+.',
      'Désinstallez puis réinstallez la dernière version depuis la page de téléchargement.',
      'Sous Windows : exécutez l\'installeur en tant qu\'administrateur.',
      'Sous macOS : autorisez l\'application via Préférences système > Sécurité.',
      'Si le plantage persiste, exécutez en mode debug depuis un terminal : sylea-agent.exe --verbose. Envoyez les logs à sylea.ai.assistance@gmail.com.',
    ],
  },

  // ─── Catégorie : Notifications et e-mails ────────────────────────────────
  {
    category: 'Notifications et e-mails',
    question: 'Je reçois trop de notifications de Syléa',
    steps: [
      'Accédez à « Paramètres » > « Notifications ».',
      'Désactivez les catégories de notifications non souhaitées : proactives, bilans quotidiens, rappels.',
      'Pour les notifications push navigateur, cliquez sur l\'icône cadenas à gauche de l\'URL puis désactivez les notifications.',
      'Pour les notifications desktop, désactivez-les depuis l\'application desktop > Paramètres > Notifications.',
      'Les e-mails transactionnels (vérification de compte, alertes de sécurité) ne peuvent pas être désactivés.',
    ],
  },

  // ─── Catégorie : Sécurité ────────────────────────────────────────────────
  {
    category: 'Sécurité',
    question: 'Je suspecte que mon compte a été piraté',
    steps: [
      'Connectez-vous immédiatement et changez votre mot de passe depuis Paramètres > Sécurité.',
      'Activez l\'authentification à deux facteurs (2FA) si ce n\'est déjà fait.',
      'Vérifiez l\'historique de connexion dans Paramètres > Sécurité > Sessions actives. Déconnectez toutes les sessions inconnues.',
      'Vérifiez les modifications récentes du profil et des paramètres : si vous constatez des changements non effectués par vous, restaurez les valeurs.',
      'Vérifiez les intégrations actives et révoquez celles que vous n\'avez pas autorisées.',
      'Contactez sylea.ai.assistance@gmail.com en précisant la suspicion : un audit de votre compte sera diligenté.',
      'Si des données sensibles ont été exposées, vous pouvez signaler à la CNIL : www.cnil.fr.',
    ],
    severity: 'critical',
  },
  {
    category: 'Sécurité',
    question: 'Comment activer l\'authentification à deux facteurs (2FA) ?',
    steps: [
      'Accédez à « Paramètres » > « Sécurité » > « Authentification à deux facteurs ».',
      'Choisissez « Application d\'authentification » (Google Authenticator, Authy, 1Password, etc.).',
      'Scannez le QR code avec votre application.',
      'Saisissez le code à 6 chiffres généré par l\'application pour valider.',
      'Notez les codes de secours qui s\'affichent : ils permettent de récupérer l\'accès en cas de perte du téléphone.',
      'À chaque connexion future, un code à 6 chiffres vous sera demandé en plus du mot de passe.',
    ],
  },

  // ─── Catégorie : Erreurs techniques ──────────────────────────────────────
  {
    category: 'Erreurs techniques',
    question: 'Erreur 500 « Internal Server Error »',
    steps: [
      'Rechargez la page (F5).',
      'Patientez 1 à 2 minutes : un incident serveur peut être en cours.',
      'Vérifiez la page de statut : sylea-ai.statuspage.io (à venir).',
      'Videz le cache de votre navigateur (Ctrl+Shift+Suppr).',
      'Essayez avec un autre navigateur ou en navigation privée.',
      'Si l\'erreur persiste, signalez-la avec : URL exacte, heure approximative, action qui a déclenché l\'erreur, à sylea.ai.assistance@gmail.com.',
    ],
  },
  {
    category: 'Erreurs techniques',
    question: 'Erreur 429 « Too Many Requests »',
    steps: [
      'Vous avez dépassé la limite de requêtes par minute autorisée par votre plan.',
      'Patientez 60 secondes puis réessayez.',
      'Si vous utilisez l\'API, ajustez votre fréquence d\'appel (max 30/min pour le plan Avancé, 100/min pour Team).',
      'Pour augmenter les limites, passez à un plan supérieur.',
      'Les limites sont par utilisateur et par minute, lissées sur une fenêtre glissante via un algorithme de token bucket.',
    ],
  },
  {
    category: 'Erreurs techniques',
    question: 'Erreur 404 « Page introuvable »',
    steps: [
      'Vérifiez l\'URL : peut-être une faute de frappe.',
      'Cliquez sur le logo Syléa en haut à gauche pour revenir à l\'accueil.',
      'Si vous avez cliqué sur un lien depuis un email ancien, la fonctionnalité peut avoir été déplacée. Naviguez depuis le menu principal.',
      'Pour les pages tierces (politique de confidentialité, CGU), utilisez le pied de page.',
    ],
  },

  // ─── Catégorie : Performance ─────────────────────────────────────────────
  {
    category: 'Performance et lenteurs',
    question: 'L\'application est lente',
    steps: [
      'Vérifiez votre vitesse de connexion (test sur fast.com ou speedtest.net).',
      'Fermez les onglets navigateur inutilisés.',
      'Videz le cache navigateur (Ctrl+Shift+Suppr > « Images et fichiers en cache »).',
      'Mettez à jour votre navigateur (Chrome, Firefox, Edge, Safari) à la dernière version.',
      'Désactivez temporairement les extensions navigateur (ad-blockers, anti-trackers) qui peuvent ralentir le chargement.',
      'Si vous utilisez l\'app desktop, vérifiez la version installée (Aide > À propos) et mettez-la à jour si nécessaire.',
      'Les analyses IA peuvent prendre 5 à 30 secondes selon la complexité : c\'est normal.',
    ],
  },
]

const CATEGORIES = Array.from(new Set(FAQ_DATA.map(item => item.category)))

function FAQItemComponent({ item }: { item: FAQItem }) {
  const [open, setOpen] = useState(false)
  const severityColors = {
    info: 'rgba(50, 150, 255, 0.2)',
    warning: 'rgba(255, 180, 50, 0.25)',
    critical: 'rgba(255, 80, 80, 0.3)',
  }
  const borderColor = item.severity ? severityColors[item.severity] : 'var(--border)'

  return (
    <div style={{
      background: 'var(--bg-surface)',
      border: `1px solid ${borderColor}`,
      borderRadius: 'var(--radius-md)',
      marginBottom: '0.4rem',
      overflow: 'hidden',
    }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.7rem 0.95rem',
          background: 'transparent', border: 'none',
          cursor: 'pointer', color: 'var(--text-primary)',
          fontSize: '0.78rem', fontWeight: 500, textAlign: 'left',
        }}
      >
        <span>{item.question}</span>
        <span style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s', opacity: 0.5 }}>›</span>
      </button>
      {open && (
        <div style={{ padding: '0 0.95rem 0.85rem', color: 'var(--text-secondary)', fontSize: '0.72rem', lineHeight: 1.6 }}>
          <ol style={{ paddingLeft: '1.1rem', margin: '0.2rem 0' }}>
            {item.steps.map((step, i) => (
              <li key={i} style={{ marginBottom: '0.4rem' }}>{step}</li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

export default function SupportPage() {
  const [activeCategory, setActiveCategory] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  const filtered = FAQ_DATA.filter(item => {
    if (activeCategory && item.category !== activeCategory) return false
    if (search) {
      const q = search.toLowerCase()
      return item.question.toLowerCase().includes(q) ||
        item.steps.join(' ').toLowerCase().includes(q) ||
        item.category.toLowerCase().includes(q)
    }
    return true
  })

  return (
    <div className="container" style={{ maxWidth: 900, margin: '0 auto', padding: '1.5rem 1.25rem 3rem' }}>
      <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
        <div style={{ fontSize: '1.7rem', marginBottom: '0.4rem' }}>&#x1F198;</div>
        <h1 style={{ fontSize: '1.45rem', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 0.3rem' }}>
          Centre d'assistance Syléa.AI
        </h1>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.74rem', margin: 0, maxWidth: 600, marginInline: 'auto', lineHeight: 1.5 }}>
          Résolution pas-à-pas de tous les incidents techniques susceptibles d'être rencontrés.
          Si votre problème n'est pas couvert ci-dessous, contactez-nous à <strong>sylea.ai.assistance@gmail.com</strong>.
        </p>
      </div>

      {/* Barre de recherche */}
      <div style={{ marginBottom: '1rem' }}>
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Rechercher un problème (ex: connexion, paiement, agent)…"
          style={{
            width: '100%',
            padding: '0.65rem 0.9rem',
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--text-primary)',
            fontSize: '0.78rem',
            outline: 'none',
          }}
        />
      </div>

      {/* Filtres catégories */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem', marginBottom: '1rem' }}>
        <button
          onClick={() => setActiveCategory(null)}
          style={{
            padding: '0.3rem 0.7rem',
            background: !activeCategory ? 'var(--accent-violet)' : 'transparent',
            border: '1px solid var(--border)',
            borderRadius: '999px',
            color: !activeCategory ? 'white' : 'var(--text-secondary)',
            fontSize: '0.7rem',
            cursor: 'pointer',
          }}
        >
          Toutes ({FAQ_DATA.length})
        </button>
        {CATEGORIES.map(cat => {
          const count = FAQ_DATA.filter(i => i.category === cat).length
          return (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              style={{
                padding: '0.3rem 0.7rem',
                background: activeCategory === cat ? 'var(--accent-violet)' : 'transparent',
                border: '1px solid var(--border)',
                borderRadius: '999px',
                color: activeCategory === cat ? 'white' : 'var(--text-secondary)',
                fontSize: '0.7rem',
                cursor: 'pointer',
              }}
            >
              {cat} ({count})
            </button>
          )
        })}
      </div>

      {/* Note importante */}
      <div style={{
        background: 'rgba(255, 200, 50, 0.06)',
        border: '1px solid rgba(255, 200, 50, 0.2)',
        borderRadius: 'var(--radius-md)',
        padding: '0.7rem 0.95rem',
        marginBottom: '1rem',
        fontSize: '0.72rem',
        lineHeight: 1.55,
        color: 'var(--text-secondary)',
      }}>
        <strong>⚠️ Rappel important.</strong> Syléa.AI souscrit à une <strong>obligation de moyens</strong> et non de
        résultat. Les analyses produites par l'IA constituent une aide à la décision et ne sauraient se substituer à un
        avis professionnel qualifié (médical, juridique, financier, psychologique). Pour les situations d'urgence,
        contactez les services compétents : <strong>15 (SAMU)</strong>, <strong>112 (urgences UE)</strong>,
        <strong> 3114 (prévention suicide)</strong>.
      </div>

      {/* FAQ items */}
      {filtered.length === 0 ? (
        <p style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.78rem', padding: '2rem' }}>
          Aucun résultat. Reformulez votre recherche ou contactez sylea.ai.assistance@gmail.com.
        </p>
      ) : (
        filtered.map((item, i) => (
          <FAQItemComponent key={i} item={item} />
        ))
      )}

      {/* Contact direct */}
      <div style={{
        marginTop: '2rem',
        textAlign: 'center',
        padding: '1.2rem',
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)',
      }}>
        <p style={{ fontSize: '0.85rem', fontWeight: 600, margin: '0 0 0.4rem', color: 'var(--text-primary)' }}>
          Votre problème n'est pas listé ?
        </p>
        <p style={{ fontSize: '0.74rem', color: 'var(--text-secondary)', margin: '0 0 0.7rem', lineHeight: 1.5 }}>
          Notre équipe support est joignable par e-mail. Délai de réponse cible : 48 heures ouvrées.
        </p>
        <a
          href="mailto:sylea.ai.assistance@gmail.com"
          style={{
            display: 'inline-block',
            padding: '0.5rem 1.1rem',
            background: 'var(--accent-violet)',
            color: 'white',
            textDecoration: 'none',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.75rem',
            fontWeight: 500,
          }}
        >
          ✉ sylea.ai.assistance@gmail.com
        </a>
      </div>

      <div style={{ textAlign: 'center', marginTop: '1.25rem' }}>
        <Link to="/" style={{ color: 'var(--text-muted)', fontSize: '0.72rem', textDecoration: 'none' }}>
          ← Retour à l'accueil
        </Link>
      </div>
    </div>
  )
}

export { SupportPage }
