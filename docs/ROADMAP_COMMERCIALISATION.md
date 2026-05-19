# Roadmap commercialisation Syléa.AI

**Objectif** : transformer Syléa d'un produit techniquement solide en une
**plateforme dont l'utilisateur ne peut plus se passer** (DAU/MAU > 50%,
rétention D30 > 40%, churn mensuel < 5%).

Ce document est volontairement orienté **rétention / engagement**, pas
features. Une feature ne crée pas l'addiction, le *hook loop* le fait.

---

## 1. Modèle d'addiction — Hook Model (Nir Eyal)

```
        ┌─────────────────────────────────────────┐
        │                                         │
        ▼                                         │
   [TRIGGER]  →  [ACTION]  →  [VARIABLE REWARD]  →  [INVESTMENT]
   (interne /     (effort       (gain inattendu      (l'user ajoute
    externe)      minimum)       qui crée le         de la valeur,
                                 manque la fois      remplit le
                                 suivante)           graphe perso)
```

Pour chaque touchpoint utilisateur, on doit vérifier ces 4 étages.

### Application à Syléa

| Étage | Implémentation actuelle | Ce qu'il faut ajouter |
|-------|-------------------------|------------------------|
| **Trigger externe** | Email + Web Push existants | Notifications push intelligentes (horaire optimisé/user), SMS premium, rappels intelligents Agent 1 |
| **Trigger interne** | "Doute sur un choix" → ouvre l'app | "Je n'avance plus" → notification "Que faire ?" / "Sentiment de vide" → message Agent 1 |
| **Action** | Analyser un choix (5 min), bilan (3 min) | Réduire à <30s : "1 tap = bilan rapide", "swipe = mini-dilemme" |
| **Variable reward** | Probabilité change après chaque action | **Effet de surprise** : variations imprévisibles (bonus aléatoire, milestone surprise, message Agent 1 inattendu) |
| **Investment** | Sous-objectifs, historique de décisions | Graphique personnel qui se remplit, mémoire Agent 1 qui s'enrichit, badges/trophées, streak |

---

## 2. Les 7 leviers d'engagement à implémenter

### 2.1 Streaks (séries de jours consécutifs) 🔥

**Pourquoi** : Duolingo a multiplié sa rétention D7 par 3 avec les streaks.
Un user qui a 47 jours d'affilée perd PLUS de valeur en interrompant que ce qu'il
gagnait à chaque jour individuel → loss aversion (Kahneman).

**Implémentation** :
- Compteur `streak_days` en DB (incrémenté sur 1 action significative/jour)
- Badge visuel proéminent sur le Dashboard : "🔥 12 jours"
- Notification PRE-perte : "Tu vas perdre ta série de 47 jours dans 4h"
- **Streak freeze** payant (Sylea Avancé) : 1 jour "pause" gratuit / mois
- Animation spéciale à 7/30/100/365 jours

**Effort** : 1 semaine. **Impact rétention D30** : +15-25%.

### 2.2 Daily Mission / Quête du jour ✦

**Pourquoi** : "Et maintenant, qu'est-ce que je fais ?" est le tueur silencieux
des SaaS. Une quête claire vide le doute et donne un point de retour journalier.

**Implémentation** :
- Au login (ou push notif 9h), banner : "**Ta mission du jour** : enregistrer
  un événement positif". Tap → l'action s'ouvre pré-remplie.
- Variété : analyses, bilans, messages Agent 1, micro-tasks.
- **Récompense fixe** : +1% probabilité bonus + XP. **Variable** : 1 fois sur 10,
  bonus 5×.
- Voir `frontend/src/components/DailyMission.tsx` (à créer).

**Effort** : 2 semaines. **Impact DAU** : +30-40%.

### 2.3 XP + niveaux + déblocages progressifs 🎮

**Pourquoi** : Donne une métrique de progression long-terme, indépendante
de l'objectif de vie de l'utilisateur. "Je veux atteindre le niveau 10".

