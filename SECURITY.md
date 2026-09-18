# Security Policy

## Reporting a vulnerability

Please do not open a public issue for security problems. Report privately using
GitHub's [private vulnerability reporting](https://docs.github.com/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository ("Security" tab → "Report a vulnerability"). Include steps to
reproduce, impact and any suggested fix.

## Scope

This project is a non-commercial hobby project. In scope:

- The API, MCP server and SDK code in this repository.
- The container images published from it.

## Hardening notes

- The model weights (`google/timesfm-3.0-pytorch`) are non-commercial and are
  **not** contained in the images; they are downloaded at runtime. See
  `THIRD_PARTY_NOTICES.md`.
- Do **not** publish images built with `PRECOG_BAKE_WEIGHTS=true`: they embed the
  non-commercial weights.
- Never commit secrets. Runtime configuration is provided via `PRECOG_*`
  environment variables / Kubernetes Secrets.
- The MCP HTTP listener has no built-in authentication; deploy it behind a
  gateway or restrict network access. Use `PRECOG_MCP_ALLOWED_HOSTS` to
  configure Host validation.
- The API optionally requires a bearer token (`PRECOG_API_KEY`).

## Supported versions

Only the latest published release is supported. Fixes are released as new
versions (semantic commits via `release-please`).
