#!/usr/bin/env bash
# pg_backup.sh — Backup PostgreSQL avec upload S3 chiffré.
#
# Usage : ./scripts/pg_backup.sh [basebackup|dump|wal]
#
# - basebackup : pg_basebackup complet (à lancer 1×/jour, retention 30j)
# - dump       : pg_dump format custom (sauvegarde logique, restore granulaire)
# - wal        : archive le WAL courant (continuous, < 1 min)
#
# Variables d'env requises :
#   DATABASE_URL=postgresql://user:pass@host:5432/sylea
#   S3_BACKUP_BUCKET=s3://sylea-backups
#   AWS_REGION=eu-west-3
#   SYLEA_BACKUP_GPG_RECIPIENT=backup@sylea.ai  (clé GPG publique pour chiffrement)
#
# À lancer depuis un cron / scheduler GitHub Actions / etc.

set -euo pipefail

MODE="${1:-basebackup}"
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOCAL_DIR="/tmp/sylea-backup-$TIMESTAMP"
mkdir -p "$LOCAL_DIR"

cleanup() {
  rm -rf "$LOCAL_DIR"
}
trap cleanup EXIT

require() {
  if [[ -z "${!1:-}" ]]; then
    echo "ERROR: env var $1 manquante" >&2
    exit 1
  fi
}

require DATABASE_URL
require S3_BACKUP_BUCKET

# ──────────────────────────────────────────────────────────────────────────────

basebackup() {
  echo "[backup] basebackup → $LOCAL_DIR"
  pg_basebackup \
    -D "$LOCAL_DIR/basebackup" \
    -h "$(echo "$DATABASE_URL" | sed -E 's|.*@([^:/]+).*|\1|')" \
    -U "$(echo "$DATABASE_URL" | sed -E 's|.*://([^:]+):.*|\1|')" \
    --format=tar \
    --gzip \
    --progress \
    --verbose \
    --wal-method=stream

  encrypt_and_upload "$LOCAL_DIR/basebackup" "basebackup/sylea-$TIMESTAMP"
}

dump() {
  echo "[backup] pg_dump → $LOCAL_DIR/sylea.dump"
  pg_dump "$DATABASE_URL" \
    --format=custom \
    --compress=9 \
    --file="$LOCAL_DIR/sylea.dump"

  encrypt_and_upload "$LOCAL_DIR/sylea.dump" "dump/sylea-$TIMESTAMP.dump"
}

wal_archive() {
  # Appelé par PostgreSQL via archive_command typiquement.
  # Ici : archive le WAL le plus récent qui n'a pas encore été uploadé.
  WAL_FILE="${2:-}"
  WAL_PATH="${3:-}"
  if [[ -z "$WAL_FILE" || -z "$WAL_PATH" ]]; then
    echo "Usage: archive_command 'pg_backup.sh wal %f %p'" >&2
    exit 1
  fi
  encrypt_and_upload "$WAL_PATH" "wal/$WAL_FILE"
}

encrypt_and_upload() {
  local src="$1"
  local dst_key="$2"

  if [[ -n "${SYLEA_BACKUP_GPG_RECIPIENT:-}" ]]; then
    echo "[backup] GPG encrypt → $src.gpg"
    if [[ -d "$src" ]]; then
      tar -czf "$src.tar.gz" -C "$(dirname "$src")" "$(basename "$src")"
      src="$src.tar.gz"
    fi
    gpg --batch --yes --trust-model always \
        --recipient "$SYLEA_BACKUP_GPG_RECIPIENT" \
        --encrypt --output "$src.gpg" "$src"
    src="$src.gpg"
    dst_key="$dst_key.gpg"
  else
    echo "[backup] WARN: pas de SYLEA_BACKUP_GPG_RECIPIENT — upload non chiffré (à éviter en prod)"
    if [[ -d "$src" ]]; then
      tar -czf "$src.tar.gz" -C "$(dirname "$src")" "$(basename "$src")"
      src="$src.tar.gz"
      dst_key="$dst_key.tar.gz"
    fi
  fi

  echo "[backup] aws s3 cp → $S3_BACKUP_BUCKET/$dst_key"
  aws s3 cp "$src" "$S3_BACKUP_BUCKET/$dst_key" \
    --storage-class STANDARD_IA \
    --metadata "backup_timestamp=$TIMESTAMP,backup_mode=$MODE"

  # WORM : marquer comme immutable pour 90 jours
  # (S3 Object Lock doit être activé sur le bucket)
  if [[ "${SYLEA_BACKUP_WORM:-}" == "true" ]]; then
    aws s3api put-object-retention \
      --bucket "$(echo "$S3_BACKUP_BUCKET" | sed 's|s3://||')" \
      --key "$dst_key" \
      --retention '{"Mode":"COMPLIANCE","RetainUntilDate":"'$(date -u -d "+90 days" +%Y-%m-%dT%H:%M:%SZ)'"}'
  fi
}

cleanup_old_backups() {
  # Garde 30 derniers basebackups + 90 derniers dumps + 14 jours de WAL
  echo "[backup] cleanup old backups (basebackup > 30j, dump > 90j, WAL > 14j)"
  # NOTE : avec Object Lock COMPLIANCE, on ne peut PAS supprimer.
  # Utiliser S3 Lifecycle Policy plutôt pour automatiser la rotation.
  aws s3 ls "$S3_BACKUP_BUCKET/basebackup/" \
    | awk '{print $4}' \
    | sort -r \
    | tail -n +31 \
    | while read -r key; do
        echo "  Removing $key"
        aws s3 rm "$S3_BACKUP_BUCKET/basebackup/$key" || true
      done
}

# ──────────────────────────────────────────────────────────────────────────────

case "$MODE" in
  basebackup)
    basebackup
    cleanup_old_backups
    ;;
  dump)
    dump
    ;;
  wal)
    wal_archive "$@"
    ;;
  *)
    echo "Usage: $0 {basebackup|dump|wal}" >&2
    exit 1
    ;;
esac

echo "[backup] DONE ($MODE) in $LOCAL_DIR"
