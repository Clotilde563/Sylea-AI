# Audit QA pré-commercialisation — Sylea.AI Web App

**Date** : 2026-05-07
**Périmètre** : pages Statistiques, Dashboard, Historique + cohérence cross-pages
**Méthode** : tests unitaires Vitest + inspection navigateur live + comparaison API/UI

---

## Résumé exécutif

| Catégorie | Niveau | Statut | Action requise |
|---|---|---|---|
| Logique des graphs (Chart 1 + Chart 2) | ✅ Validée | 24/24 tests passent | Aucune (déjà fixée) |
| Cohérence chiffres cards/graphs | ⚠️ Incohérence | Bug trouvé | À corriger avant commercial |
| Données historiques (snapshots) | 🔴 Critique | Système-wide | À corriger backend |
| Affichage Dashboard SO | ⚠️ Ambigu | UX confus | À reformuler |
| Page Historique | ⚠️ Vide | Zéros partout | À corriger ou retirer |

---

## ✅ Phase 1 — Tests automatiques chart logic (24/24 verts)

**Fichier** : `frontend/src/__tests__/statsBuild.test.ts`
**Module testé** : `frontend/src/utils/statsBuild.ts` (extrait de StatistiquesPage.tsx)

### `buildHistoricalPoints` (Chart 2 — courbe rouge)
- ✓ Cas dégénérés : profil null, pas de décisions, temps_initial=0
- ✓ Cas normal : snapshots valides → courbe step
- ✓ **Stale snapshots tous=0** + progression>0 → distribution linéaire (le bug Sprint 4)
- ✓ Snapshots scalables (last>0, mismatch) → scaling proportionnel
- ✓ Snapshots non-stale (last == current) → kept as-is
- ✓ **Invariant QA critique** : point final = `progressionActuelle` (matche carte PROGRESSION)
- ✓ Monotonicité elapsedMs
- ✓ Clamping [0, 100]
- ✓ Décisions hors fenêtre (avant `objectif_modifie_le`) → ignorées

### `buildSOTimelines` (Chart 1 — sous-objectifs)
- ✓ Pas de SO → vide
- ✓ SO sans décision → ligne plate de 0 à `currentProg`
- ✓ Match par UUID (`sous_objectif_id`)
- ✓ Match par titre (`sous_objectif_impacte`) en fallback
- ✓ Décision sans soId/titre → ignorée
- ✓ Décision avec soId inconnu → ignorée
- ✓ Scaling vers progression actuelle
- ✓ **Invariant QA critique** : point final = `currentProg` du SO
- ✓ Clamping [0, 100], monotonicité

### `interpolateProb`
- ✓ Tableau vide → 0
- ✓ Comportement palier (step), pas linéaire
- ✓ Avant/sur/après chaque point

---

## 🔴 Phase 2 — Incohérences trouvées (audit live)

### CRITIQUE 1 : `probabilite_actuelle` ≠ `progression`

```
profil.probabilite_actuelle      = 24.05
calc (temps_gagne / temps_init)  = 33.33%
écart                            = 9.3 points (38% relatif)
```

**Impact utilisateur** : selon la page, le client voit **2 chiffres différents** pour la même notion :
- Dashboard / Statistiques cards : 33.3%
- Si `probabilite_actuelle` est exposé ailleurs : 24.05

**Cause probable** :
- `probabilite_actuelle` = probabilité IA (formule deterministe avec readiness × neuro_factor × ...)
- `progression` = simple % de temps gagné

**Action requise** :
- ⚠️ Soit unifier les deux (recalculer `probabilite_actuelle` = progression)
- ⚠️ Soit clarifier visuellement les deux notions (label "PROBABILITÉ IA" vs "PROGRESSION TEMPS")

### CRITIQUE 2 : Tous les SO ont exactement 33.3%

```json
[
  { "titre": "Fondations et Apprentissage Structuré",     "progression": 33.3 },
  { "titre": "Portfolio et Compétences Avancées",         "progression": 33.3 },
  { "titre": "Lancement Freelance et Premier Réseau",     "progression": 33.3 },
  { "titre": "Croissance et Consolidation vers 3000€/mois","progression": 33.3 }
]
```

**Suspect** : 4 SO différents avec progression IDENTIQUE = calcul partagé/global ?

**Sum impact_sous_objectif des 20 décisions** = 29.5 → distribué sur les SO.
Mais résultat = 33.3% pour TOUS les 4 SO. Improbable que les 4 aient progressé exactement pareil.

**Action** : vérifier le backend `update_progression_so` — soit propage la progression globale uniformément, soit les impacts sont mal attribués.

### CRITIQUE 3 : Snapshots `temps_gagne_avant/apres` = 0 sur toutes les décisions

