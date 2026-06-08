# Disaster Recovery Runbook — Syléa.AI

**Statut** : v1 — 2026-05-18
**Owner** : équipe SRE
**Cadence drill** : semestrielle (Avr, Oct)
**RTO cible** : 1h
**RPO cible** : 5 min

---

## 0. Scénarios couverts

| # | Scénario | Probabilité | Impact | Procédure |
|---|----------|-------------|--------|-----------|
| 1 | Corruption DB PostgreSQL (DROP TABLE accidentel, bug applicatif) | Moyenne | Catastrophique | §3 |
| 2 | Perte région cloud principale (eu-west-3 down) | Faible | Catastrophique | §4 |
| 3 | Suppression de données par bug applicatif (ex. migration buggy) | Faible | Élevé | §3 (PITR) |
| 4 | Compromission de comptes admin (data exfiltration) | Faible | Catastrophique | §5 |
| 5 | Ransomware sur l'hébergeur | Très faible | Catastrophique | §4 + §6 |
| 6 | Perte clés de chiffrement (Vault inaccessible) | Très faible | Catastrophique | §7 |
| 7 | Attaque DDoS prolongée | Moyenne | Élevé | §8 |
| 8 | Indisponibilité Anthropic API | Élevée | Moyen | §9 |

---

## 1. Pré-requis (à vérifier mensuellement)

- [ ] Backups automatisés PostgreSQL actifs (pg_basebackup + WAL archiving)
- [ ] Backups répliqués vers une **2e région** et un **2e fournisseur** (S3 + Backblaze)
- [ ] Backups chiffrés (cleartext interdit) avec clés séparées de la prod
- [ ] WAL archiving avec rotation < 1 min
- [ ] Documentation du schéma DB à jour (`alembic stamp head`)
- [ ] Accès admin AWS/GCP via 2FA TOTP + audit log activé
- [ ] Clés Vault sauvegardées dans coffre-fort physique (3 fragments Shamir)
- [ ] Runbook testé lors du dernier drill (date : ____________)

---

## 2. Contacts d'urgence

| Rôle | Personne | Téléphone | Email |
|------|----------|-----------|-------|
| On-call SRE primaire | _____ | _____ | _____ |
| On-call SRE backup | _____ | _____ | _____ |
| CTO | _____ | _____ | _____ |
| DPO (data breach RGPD) | _____ | _____ | _____ |
| Counsel juridique | _____ | _____ | _____ |
| Support Anthropic | n/a | n/a | https://support.anthropic.com |
| Support hébergeur (Railway/Render/...) | _____ | _____ | _____ |

---

## 3. Restoration PostgreSQL via PITR

### 3.1 Décision

```
              [Détection incident]
                       │
                       ▼
        ┌──── Est-ce qu'on perd des données récentes ? ────┐
        │ OUI (DROP, UPDATE buggy)        NON (corruption) │
        ▼                                          ▼
  PITR vers t-5min                       Restore dernier basebackup
  (commande §3.3)                        (commande §3.4)
```

### 3.2 Pré-restore : geler la prod

```bash
# 1. Mettre l'API en maintenance mode (banner frontend)
curl -X POST $ADMIN_URL/api/admin/maintenance \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -d '{"enabled": true, "message": "Maintenance d urgence - DB restore"}'

# 2. Arrêter tous les workers (canary 0% sur le déploiement)
# (commande dépendante de l'hôte : Cloud Run, K8s, etc.)

# 3. Snapshot de l'état actuel AVANT toute modification (pour forensics)
pg_dump $DATABASE_URL --format=custom --file=/backups/pre-restore-$(date +%s).dump
```

### 3.3 Point-in-Time Recovery

```bash
# Cible : restaurer à t-5min, juste avant l'incident.
# Pré-requis : WAL archiving doit être actif (sinon impossible).

export RESTORE_TARGET_TIME="2026-05-18 14:55:00 UTC"

# 1. Provisionner une nouvelle instance PG vierge
# (sur AWS RDS, Cloud SQL, Crunchy, ou pg_basebackup local)

# 2. Restaurer le basebackup le plus récent ANTÉRIEUR à RESTORE_TARGET_TIME
aws s3 cp s3://sylea-backups/basebackup/latest.tar.gz - | \
  tar -xz -C /var/lib/postgresql/restore/

# 3. Configurer recovery.signal + recovery target
cat > /var/lib/postgresql/restore/recovery.signal <<EOF
# présence du fichier = mode recovery
EOF

cat >> /var/lib/postgresql/restore/postgresql.auto.conf <<EOF
restore_command = 'aws s3 cp s3://sylea-backups/wal/%f %p'
recovery_target_time = '$RESTORE_TARGET_TIME'
recovery_target_action = 'pause'
EOF

# 4. Démarrer PG en mode recovery
pg_ctl -D /var/lib/postgresql/restore start

# 5. Vérifier que la cible est atteinte
psql -d sylea -c "SELECT pg_is_in_recovery();"  # true
psql -d sylea -c "SELECT now(), pg_last_wal_replay_lsn();"

# 6. Valider sur quelques tables critiques
psql -d sylea -c "SELECT count(*) FROM users WHERE created_at < '$RESTORE_TARGET_TIME';"
psql -d sylea -c "SELECT max(created_at) FROM events;"

# 7. Promouvoir en cas de validation OK
psql -d sylea -c "SELECT pg_promote();"
```

