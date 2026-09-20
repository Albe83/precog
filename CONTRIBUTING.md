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
  release workflows: the weight-free `precog-api` and `precog-mcp` images, the
  Helm chart (OCI + GitHub release `.tgz`), and the application Python
  distributions (`precog-api`, `precog-mcp`) when enabled (see below). Model
  weights are never published. The `precog-schemas`/`precog-client` Python pair
  is versioned independently and published manually from `main`
  (`python-packages` workflow), not by release-please.
- Release PRs are merged by the `autorelease` workflow. A release PR that would
  cross a major version is not auto-merged and must be reviewed and merged
  deliberately.

### Major releases

`autorelease` compares the manifest major on `main` with the release PR target
major and refuses to merge across a boundary (for example `0.x` → `1.0.0`).

To cut a major release (e.g. v1.0.0 for #201):

1. land a one-shot commit on `main` whose commit body contains
   `Release-As: 1.0.0` (use the intended major version). Release Please uses
   that footer to override the semantic version it would otherwise derive; do
   not persist `release-as` in `release-please-config.json`;
2. review the generated release PR carefully: version, `CHANGELOG.md`, and the
   artifact configuration (`release-please-config.json`, workflows);
3. merge it manually (squash) once checks are green;
4. finalize explicitly, since a manual/fallback-`GITHUB_TOKEN` merge does not
   trigger the `push` workflow that creates the GitHub release:

   ```bash
   gh workflow run release-please.yml --ref main
   ```

   This creates the tag/GitHub release and publishes the images and Helm chart.
   It is idempotent: re-running it on an already-released version does nothing.
   With a `RELEASE_PLEASE_TOKEN` secret configured, the merge push finalizes
   automatically and step 3 is not needed.

### Application Python packages (PyPI)

`precog-api` and `precog-mcp` are also published to PyPI as secondary
distributions of the same application release (containers/Helm remain the
preferred production path). `publish-python-apps` is a **standalone** workflow
(PyPI Trusted Publishing does not support reusable workflows): when a release is
cut and `PYPI_APP_PUBLISH` is set, `release-please.yml` dispatches it via the
workflow-dispatch API at the release tag ref and waits for the run, so a failed
publication fails the release. It builds from the concrete release tag commit
and uploads via OIDC — no static token, and never from a later `main` commit.

Bootstrap: publication is opt-in through the repository variable
`PYPI_APP_PUBLISH`. Leave it unset for ordinary pre-v1 releases; enable it for
the deliberate `v1.0.0` release after registering the Trusted Publishers below.

PyPI enforces uniqueness of the `(owner, repo, workflow, environment)` tuple, so
each package in a workflow needs its own environment. The exact identities are:

| Project | Workflow | Environment |
| ------- | -------- | ----------- |
| `precog-schemas` | `.github/workflows/python-packages.yml` | `pypi` |
| `precog-client` | `.github/workflows/python-packages.yml` | `pypi-client` |
| `precog-api` | `.github/workflows/publish-python-apps.yml` | `pypi` |
| `precog-mcp` | `.github/workflows/publish-python-apps.yml` | `pypi-mcp` |

Create the empty GitHub environments (`pypi`, `pypi-client`, `pypi-mcp`) before
registering the corresponding pending publishers. The SDK pair
(`precog-schemas`/`precog-client`) remains a separate train and is not published
by the application workflow.

Retries are safe: API and MCP publish as independent jobs after a shared,
validated build (package version is asserted to equal the release tag), and
uploads use `skip-existing`, so a successful API upload does not force a rebuild
or a version change when MCP needs a retry. Re-publish an existing tag with:

```bash
gh workflow run publish-python-apps.yml --ref v1.0.0 -f tag=v1.0.0
```

or re-dispatch it through the release workflow with
`gh workflow run release-please.yml -f dispatch_pypi_tag=v1.0.0`.

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
