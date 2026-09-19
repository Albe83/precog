# ADR 0004 — API versioning and deprecation

- Status: accepted
- Date: 2026-09-18
- Amended: 2026-09-19 (pre-release scope, see [ADR 0006](0006-execution-layer.md))

## Context

The REST API exposes a stable contract under `/v1` used by the MCP server, the
Python SDK and third-party clients. We need a predictable rule for evolving it
without breaking consumers.

## Decision

- **Major version in the path**: `/v1`. Breaking changes ship under a new major
  (`/v2`) while the previous major keeps working.
- **Within a major, only backwards-compatible changes** are allowed: new
  optional request fields, new response fields, new endpoints, new enum values
  in responses (clients must tolerate unknown values), relaxed validation.
  Renaming/removing fields, changing types or tightening validation is breaking.
- **Discovery**: clients should read `GET /v1/capabilities` for limits and
  feature support rather than hard-coding them.
- **Deprecation**:
  - Announce in `CHANGELOG.md`, the OpenAPI description and the docs, with the
    replacement and a timeline.
  - Keep a deprecated endpoint/field for at least one minor release before
    removal, and only remove it in a new major.
  - Mark deprecated fields in the OpenAPI schema (`deprecated: true`).
  - Where practical, return `Deprecation`/`Sunset` response headers.
- **Clients**: the Python SDK pins to a major version and treats new response
  fields as optional.

## Pre-release scope

The compatibility commitment above applies to **released** contracts. Precog has
not been released yet, so the current `/v1` contract is not yet a stability
guarantee.

[ADR 0006](0006-execution-layer.md) performs a one-time reset of `/v1` in place
while introducing the execution layer. That reset is **not** a breaking change
that requires `/v2`, and no backward-compatibility machinery is built for the
pre-release contract. The rules in this ADR take effect once the redesigned
execution contract becomes the released baseline.

## Consequences

- Additive evolution is cheap and needs no coordination.
- Breaking changes are explicit, rare and versioned.
- The capability endpoint becomes the contract for numeric limits so they can
  change without a new major.
