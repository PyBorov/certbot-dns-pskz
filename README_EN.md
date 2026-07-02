# certbot-dns-pskz

[![CI](https://github.com/PyBorov/certbot-dns-pskz/actions/workflows/ci.yml/badge.svg)](https://github.com/PyBorov/certbot-dns-pskz/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/certbot-dns-pskz.svg)](https://pypi.org/project/certbot-dns-pskz/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[RU README](https://github.com/PyBorov/certbot-dns-pskz/blob/main/README.md)

A [Certbot](https://certbot.eff.org/) DNS Authenticator plugin for
[ps.kz](https://ps.kz) — automates DNS-01 (`_acme-challenge` TXT record)
domain validation using the ps.kz DNS GraphQL API, so you can issue and
auto-renew wildcard and standard TLS certificates without any manual DNS
editing.

## Why

ps.kz's DNS console (`console.ps.kz/dns/graphql`) exposes a GraphQL API,
but it isn't publicly documented, and authentication requires a specific
`X-User-Token` header (not the more common `Authorization: Bearer` /
cookie-session schemes you'd expect from a typical Apollo Server setup).
This plugin wraps that API into a standard Certbot authenticator plugin.

## Requirements

* Certbot >= 1.1.0
* Python 3.7+
* An API token generated in the ps.kz console for the account that owns
  the target DNS zone

## Installation

```bash
pip install certbot-dns-pskz
```

Or from source:

```bash
git clone https://github.com/PyBorov/certbot-dns-pskz.git
cd certbot-dns-pskz
pip install -e .
```

Verify Certbot sees the plugin:

```bash
certbot plugins --text | grep -A3 pskz
```

## Credentials

Create an INI file containing your ps.kz API token:

```ini
# /etc/letsencrypt/pskz/credentials.ini
dns_pskz_token = xxxxxxxxxxxxxxxx.accountid.userid
```

```bash
chmod 600 /etc/letsencrypt/pskz/credentials.ini
```

**Note:** each ps.kz API token is bound to a single account at creation
time. If your zones are split across multiple ps.kz accounts, you'll
need a separate token (and separate `certbot` invocation / credentials
file) per account.

## Usage

```bash
certbot certonly \
  --authenticator dns-pskz \
  --dns-pskz-credentials /etc/letsencrypt/pskz/credentials.ini \
  --dns-pskz-propagation-seconds 60 \
  -d example.kz -d '*.example.kz'
```

| Flag | Description | Default |
|---|---|---|
| `--dns-pskz-credentials` | Path to the credentials INI file | *(required)* |
| `--dns-pskz-propagation-seconds` | Seconds to wait for DNS propagation before asking the CA to validate | `60` |

Renewal works exactly like any other Certbot plugin — the invocation
above (including these flags) is saved into
`/etc/letsencrypt/renewal/<cert-name>.conf` and reused automatically by
`certbot renew`.

## How zone resolution works

The plugin resolves the correct DNS zone for a given domain by querying
`dns.zones(searchName: ...)` and walking up the label hierarchy until it
finds an exact match your token has access to — e.g. for
`wiki.example.kz` it tries `wiki.example.kz`, then `example.kz`, then
`kz`, and uses the first exact match. This means it works correctly for
subdomains without needing to know the zone name in advance.

## Deploying alongside other tooling (e.g. GitLab Omnibus)

Certbot's DNS-01 plugins only handle domain validation — they don't
install the certificate anywhere. For services like GitLab Omnibus that
expect certs in a specific location, use `--deploy-hook` /
`--renew-hook` to copy the issued certificate and reload the relevant
service, e.g.:

```bash
certbot certonly \
  --authenticator dns-pskz \
  --dns-pskz-credentials /etc/letsencrypt/pskz/credentials.ini \
  --renew-hook "/etc/letsencrypt/pskz/gitlab-deploy.sh" \
  -d gitlab.example.kz -d registry.gitlab.example.kz \
  --cert-name gitlab.example.kz
```

## Background: an undocumented API

ps.kz doesn't publish API documentation for the DNS console. This plugin
exists because the schema was recovered via GraphQL introspection
against `console.ps.kz/dns/graphql`, and the correct auth header
(`X-User-Token`, rather than the `Authorization: Bearer` scheme the
tokens' `secret.accountId.userId` format might suggest) was found by
trial and error against ps.kz's own Cloud API docs.

Two things worth knowing if you're debugging this yourself or if ps.kz
changes something upstream:

- **Tokens are bound to a single account at creation time.** The
  `accountId` segment in the token string is cosmetic — swapping it
  doesn't change which account the token resolves to. If your domains
  are split across multiple ps.kz accounts, you need one token (and one
  `certonly`/`renew` invocation) per account.
- **Zone names are returned with a trailing dot** (e.g. `example.kz.`),
  matching standard DNS FQDN notation. The plugin strips it for
  comparison but always sends the API the zone name exactly as returned.

If ps.kz ever publishes an official API or changes this schema, please
open an issue.

## Testing

The test suite mocks the HTTP layer entirely — no real API calls are
made, and no credentials are required to run it.

```bash
pip install -e ".[test]"
pytest -v
```

## License

MIT — see [LICENSE](LICENSE).