**Implémentation** :
- `users.xp_total`, `users.current_level`
- XP gagné à chaque action (10 XP analyse, 5 XP bilan, 2 XP message)
- Niveaux 1-50 avec progression géométrique
- Déblocages à chaque niveau : nouveau template d'objectif, nouveau ton
  Agent 1, nouvelle palette de couleurs, accès à un mini-jeu, etc.
- Page dédiée `/progression` avec barre de progression visuelle.

**Effort** : 1.5 semaine. **Impact LTV** : +20%.

### 2.4 Badges + Achievements 🏆

**Pourquoi** : "Collectionite" innée + preuve sociale exportable (partager
ses badges sur LinkedIn/X devient un vecteur d'acquisition gratuit).

**Catalogue minimum (30 badges)** :
- **Démarrage** : Premier profil, 1er objectif, 1er bilan, 1ère analyse
- **Persistance** : 7j streak, 30j streak, 100j streak, 365j streak
- **Maître de la décision** : 10 dilemmes, 100, 1000
- **Bien-être** : 7 bilans positifs d'affilée, score moyen > 8/10 sur 30j
- **Découverte** : Premier coaching, premier export, premier partage
- **Secret** : déclenchés par actions inattendues (encourage exploration)

**Effort** : 2 semaines (design + logique). **Effet viral** : badge partageable
= +5-10% acquisition organique.

### 2.5 Notifications push intelligentes (pas spam) 🔔

**Règles strictes** :
- **JAMAIS** > 1 notification / jour (sauf urgence réelle)
- Timing **personnalisé** : on push à l'heure où l'utilisateur ouvre
  habituellement l'app (Machine Learning simple : moyenne des
  timestamps de session)
- Contenu **contextualisé** : pas "Reviens sur Syléa", mais
  "**Lucas**, tu as un dilemme en attente depuis 3 jours. 5 min suffisent."
- **Triggers émotionnels** spécifiques :
  - Anniversaire deadline : "Plus que 30 jours pour atteindre ton objectif"
  - Pic positif : "Tu n'as jamais eu un bien-être aussi haut. On célèbre ?"
  - Pic négatif : "Tu as eu une semaine difficile. Veux-tu parler à Syléa ?"
  - Milestone : "Tu viens de passer la barre des 30% de progression"

**Effort** : 2 semaines (ML scheduler + 30 templates de notifs). **Impact
DAU** : +25%.

### 2.6 Mémoire long terme Agent 1 (effet "il me connaît") 💭

**Pourquoi** : Plus l'utilisateur sent que l'agent le connaît, plus il revient.
Cf. Replika qui a 30M+ utilisateurs simplement parce que leur IA "se souvient".

