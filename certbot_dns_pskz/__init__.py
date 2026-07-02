"""DNS Authenticator plugin for certbot using the ps.kz DNS GraphQL API."""
import logging

import requests

from certbot import errors
from certbot.plugins import dns_common

logger = logging.getLogger(__name__)

API_URL = "https://console.ps.kz/dns/graphql"


class Authenticator(dns_common.DNSAuthenticator):
    """DNS Authenticator for ps.kz

    This Authenticator uses the ps.kz DNS GraphQL API to fulfill a dns-01 challenge.
    """

    description = (
        "Obtain certificates using a DNS TXT record (if you are using ps.kz "
        "for DNS)."
    )
    ttl = 60

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.credentials = None

    @classmethod
    def add_parser_arguments(cls, add, default_propagation_seconds=60):  # pylint: disable=arguments-differ
        super().add_parser_arguments(add, default_propagation_seconds)
        add("credentials", help="ps.kz credentials INI file")

    def more_info(self):
        return (
            "This plugin configures a DNS TXT record to respond to a "
            "dns-01 challenge using the ps.kz GraphQL DNS API."
        )

    def _validate_credentials(self, credentials):
        token = credentials.conf("token")
        if not token:
            raise errors.PluginError(
                "{}: dns_pskz_token is required".format(credentials.confobj.filename)
            )

    def _setup_credentials(self):
        self.credentials = self._configure_credentials(
            "credentials",
            "ps.kz credentials file",
            {
                "token": (
                    "API token generated in the ps.kz console "
                    "(value sent as the X-User-Token header)"
                ),
            },
            self._validate_credentials,
        )

    def _perform(self, domain, validation_name, validation):
        self._get_pskz_client().add_txt_record(domain, validation_name, validation)

    def _cleanup(self, domain, validation_name, validation):
        self._get_pskz_client().del_txt_record(domain, validation_name, validation)

    def _get_pskz_client(self):
        return _PSKZClient(self.credentials.conf("token"))


class _PSKZClient:
    """Encapsulates all communication with the ps.kz GraphQL DNS API."""

    def __init__(self, token):
        self.token = token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "X-User-Token": token,
            }
        )

    def _query(self, query, variables=None):
        try:
            resp = self.session.post(
                API_URL,
                json={"query": query, "variables": variables or {}},
                timeout=30,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise errors.PluginError(
                "Error communicating with the ps.kz API: {}".format(e)
            )

        data = resp.json()
        if data.get("errors"):
            raise errors.PluginError(
                "ps.kz API returned an error: {}".format(data["errors"])
            )
        return data["data"]

    def _find_zone(self, domain):
        """Find the most specific zone accessible to this token that
        matches ``domain``, walking up the label hierarchy.

        e.g. for wiki.exmpl.kz it tries: wiki.exmpl.kz, exmpl.kz, asia
        """
        candidate = domain.rstrip(".")
        while candidate:
            data = self._query(
                "query($s: String){ dns { zones(searchName: $s, perPage: 20) "
                "{ items { name } } } }",
                {"s": candidate},
            )
            items = data["dns"]["zones"]["items"] or []
            for item in items:
                # ps.kz stores zone names as FQDNs with a trailing dot
                if item["name"].rstrip(".") == candidate:
                    return item["name"]
            if "." not in candidate:
                break
            candidate = candidate.split(".", 1)[1]

        raise errors.PluginError(
            "Unable to find a ps.kz zone matching domain {} with this "
            "token".format(domain)
        )

    def add_txt_record(self, domain, record_name, record_content):
        zone = self._find_zone(domain)
        mutation = """
        mutation CreateDNSRecord($zoneName: String!, $recordData: RecordCreateInput!) {
          dns {
            record {
              create(zoneName: $zoneName, createData: $recordData) {
                name
                records { name type value ttl }
              }
            }
          }
        }
        """
        variables = {
            "zoneName": zone,
            "recordData": {
                "name": record_name.rstrip(".") + ".",
                "type": "TXT",
                "value": record_content,
                "ttl": 60,
            },
        }
        logger.debug("Creating TXT record %s in zone %s", record_name, zone)
        self._query(mutation, variables)

    def del_txt_record(self, domain, record_name, record_content):
        try:
            zone = self._find_zone(domain)
        except errors.PluginError:
            logger.warning(
                "Could not resolve ps.kz zone for %s during cleanup, "
                "skipping",
                domain,
            )
            return

        lookup = """
        query GetZoneRecords($domainName: String!) {
          dns {
            zone(name: $domainName) {
              records { id name type value }
            }
          }
        }
        """
        data = self._query(lookup, {"domainName": zone})
        zone_data = data["dns"]["zone"] or {}
        records = zone_data.get("records") or []

        target_name = record_name.rstrip(".") + "."
        record_id = None
        for rec in records:
            if (
                rec["type"] == "TXT"
                and rec["name"] == target_name
                and rec["value"] == record_content
            ):
                record_id = rec["id"]
                break

        if not record_id:
            logger.debug(
                "TXT record %s with expected value not found during "
                "cleanup, nothing to do",
                record_name,
            )
            return

        mutation = """
        mutation DeleteDnsRecord($zoneName: String!, $recordId: String!) {
          dns {
            record {
              delete(zoneName: $zoneName, recordId: $recordId) {
                id
                name
              }
            }
          }
        }
        """
        logger.debug("Deleting TXT record id=%s in zone %s", record_id, zone)
        self._query(mutation, {"zoneName": zone, "recordId": record_id})
