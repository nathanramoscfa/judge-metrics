<!-- .github/PULL_REQUEST_TEMPLATE.md -->
## Roadmap step

<!-- e.g. Phase 1 Step 1 (docs/phase01-roadmap.md) — or "not a roadmap step" -->

## Summary

<!-- What this PR changes and why. One PR per step. -->

## Test plan

<!-- Commands run and their results. -->

- [ ] `uv run poe check`
- [ ] `uv run poe gate`

## Screenshots (UI)

<!-- Required when `web/` changes; otherwise "n/a". -->

## Breaking changes

<!-- API, schema, CLI, config, or data-format changes; or "none". -->

## Rollback plan

<!-- How to undo this if it is merged and wrong. -->

## Security gate

- [ ] Secret / PII scan clean (`detect-secrets` locally, gitleaks in CI)
- [ ] SAST clean (`bandit`; any suppression has an inline justification)
- [ ] Dependency audit clean (`pip-audit --strict`)
- [ ] Sensitive-data diff review done: no restricted columns in public
      paths, no PII in logs, no over-broad grants; workflow files pin
      actions by SHA, declare minimum `permissions:`, and expose no
      secret to pull-request triggers

## Definition of done

- [ ] Feature implemented
- [ ] Types added
- [ ] Database migration added if required
- [ ] Unit tests added
- [ ] Integration tests added when relevant
- [ ] Relevant documentation updated
- [ ] Lint passes
- [ ] Type checking passes
- [ ] Tests pass
- [ ] Frontend production build passes when the frontend is affected
- [ ] No credentials committed
- [ ] Data lineage preserved when data is affected

## Issues opened

<!-- Findings classified per ROADMAP.md §5 and filed, or "none". -->