**Implémentation** :
- Mémoire sémantique déjà présente (pgvector / fallback LIKE)
- À ajouter : extraction proactive de **traits de personnalité** au fil des
  conversations ("Lucas aime le ski, déteste les réunions, est plus
  productif le matin").
- L'Agent 1 référence ces traits subtilement dans ses messages.
- Page **"Ce que Syléa sait de moi"** : transparence + édition.
- Effet recherché : "Si je quitte Syléa, je perds tout ce contexte → trop
  cher de partir."

**Effort** : 3 semaines (extraction + storage + display + UX édition).
**Impact churn** : -30% (le "switching cost" devient psychologique, pas
juste fonctionnel).

### 2.7 Variable reward — Bonus aléatoires 🎲

**Pourquoi** : Le **schedule variable** est la base de toute mécanique
addictive (slot machines, dopamine prediction error). Si la récompense est
prévisible, le cerveau s'habitue. Si elle varie de façon imprévisible, il
relance pour vérifier.

**Implémentations subtiles, non malsaines** :
- À la complétion d'une tâche : 1 fois sur 10, **double XP** + animation
- Quête du jour : 1 fois sur 20, récompense **trésor caché** (badge rare,
  message exclusif Agent 1, feature unlocked)
- Sur les bilans : 1 fois sur 30, un **insight** profond généré par Claude
  ("J'ai remarqué que tes scores chutent toujours le mardi — coïncidence ?")

**Effort** : 1 semaine. **Impact session_count_per_day** : +40%.

---

## 3. Onboarding 5-star (Time-to-First-Value < 90s)

**Statistiques industrie** : 75% des nouveaux users abandonnent dans les
24h. La cause #1 : pas de "Aha! moment" rapide.

### Le **premier choix analysé** doit arriver < 90 secondes après le login.

Aujourd'hui : login → wizard 3 étapes (10 min) → dashboard vide → user perdu.

**Refonte proposée** :

1. **0-10s** : Login (déjà rapide) → page d'accueil avec **animation Syléa
   en pleine page** + un seul champ : "Tape ici la décision qui te tracasse
   en ce moment"
2. **10-30s** : User tape "Quitter mon job ou pas". L'IA répond IMMÉDIATEMENT
   avec une mini-analyse même sans profil ("D'accord, voyons les deux côtés...").
   **C'est le "Aha! moment".**
3. **30-90s** : Après cette première interaction, l'app propose en *soft sell* :
   "Pour que mes analyses soient encore plus précises, dis-moi rapidement
   qui tu es" → wizard simplifié à 3 questions (nom, âge, objectif principal).
4. **Le wizard détaillé** (compétences, scores, bien-être) devient OPTIONNEL,
   à compléter plus tard via une carte "Améliorer mes analyses (+30%)".

**Effort** : 2 semaines. **Impact activation D1** : +50% (de ~20% à ~30%).

---

## 4. Email lifecycle (drip campaign)

Outil : Customer.io / Mailchimp / Brevo (free tier jusqu'à 2000 contacts).

| Jour | Email | Objectif |
|------|-------|----------|
| D0 | Bienvenue + lien onboarding | Activation |
| D1 (si pas connecté) | "Lucas, ton analyse t'attend" | Retour |
| D3 | Découverte fonctionnalité non-utilisée | Expansion |
| D7 | Recap première semaine + premier badge | Validation |
| D14 | Story client : "Comment Marie a atteint son objectif en 6 mois" | Inspiration |
| D21 | Upsell Syléa Avancé (si free + actif) | Conversion |
| D30 | Bilan personnalisé du mois | Engagement |
| D60 (si churn) | "On te manque" + offre de retour | Reactivation |

**Effort** : 1 semaine (20 templates copywriting + intégration). **Impact
conversion free → paid** : +15%.

---

## 5. Communauté + Social proof

**Effets** :
- Permet à un user de voir que d'autres utilisent Syléa avec succès
- Crée des contributeurs (UGC) qui font la promo gratuitement
- Augmente la rétention par lien social fort (anti-churn)

### Composants à construire

1. **Témoignages dynamiques** sur la landing page + Dashboard
   - Carrousel "Ils ont atteint leur objectif avec Syléa" (avec photos +
     prénoms + verbatims, opt-in)
2. **Stories anonymisées** : "47% des users qui ont ton profil ont atteint
   leur objectif" (Data-driven, anonyme)
3. **Communauté Discord** privée Syléa (gratuit + Avancé) — channel par
   catégorie d'objectif (carrière / santé / créa / etc.)
4. **Programme ambassadeurs** : 10% commission sur les filleuls payants

**Effort** : 3 semaines (modération + intégrations + design). **Impact
acquisition organique** : +30%.

---

## 6. Métriques à monitorer obligatoirement

Après chaque déploiement de feature engagement, suivre dans un dashboard :

| Métrique | Cible "produit healthy" |
|----------|--------------------------|
| **DAU/MAU ratio** | > 30% (Facebook ~70%, Notion ~25%) |
| **D1 retention** | > 50% |
| **D7 retention** | > 30% |
| **D30 retention** | > 20% |
| **Sessions/user/day** | > 1.5 |
| **Avg session duration** | 3-10 min (trop court = pas de valeur, trop long = addiction toxique) |
| **TTFV** (Time to First Value) | < 90s |
| **NPS** | > 40 |
| **Churn mensuel** | < 5% (Avancé), < 8% (free) |
| **LTV / CAC** | > 3 |

Outils : PostHog (open source, free tier 1M events/mois), Mixpanel ou
Amplitude pour les funnels.

---

## 7. Anti-patterns à éviter ABSOLUMENT

L'addiction ≠ engagement positif. La frontière est mince et **éthique**.
Les anti-patterns suivants sont **interdits** chez Syléa :

| À NE PAS faire | Raison |
|----------------|--------|
| Notifications push spam (>3/jour) | Désabonnement OS, désinstallation |
| Streak qui PUNIT vraiment (perte définitive de progression) | Anxiété + perception toxique |
| Limites artificielles "5 messages/jour" pour pousser au payant | Bloque le moment où ils ont le plus besoin |
| Dark patterns (consentement caché, désinscription difficile) | RGPD violation + bad press |
| Mauvaise nouvelle aléatoire pour créer du stress | Mental health risk |
| Comparaison sociale toxique ("Lucas est mieux que toi") | Mental health risk |
| Infinite scroll des conversations Agent 1 | Capte trop de temps sans valeur |

**Manifeste produit** : "Syléa aide à atteindre tes objectifs. Si Syléa te
détourne d'eux, on a échoué."

---

## 8. Roadmap commercialisation — Séquençage 6 mois

### Mois 1-2 — Foundation engagement
- [ ] Onboarding 90s + Aha moment immédiat
- [ ] Streaks + badge UI
- [ ] Push notifications timing intelligent
- [ ] Email drip D0-D30

### Mois 3 — Gamification light
- [ ] Quête du jour
- [ ] XP + niveaux + déblocages
- [ ] Variable rewards (animations bonus)
- [ ] 30 badges initiaux

### Mois 4 — Mémoire & personnalisation
- [ ] Extraction proactive traits utilisateur
- [ ] Page "Ce que Syléa sait de moi"
- [ ] Agent 1 références personnalisées
- [ ] Recommandations contextuelles

### Mois 5 — Communauté
- [ ] Discord communauté
- [ ] Témoignages dynamiques
- [ ] Programme ambassadeurs
- [ ] Stories anonymisées

### Mois 6 — Polish + Launch
- [ ] A/B testing tout (titres, CTAs, copywriting)
- [ ] Mobile app (PWA puis natif)
- [ ] Localisation marketing (DE, ES, EN)
- [ ] Launch Product Hunt + Reddit
- [ ] Press release (TechCrunch, Les Echos, Capital)

---

## 9. Investissement nécessaire

| Poste | Coût mois 1-6 |
|-------|----------------|
| Dev (1 ETP full-stack, 6 mois) | 60 000 € |
| Designer (0.3 ETP, 6 mois) | 12 000 € |
| Outils (PostHog, Customer.io, Mailchimp, Discord boost) | 1 800 € |
| Notifs push (OneSignal, Pusher) | 600 € |
| Marketing initial (ads test budget) | 5 000 € |
| **Total** | **~80 000 €** |

**ROI attendu** : doubler la rétention D30 fait passer le LTV de ~50 € à
~120 €. Sur 1000 users payants, gain LTV = 70 k€. Break-even en ~3 mois
post-déploiement.

---

## 10. Critères "go to market" — Checklist finale

Avant de dépenser 1 € en publicité, ces 12 points doivent être verts :

- [ ] **TTFV** < 90s mesuré sur 100+ users beta
- [ ] **D1 retention** > 50% mesuré sur cohorte de 100+ users
- [ ] **Onboarding completion** > 70%
- [ ] **NPS** > 40 (au moins 30 réponses)
- [ ] **Crash-free sessions** > 99.5% (Sentry)
- [ ] **API p99 latency** < 2s (Datadog/Grafana)
- [ ] **0 critical security vulnerabilities** (pip-audit + npm audit)
- [ ] **Documentation utilisateur complète** (HelpPage + SupportPage)
- [ ] **Procédure DR testée** (drill semestriel passé)
- [ ] **Support email + chatbot fonctionnels**
- [ ] **Pricing page A/B testée** (3 plans, 2 paliers de prix testés)
- [ ] **Backup quotidien + restore drill validé**

**Tant qu'un point est rouge, on ne paye pas Google Ads / Meta Ads.** Sinon
on brûle du budget pour acquérir des users qu'on perd immédiatement.
