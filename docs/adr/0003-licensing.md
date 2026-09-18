# ADR 0003 — Licensing

- Status: accepted
- Date: 2026-09-18

## Context

TimesFM-3 model weights are released under the **TimesFM Non-Commercial License
v1.0** and are restricted to non-commercial, non-production use. The Precog
application code is MIT. Mixing the two naively would conflict.

## Decision

Keep the two regimes clearly separated:

- Application code: MIT (`LICENSE`).
- Model weights: TimesFM Non-Commercial License v1.0; **never** committed to
  this repository, **never** redistributed in published artifacts.

Operational rules (see issue `PREC-9`):

- `.gitignore` excludes weights and Hugging Face caches.
- By default the weights are **not baked into the image**: the container
  downloads them at runtime into a mounted volume and caches them there. The
  image therefore does not redistribute the weights.
- A baked variant is available for air-gapped use (`PRECOG_BAKE_WEIGHTS=true`);
  such an image embeds the weights and must not be published.
- `THIRD_PARTY_NOTICES.md` records the model license; it ships with the repo and
  inside the image.
- This is a non-commercial, hobby project. Users of the weights, however
  obtained, are bound by the non-commercial restriction.

The Python SDK contains only MIT code and carries no weights, so it may be
published on an explicit manual tag.
