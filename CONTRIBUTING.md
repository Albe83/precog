# Contributing

## Workflow

Trunk-based development. Short-lived branches merged with squash.

Branch naming: `feat/<scope>-<slug>`, `fix/<scope>-<slug>`, `docs/<slug>`, `chore/<slug>`.

Commit and PR titles follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>
```

Allowed types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `build`, `ci`, `perf`, `spike`.
Allowed scopes: `api`, `mcp`, `sdk`, `webui`, `deploy`, `deps`, `ci`, `docs`, `repo`.

Examples:

- `feat(api): add synchronous forecast endpoint`
- `fix(sdk): handle 422 problem+json`
- `docs(repo): document TLS inspection setup`

## Backlog

Work is tracked as GitHub issues and grouped by milestone in the *Precog
Roadmap* project. Dependencies are expressed as task lists inside each issue
body. Older `M0`–`M5` / `batch:N` labels are historical and are not the current
operating model.

## Commands

```bash
uv sync --all-packages --system-certs
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

`--system-certs` is only needed behind a TLS-inspecting proxy.

## Hooks and automation

Install the git hooks (needs `pre-commit`):

```bash
uv tool install pre-commit        # or: pipx install pre-commit
pre-commit install --hook-type pre-commit --hook-type commit-msg
```

- `pre-commit` runs ruff (lint + format) and validates the commit message.
- PR titles are checked in CI (`pr-title` workflow) with the same types/scopes.
- `release-please` opens a release PR from `main`; merging it tags the source,
  updates `CHANGELOG.md`, and publishes the release artifacts through the
  release workflows: the weight-free `precog-api` and `precog-mcp` images and
  the Helm chart (OCI + GitHub release `.tgz`). Model weights are never
  published. The `precog-schemas`/`precog-client` Python pair is versioned
  independently and published manually from `main` (`python-packages`
  workflow), not by release-please.
- Release PRs are merged by the `autorelease` workflow. A release PR that would
  cross a major version is not auto-merged and must be reviewed and merged
  deliberately.

### Major releases

`autorelease` compares the manifest major on `main` with the release PR target
major and refuses to merge across a boundary (for example `0.x` → `1.0.0`).

To cut a major release (e.g. v1.0.0 for #201):

1. review the release PR carefully: version, `CHANGELOG.md`, and the artifact
   configuration (`release-please-config.json`, workflows);
2. merge it manually (squash) once checks are green;
3. finalize explicitly, since a manual/fallback-`GITHUB_TOKEN` merge does not
   trigger the `push` workflow that creates the GitHub release:

   ```bash
   gh workflow run release-please.yml --ref main
   ```

   This creates the tag/GitHub release and publishes the images and Helm chart.
   It is idempotent: re-running it on an already-released version does nothing.
   With a `RELEASE_PLEASE_TOKEN` secret configured, the merge push finalizes
   automatically and step 3 is not needed.

## Branch protection

`main` is protected (enforced for admins too):

- Changes land through a pull request; direct pushes and force-pushes are
  rejected.
- Required status checks: `quality` (ci), `image` (build), `audit` + `sbom`
  (security), `lint` (helm/kustomize).
- Linear history and conversation resolution are required.

To make an emergency change, temporarily disable the ruleset/branch protection
in repository settings and re-enable it afterwards.

## Definition of Done

- Acceptance criteria of the issue satisfied.
- Lint, typecheck and tests green.
- Documentation updated where it matters.
- Semantic commit / PR title.
