# Contributing

## Workflow

Trunk-based development. Short-lived branches merged with squash.

Branch naming: `feat/<scope>-<slug>`, `fix/<scope>-<slug>`, `docs/<slug>`, `chore/<slug>`.

Commit and PR titles follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>
```

Allowed types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `build`, `ci`, `perf`, `spike`.
Allowed scopes: `api`, `mcp`, `sdk`, `deploy`, `ci`, `docs`, `repo`.

Examples:

- `feat(api): add synchronous forecast endpoint`
- `fix(sdk): handle 422 problem+json`
- `docs(repo): document TLS inspection setup`

## Backlog

Work is tracked as GitHub issues grouped by milestones (`M0`–`M5`). Each batch
corresponds to a milestone and its issues carry `batch:N` labels. Dependencies
are expressed as task lists inside each issue body.

## Commands

```bash
uv sync --all-packages --system-certs
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

`--system-certs` is only needed behind a TLS-inspecting proxy.

## Definition of Done

- Acceptance criteria of the issue satisfied.
- Lint, typecheck and tests green.
- Documentation updated where it matters.
- Semantic commit / PR title.
