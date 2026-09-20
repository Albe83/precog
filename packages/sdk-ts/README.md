# @precog/sdk (TypeScript)

> **Experimental — not part of the supported v1 product surface.**
>
> This package is retained in-tree and kept buildable, but it is not a supported
> Precog interface and must not drive the REST/MCP/Python architecture. The
> supported v1 surfaces are the REST Execution API, the MCP semantic interface
> and the Python SDK (`precog-client`). Use the Python client for supported
> execution. No feature work is planned here.

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
console.log(caps.engine, caps.limits.max_horizon, caps.limits.max_context);

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
