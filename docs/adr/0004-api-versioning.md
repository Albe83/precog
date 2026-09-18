# ADR 0004 — API versioning and deprecation

- Status: accepted
- Date: 2026-09-18

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

## Consequences

- Additive evolution is cheap and needs no coordination.
- Breaking changes are explicit, rare and versioned.
- The capability endpoint becomes the contract for numeric limits so they can
  change without a new major.
