# Third-party notices

## Precog

Precog application code is licensed under the MIT License (see `LICENSE`).

## TimesFM-3 model weights

The default model weights (`google/timesfm-3.0-pytorch`) are distributed by
Google Research under the **TimesFM Non-Commercial License v1.0**:

- License text: https://huggingface.co/google/timesfm-3.0-pytorch
- You may not use the weights for commercial or production purposes.
- The weights are **not** included in this repository and are **not**
  redistributed by the published Precog image. By default the container
  downloads them at startup into a cache volume; a baked variant exists only for
  air-gapped use and must not be published.

## TimesFM source code

The `timesfm` Python package is licensed under Apache-2.0 (versions up to 2.5;
the 3.0 checkpoint adds the non-commercial weight license above).

## Other dependencies

Python dependencies retain their respective licenses; see each package's
metadata.