### 3.4 Restore basebackup simple (sans PITR)

```bash
# Si corruption uniquement (pas de besoin de remonter dans le temps)
pg_restore --clean --if-exists --no-owner \
           --dbname=$DATABASE_URL_NEW \
           /backups/sylea-2026-05-18.dump
```

### 3.5 Bascule trafic vers la DB restaurée

```bash
# 1. Mettre à jour DATABASE_URL dans Vault / Secrets Manager
vault kv put secret/sylea/prod DATABASE_URL="postgresql://..." # nouvelle URL

# 2. Forcer le rechargement des secrets (TTL cache 5 min ou redémarrage)
curl -X POST $ADMIN_URL/api/admin/reload-secrets -H "Authorization: ..."

# 3. Redémarrer les workers progressivement (canary 10% → 50% → 100%)

# 4. Sortir du mode maintenance
curl -X POST $ADMIN_URL/api/admin/maintenance \
     -d '{"enabled": false}'

# 5. Monitorer Sentry + Grafana pendant 30 min
```

### 3.6 Post-restore (obligatoire)

- [ ] Notifier les utilisateurs des données potentiellement perdues
  (transactions entre t-5min et incident)
- [ ] Si > 5 utilisateurs touchés ET données personnelles → **déclaration CNIL <72h**
  (RGPD art. 33). Voir `docs/RGPD_INCIDENT.md`.
- [ ] Post-mortem rédigé dans 5 jours ouvrés (template `docs/postmortems/`)
- [ ] Ticket pour la cause racine + action items
- [ ] Vérifier l'intégrité du basebackup utilisé pour le restore

---

## 4. Bascule multi-région

**Pré-requis** : instance secondaire répliquée (streaming replication ou
logical replication) tournant en eu-central-1 ou us-east-1.

```bash
# 1. Promouvoir la replica en primary
psql -h replica.eu-central-1.sylea.ai -c "SELECT pg_promote();"

# 2. Mettre à jour le DNS (TTL < 60s sur le record principal)
# Cloudflare API ou AWS Route 53 :
aws route53 change-resource-record-sets ...

# 3. Mettre à jour DATABASE_URL pour pointer sur la nouvelle primary
# (via Secrets Manager / Vault)

# 4. Rediriger le trafic applicatif (déjà fait via DNS)

# 5. Vérifier : connections, health checks, alerts
```

**RTO mesuré** : ~10 minutes si la replica est à jour.
**RPO** : selon le lag de réplication (cible < 5s).

---

## 5. Compromission compte admin

```bash
# 1. Révoquer tokens admin compromis
psql -c "DELETE FROM tokens WHERE user_id = '...' AND scope = 'admin';"

# 2. Forcer la déconnexion de TOUTES les sessions admin
psql -c "UPDATE users SET force_logout_after = now() WHERE is_admin = true;"

# 3. Rotation IMMÉDIATE de tous les secrets sensibles :
#    - JWT_SECRET_KEY  (invalide TOUS les tokens utilisateurs)
#    - DATABASE password
#    - Anthropic API key (révoquer + créer nouvelle)
#    - Stripe webhook secret
#    - Fernet master key (re-chiffrement nécessaire — gros effort)

# 4. Audit log : exporter qui a fait quoi avec le compte compromis
psql -c "SELECT * FROM audit_log
         WHERE actor_user_id = '...'
         AND ts > now() - interval '7 days'
         ORDER BY ts;" > /tmp/audit-incident-$(date +%s).csv

# 5. Notifier DPO + Counsel pour déclaration RGPD si data breach
```

---

## 6. Restore "from scratch" (cas ransomware)

```bash
# Pré-requis : backups WORM (immuables) — S3 Object Lock activé.

# 1. Provisionner une infra NEUVE chez un AUTRE fournisseur
#    (ex. backup AWS → restore sur Hetzner / GCP)
#    → empêche la propagation de l'attaque sur la nouvelle infra.

# 2. Restaurer depuis les backups Object Lock immuables
aws s3 cp s3://sylea-backups-worm/basebackup/latest.tar.gz - \
  | tar -xz -C /var/lib/postgresql/

# 3. Régénérer toutes les clés (Vault, JWT, Fernet)
#    car l'attaquant a peut-être exfiltré les précédentes.

# 4. Re-déployer les apps depuis un commit Git VÉRIFIÉ signed
#    (vérifier les signatures GPG des derniers commits).

# 5. Communication client : email personnalisé, RGPD notification.
```

