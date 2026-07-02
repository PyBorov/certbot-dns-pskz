# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-07-02

### Changed
- Replaced a real domain name that had leaked into a docstring example
  and the test fixtures with a generic placeholder (`example.kz`). No
  functional change.

## [0.1.0] - 2026-07-02

### Added
- Initial release.
- `dns-pskz` Certbot authenticator plugin implementing DNS-01 validation
  against the ps.kz DNS GraphQL API.
- Automatic zone resolution by walking up the domain's label hierarchy
  (e.g. `wiki.example.kz` → `example.kz` → `kz`) via `dns.zones(searchName: ...)`,
  so subdomains work without configuring the zone name explicitly.
- Credentials file support (`dns_pskz_token`), consistent with other
  `certbot-dns-*` plugins.
- Test suite covering zone resolution, record creation, and record
  cleanup (including not-found / zone-unresolvable edge cases), fully
  mocked against the HTTP layer.
- GitHub Actions CI running the test suite and a plugin-registration
  smoke test on Python 3.9–3.12.