```
20 décisions / 20 ont tg_avant=0, tg_apres=0
profil.temps_gagne_jours = 652 (correct)
→ DB désynchronisée
```

**Conséquence** : Chart 2 sans le fix Sprint 4 = ligne plate puis saut. **Le fix masque le symptôme mais le problème de fond reste**.

**Action** : 
1. Identifier pourquoi les nouveaux snapshots ne sont pas stockés (backend bug ?)
2. Migration de backfill pour les anciennes décisions
3. Test : créer une nouvelle décision, vérifier que tg_avant/apres sont remplis

### MAJEUR 4 : Dashboard SO display "X / Y" ambigu

```
Affichage : "Fondations et Apprentissage Structuré [À PRIORISER] 1a 2m / 1a 10m"
              barre ~33% remplie
```

L'utilisateur ne sait pas si :
- "1a 2m" = temps déjà fait, "1a 10m" = total → 64% fait (mais barre ~33%)
- "1a 2m" = temps restant, "1a 10m" = total → 36% fait (barre ~33% — **c'est le cas réel**)

**Action UX** : ajouter un label explicite, ex : `"⏱ Reste 1a 2m sur 1a 10m"` ou `"7m gagnés / 1a 10m total"`.

### MAJEUR 5 : Historique affiche "0j → 0j" partout

Conséquence directe de CRITIQUE 3. Toutes les lignes de l'historique montrent `0j → 0j` → utilisateur croit qu'aucune décision n'a eu d'impact.

**Action** : lier au fix CRITIQUE 3 (re-population des snapshots).

---

## 🟡 Observations mineures

### Page Historique : cards stats vides
La page n'affiche aucune card de stats agrégées (somme impact_net, par type, etc.). Le composant `decision_rows_count` retourne 0 alors que 20 décisions existent — pas de selecteur CSS pour les rangées de décisions.

### Couverture i18n
Plusieurs strings UI sont en français hardcodés (e.g., "À PRIORISER" via `t('dashboard.sous_objectifs')` mais d'autres en dur). Risque de traduction incomplète si on lance en EN/ES.

### `probabilite_actuelle` dans le profil = 24.05
Ce chiffre est calculé par `MoteurProbabilite` mais ne semble pas affiché clairement à l'utilisateur. Soit on le retire, soit on lui donne sa propre carte avec explication.

---

## Recommandations avant commercialisation

### 🔴 Bloquants (à fixer avant lancement)

1. **Unifier `probabilite_actuelle` et `progression`** — choisir UN seul chiffre canonique pour "où en est-on de l'objectif". Renommer si nécessaire (ex: `progression_temps_pct`).

2. **Investiguer le calcul `progression` des SO** — pourquoi 4 SO ont exactement 33.3% ? Audit du backend `_update_so_progression()`. Tester en créant une décision qui impacte UN SEUL SO et vérifier que la progression de ce SO change indépendamment.

3. **Backfill snapshots `temps_gagne_avant/apres`** — migration pour ré-écrire l'historique cohérent. Sinon les nouveaux clients verront un graph plat les premiers jours.

### 🟡 Important (à fixer dans la première release)

4. **Reformuler Dashboard SO** : remplacer "1a 2m / 1a 10m" par "1a 2m restant · sur 1a 10m" ou "7m gagnés / 1a 10m total".

5. **Page Historique** : afficher des cards stats globales (total décisions, somme impact, par type, par mois).

### 🟢 Nice-to-have

6. **Tests E2E Playwright** : pour vérifier que les chiffres d'une page = chiffres d'une autre page, sur les principaux scénarios utilisateur.

7. **Audit i18n** : extraire toutes les strings hardcodées dans `i18n/locales/`.

---

## Couverture de tests actuelle

| Module | Tests | Status |
|---|---|---|
| `statsBuild.ts` (Chart 1+2) | 24 | ✅ All passing |
| `duration.ts` (formatJours, buildTimeTicks) | déjà couvert | ✅ |
| `authStore.ts` | déjà couvert | ✅ |
| `hashUtils.ts` | déjà couvert | ✅ |
| Backend (Python) | 105 (multi-suites) | ✅ All passing |
| Rust audio_capture | 20 | ✅ All passing |

**Total tests verts** : 149 (TS + Python + Rust)

---

## Conclusion

L'application est **fonctionnellement solide** côté logique des graphs (24/24 tests). Les bugs trouvés sont principalement liés à la **cohérence de données entre couches** (DB stale, calculs partagés vs distincts, formats d'affichage).

Avant la commercialisation, traiter en priorité les 3 critiques (unification probabilité, progression SO, backfill snapshots).