---

## 7. Perte clés de chiffrement Fernet / Vault

Les données chiffrées par cette clé sont **irrécupérables** sans elle.
D'où l'importance des sauvegardes Shamir Secret Sharing.

```bash
# 1. Reconstruire la clé depuis les fragments Shamir (3 sur 5)
ssss-combine -t 3 < fragments.txt > recovered_key.txt

# 2. Charger dans Vault / Secrets Manager
vault kv put secret/sylea/prod SYLEA_CREDENTIALS_MASTER_KEY=$(cat recovered_key.txt)

# 3. Restart applicatif pour relire la clé
```

Si TOUS les fragments sont perdus → données chiffrées (TOTP secrets, OAuth
tokens, credentials vault) **définitivement perdues**. Les users doivent
re-configurer leur 2FA / re-connecter leurs intégrations.

---

## 8. DDoS prolongé

```bash
# 1. Activer "Under Attack mode" sur Cloudflare (JS challenge)
# 2. Activer rate-limit IP strict via env var :
export SYLEA_IP_RATELIMIT_CAPACITY=5      # 5 req burst seulement
export SYLEA_IP_RATELIMIT_REFILL=0.05     # 1 req / 20s

# 3. Si l'IP du serveur d'origine est exposée → activer Cloudflare Tunnel
cloudflared tunnel route dns sylea-api api.sylea.ai

# 4. Bloquer ASNs sources via Cloudflare WAF custom rule

# 5. Communication status page : "Issues d'accessibilité partielle"
```

---

## 9. Anthropic API indisponible

```bash
# 1. Activer le kill switch via feature flag
# Éditer config/feature_flags.yaml :
#   anthropic_disabled: { default: "on" }
# Puis git push + reload

# 2. (Optionnel) Activer fallback OpenAI GPT-4o
export SYLEA_LLM_FALLBACK_PROVIDER=openai
export OPENAI_API_KEY=...

# 3. Communication users via banner frontend
#    + status page (statuspage.io / instatus)

# 4. Surveiller https://status.anthropic.com pour mise à jour
```

---

## 10. Drill semestriel (procédure de test)

À exécuter **2× par an** (avril + octobre). Documenté dans `docs/postmortems/dr-drill-YYYY-MM.md`.

### Étapes du drill

1. **Pre-drill** (J-7)
   - Annoncer le drill à l'équipe (date, durée, scénario)
   - Vérifier que tous les contacts d'urgence sont joignables
   - S'assurer qu'aucun déploiement majeur n'est planifié

2. **Drill** (J)
   - 09h00 : Bascule prod vers une infra de drill (DNS swap)
   - 09h05 : Simuler un incident (ex. `DROP DATABASE sylea` sur la copie)
   - 09h10 : Suivre le runbook §3 pour restore
   - **Mesurer** :
     - Temps détection → bascule maintenance mode
     - Temps début restore → fin restore
     - Temps fin restore → utilisateurs reconnectés
   - 11h00 : Bascule retour prod normale

3. **Post-drill** (J+5)
   - Post-mortem rédigé
   - RTO mesuré vs cible (1h) → quelle marge ?
   - RPO mesuré vs cible (5 min) → quelle marge ?
   - Actions correctives identifiées + tickets créés
   - Mise à jour du runbook si nouvelles leçons

---

## 11. Métriques à monitorer en continu

| Métrique | Seuil alerte | Outil |
|----------|--------------|-------|
| Lag streaming replication | > 30s | Prometheus |
| Backups WAL up-to-date | > 5 min lag | Prometheus |
| Dernier basebackup réussi | > 24h | Prometheus + PagerDuty |
| Taille DB / disque libre | > 80% | Grafana |
| Erreurs Sentry rate | > 50/min | Sentry + PagerDuty |
| Latence p99 `/api/*` | > 2s | Datadog APM |
| Disponibilité (uptime) | < 99.9% (mensuel) | Statuspage + Checkly |

---

## Annexe — Commandes utiles

```bash
# État du WAL archiving
psql -c "SELECT * FROM pg_stat_archiver;"

# Liste des basebackups disponibles
aws s3 ls s3://sylea-backups/basebackup/

# Vérifier intégrité d'un basebackup
pg_verifybackup /backups/sylea-2026-05-18

# Lister les replicas connectées
psql -c "SELECT client_addr, state, write_lag, flush_lag FROM pg_stat_replication;"

# Forcer un basebackup manuel (avant un déploiement risqué)
pg_basebackup -D /backups/manual-$(date +%s) -Ft -z -P
```
