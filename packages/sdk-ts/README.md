# @precog/sdk (TypeScript)

Typed TypeScript client for the Precog REST API. Works in Node 18+ and the
browser (uses `fetch`).

## Install

From this repository:

```bash
cd packages/sdk-ts
npm install
npm run build
```

## Usage

```ts
import { PrecogClient } from "@precog/sdk";

const client = new PrecogClient({ baseUrl: "http://localhost:8000" });

const caps = await client.capabilities();
console.log(caps.max_horizon, caps.modes);

const response = await client.forecast({
  horizon: 4,
  targets: [{ id: "sales", values: [100, 102, 101, 105, 107, 106, 108, 109] }],
  quantiles: [0.1, 0.9],
});
console.log(response.targets[0].forecast);
```

Multiple targets forecast jointly, with request-level covariates:

```ts
await client.forecast({
  horizon: 3,
  targets: [
    { id: "a", values: [100, 102, 101, 105, 107, 106] },
    { id: "b", values: [80, 81, 80, 83, 85, 84] },
  ],
  past_covariates: [{ id: "footfall", values: [0.1, 0.2, 0.15, 0.3, 0.4, 0.35] }],
  known_future_covariates: [
    { id: "promo", history: [0, 1, 0, 0, 0, 1], future: [0, 1, 0] },
  ],
});
```

## Errors

All errors extend `PrecogError`: `PrecogConnectionError`, `PrecogTimeoutError`,
`PrecogValidationError` and `PrecogAPIError` (`status`, `title`, `detail`).
Retries on `429`/`5xx` honour `Retry-After`.

## Scripts

```bash
npm run build      # emit dist/
npm run typecheck  # tsc --noEmit
npm test           # build + node --test
```
