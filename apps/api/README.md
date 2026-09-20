# precog-api

Precog **REST Execution API**: Google
[TimesFM-3](https://research.google/blog/timesfm-3-a-zero-shot-foundation-model-for-multivariate-forecasting/)
zero-shot forecasting as a synchronous, typed HTTP service.

This is the Python distribution of the Precog API. Containers and Helm remain
the preferred production deployment path; install this package for development,
labs and Python-native environments. The distribution contains **no model
weights**.

## Install

```bash
pip install precog-api             # base install: fake engine only, no torch
pip install "precog-api[engine]"   # real TimesFM-3 engine (weights download at runtime)
```

The base install is lightweight and runs the deterministic fake engine, which is
enough to exercise the REST contract.

## Run

```bash
PRECOG_ENGINE=fake precog-api      # http://localhost:8000
precog-api                         # real engine (requires the [engine] extra)
```

Configuration uses the `PRECOG_` prefix (`PRECOG_ENGINE`, `PRECOG_DEVICE`,
`PRECOG_MAX_*`, `PRECOG_API_KEY`, ...). See the repository documentation.

## License

Application code is MIT. The TimesFM-3 model weights are distributed under the
TimesFM Non-Commercial License v1.0 and are **not** part of this distribution.
