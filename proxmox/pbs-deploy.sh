#!/usr/bin/env bash
# Renewal hook for Proxmox Backup Server (PBS).
#
# On every real certbot renewal (invoked via --renew-hook), this script:
#   1. Installs the renewed cert/key into PBS's expected locations
#   2. Reloads proxmox-backup-proxy so it picks up the new cert
#   3. Extracts the new TLS fingerprint via `proxmox-backup-manager cert info`
#   4. Pushes that fingerprint to every PVE node listed in the hosts file,
#      via `pvesm set <storage-id> --fingerprint <fingerprint>` over SSH
#
# Requires: passwordless SSH (key-based) from this host as root to every
# PVE node listed below.

set -euo pipefail

PBS_CERT_DIR="/etc/proxmox-backup"
DEST_CERT="$PBS_CERT_DIR/proxy.pem"
DEST_KEY="$PBS_CERT_DIR/proxy.key"

# List of "hostname storage-id" pairs, one per line. Lines starting with
# '#' and blank lines are ignored. storage-id is the name under which
# this PBS instance is registered as storage on each PVE node (can differ
# per node if they weren't all named the same).
HOSTS_FILE="/etc/letsencrypt/pskz/pbs-storage-hosts.txt"

CERT_SRC="${RENEWED_LINEAGE:?RENEWED_LINEAGE is not set - this script must be run as a certbot --renew-hook}/fullchain.pem"
KEY_SRC="${RENEWED_LINEAGE}/privkey.pem"

if [ ! -f "$CERT_SRC" ] || [ ! -f "$KEY_SRC" ]; then
  echo "ERROR: expected cert files not found under $RENEWED_LINEAGE" >&2
  exit 1
fi

echo "Installing certificate into $PBS_CERT_DIR ..."
install -o root -g root -m 644 "$CERT_SRC" "$DEST_CERT"
install -o root -g root -m 640 "$KEY_SRC" "$DEST_KEY"
# proxmox-backup-proxy runs as user "backup" and needs read access to the key
chgrp backup "$DEST_KEY" 2>/dev/null || true

echo "Reloading proxmox-backup-proxy ..."
systemctl reload proxmox-backup-proxy

# Give the proxy a moment to actually pick up the new cert before we read
# it back via `cert info`.
sleep 3

echo "Reading new fingerprint ..."
FINGERPRINT=$(proxmox-backup-manager cert info \
  | awk -F': ' '/Fingerprint \(sha256\)/{print $2}' \
  | tr -d ' ')

if [ -z "$FINGERPRINT" ]; then
  echo "ERROR: could not extract fingerprint from 'proxmox-backup-manager cert info' output" >&2
  exit 1
fi

echo "New PBS fingerprint: $FINGERPRINT"

if [ ! -f "$HOSTS_FILE" ]; then
  echo "ERROR: hosts file $HOSTS_FILE not found, skipping fingerprint rollout" >&2
  exit 1
fi

FAILED_HOSTS=()

while read -r HOST STORAGE_ID; do
  # skip blank lines and comments
  [ -z "${HOST:-}" ] && continue
  case "$HOST" in \#*) continue ;; esac

  if [ -z "${STORAGE_ID:-}" ]; then
    echo "WARNING: no storage-id specified for host $HOST in $HOSTS_FILE, skipping" >&2
    continue
  fi

  echo "Updating fingerprint on $HOST (storage: $STORAGE_ID) ..."
  if ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new \
      "root@${HOST}" pvesm set "${STORAGE_ID}" --fingerprint "${FINGERPRINT}"; then
    echo "  OK: $HOST"
  else
    echo "  FAILED: $HOST" >&2
    FAILED_HOSTS+=("$HOST")
  fi
done < "$HOSTS_FILE"

if [ "${#FAILED_HOSTS[@]}" -gt 0 ]; then
  echo "ERROR: failed to update fingerprint on: ${FAILED_HOSTS[*]}" >&2
  exit 1
fi

echo "Fingerprint rollout complete."
