#!/usr/bin/env bash
# ps.kz DNS API plugin, compatible with the acme.sh dnsapi interface used
# by Proxmox VE's built-in ACME client (proxmox-acme).
#
# Configuration (one of):
#   export PSKZ_Token="secret.accountid.userid"
#   pvenode acme plugin add dns pskz --api pskz --data /path/to/pskz.env
#     (where the file contains: PSKZ_Token=secret.accountid.userid)
#
# Each ps.kz API token is bound to a single account at creation time; if
# your zones are split across multiple accounts you need one plugin
# instance (one token / one --data file) per account.

PSKZ_API="https://console.ps.kz/dns/graphql"

# Fallback logging helpers, used only if the host environment (acme.sh /
# proxmox-acme) hasn't already defined them.
if ! command -v _err >/dev/null 2>&1; then
  _err() { echo "[pskz] ERROR: $*" >&2; }
fi
if ! command -v _info >/dev/null 2>&1; then
  _info() { echo "[pskz] INFO: $*" >&2; }
fi

########  Public functions #####################

# Usage: dns_pskz_add   _acme-challenge.www.domain.com   "txt-value"
dns_pskz_add() {
  fulldomain=$1
  txtvalue=$2

  if [ -z "$PSKZ_Token" ] && command -v _readaccountconf_mutable >/dev/null 2>&1; then
    PSKZ_Token="$(_readaccountconf_mutable PSKZ_Token)"
  fi
  if [ -z "$PSKZ_Token" ]; then
    _err "PSKZ_Token is not set."
    return 1
  fi
  if command -v _saveaccountconf_mutable >/dev/null 2>&1; then
    _saveaccountconf_mutable PSKZ_Token "$PSKZ_Token"
  fi

  if ! command -v jq >/dev/null 2>&1; then
    _err "jq is required but not installed (apt install -y jq)."
    return 1
  fi

  if ! _pskz_find_zone "${fulldomain#\*.}"; then
    _err "Unable to find a ps.kz zone matching $fulldomain with this token."
    return 1
  fi
  _info "Resolved ps.kz zone: $_pskz_zone for $fulldomain"

  _pskz_mutation=$(jq -n \
    --arg zone "$_pskz_zone" \
    --arg name "${fulldomain}." \
    --arg value "$txtvalue" \
    '{
      query: "mutation CreateDNSRecord($zoneName: String!, $recordData: RecordCreateInput!) { dns { record { create(zoneName: $zoneName, createData: $recordData) { name } } } }",
      variables: { zoneName: $zone, recordData: { name: $name, type: "TXT", value: $value, ttl: 60 } }
    }')

  _pskz_response=$(curl -s "$PSKZ_API" \
    -H "Content-Type: application/json" \
    -H "X-User-Token: $PSKZ_Token" \
    --data "$_pskz_mutation")

  if echo "$_pskz_response" | jq -e '.errors' >/dev/null 2>&1; then
    _err "ps.kz API error: $(echo "$_pskz_response" | jq -c '.errors')"
    return 1
  fi

  return 0
}

# Usage: dns_pskz_rm   _acme-challenge.www.domain.com   "txt-value"
dns_pskz_rm() {
  fulldomain=$1
  txtvalue=$2

  if [ -z "$PSKZ_Token" ] && command -v _readaccountconf_mutable >/dev/null 2>&1; then
    PSKZ_Token="$(_readaccountconf_mutable PSKZ_Token)"
  fi
  if [ -z "$PSKZ_Token" ]; then
    _err "PSKZ_Token is not set."
    return 1
  fi

  if ! _pskz_find_zone "${fulldomain#\*.}"; then
    _info "Unable to resolve ps.kz zone for $fulldomain during cleanup, skipping."
    return 0
  fi

  _pskz_lookup=$(jq -n --arg zone "$_pskz_zone" '{
    query: "query GetZoneRecords($domainName: String!) { dns { zone(name: $domainName) { records { id name type value } } } }",
    variables: { domainName: $zone }
  }')

  _pskz_lookup_resp=$(curl -s "$PSKZ_API" \
    -H "Content-Type: application/json" \
    -H "X-User-Token: $PSKZ_Token" \
    --data "$_pskz_lookup")

  _pskz_record_id=$(echo "$_pskz_lookup_resp" | jq -r \
    --arg name "${fulldomain}." \
    --arg value "$txtvalue" \
    '.data.dns.zone.records[]? | select(.type=="TXT" and .name==$name and .value==$value) | .id' \
    | head -1)

  if [ -z "$_pskz_record_id" ]; then
    _info "TXT record for $fulldomain not found during cleanup, nothing to do."
    return 0
  fi

  _pskz_delete=$(jq -n --arg zone "$_pskz_zone" --arg id "$_pskz_record_id" '{
    query: "mutation DeleteDnsRecord($zoneName: String!, $recordId: String!) { dns { record { delete(zoneName: $zoneName, recordId: $recordId) { id } } } }",
    variables: { zoneName: $zone, recordId: $id }
  }')

  curl -s "$PSKZ_API" \
    -H "Content-Type: application/json" \
    -H "X-User-Token: $PSKZ_Token" \
    --data "$_pskz_delete" >/dev/null

  return 0
}

####################  Private functions below ##################################

# _pskz_find_zone domain
# Walks up the label hierarchy (wiki.example.kz -> example.kz -> kz) and
# sets $_pskz_zone (with trailing dot, as returned by the API) on success.
_pskz_find_zone() {
  _pskz_candidate="$1"

  while true; do
    _pskz_query=$(jq -n --arg s "$_pskz_candidate" '{
      query: "query($s: String){ dns { zones(searchName: $s, perPage: 20) { items { name } } } }",
      variables: { s: $s }
    }')

    _pskz_resp=$(curl -s "$PSKZ_API" \
      -H "Content-Type: application/json" \
      -H "X-User-Token: $PSKZ_Token" \
      --data "$_pskz_query")

    _pskz_match=$(echo "$_pskz_resp" | jq -r \
      --arg c "$_pskz_candidate" \
      '.data.dns.zones.items[]? | select((.name | rtrimstr(".")) == $c) | .name' \
      | head -1)

    if [ -n "$_pskz_match" ]; then
      _pskz_zone="$_pskz_match"
      return 0
    fi

    case "$_pskz_candidate" in
      *.*) _pskz_candidate="${_pskz_candidate#*.}" ;;
      *) return 1 ;;
    esac
  done
}
