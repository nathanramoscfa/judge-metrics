<!-- SECURITY.md -->
# Security policy

JudgeMetrics processes public court records and, from Phase 5, restricted
attributes that must never reach a public surface. Security findings are
handled as defects that jump the queue by severity (see `ROADMAP.md` §5,
"Vulnerability handling").

## Reporting a vulnerability

**Do not open a public issue for a vulnerability.**

Report it privately through GitHub's security advisories:

1. Open <https://github.com/nathanramoscfa/judge-metrics/security/advisories/new>.
2. Describe the issue, the affected surface (API, web, ingest, database,
   CI, repository settings), reproduction steps, and the impact you
   believe it has. Include a proof of concept if you have one; do not
   include real personal data.

You will receive an acknowledgement within 5 business days. Critical and
High findings are fixed on a `hotfix/` branch before new feature work
continues; Medium and Low findings are tracked with an owner and a due
date. You will be credited in the advisory unless you ask otherwise.

## Scope

In scope: this repository's code, workflows, container definitions,
repository settings, and any deployed JudgeMetrics surface.

Out of scope: the upstream data sources listed in
`docs/DATA_SOURCES.md` (report those to the source's owner), and
findings that require a compromised maintainer account or machine.

## Data-exposure reports

If you find a record that should not be public — a sealed, expunged, or
juvenile record, or a person identifier on a public surface — report it
through the same private advisory channel and mark it **data exposure**.
Suppression requests are handled ahead of any other work.

## Supported versions

The project is pre-release. Only the `main` branch receives fixes.
