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
  mode: "univariate",
  horizon: 4,
  series: [{ id: "sales", target: [100, 102, 101, 105, 107, 106, 108, 109] }],
});
console.log(response.results[0].forecast);
```

Multivariate with request-level covariates:

```ts
await client.forecast({
  mode: "multivariate",
  horizon: 3,
  series: [
    { id: "a", target: [100, 102, 101, 105, 107, 106] },
    { id: "b", target: [80, 81, 80, 83, 85, 84] },
  ],
  past_covariates: { footfall: [0.1, 0.2, 0.15, 0.3, 0.4, 0.35] },
  future_covariates: { promo: [0, 1, 0, 0, 0, 1, 0, 1, 0] },
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
