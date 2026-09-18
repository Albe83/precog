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
- Weights are downloaded only at image **build** time.
- Container images (which bake the weights) are **not published** to any
  registry; they are built locally.
- `THIRD_PARTY_NOTICES.md` records the model license; it ships with the repo and
  inside the image.
- This is a non-commercial, hobby project. Users of a locally built image
  inherit the non-commercial restriction on the weights.

The Python SDK contains only MIT code and carries no weights, so it may be
published on an explicit manual tag.
