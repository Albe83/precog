# Precog Web UI

> **Experimental — not part of the supported v1 product surface.**
>
> The Web UI is retained in-tree as a demo and kept buildable, but it is not a
> supported Precog interface and must not drive the REST/MCP/Python
> architecture. The supported v1 surfaces are the REST Execution API, the MCP
> semantic interface and the Python SDK (`precog-client`). No feature work is
> planned here.

Minimal browser UI for the Precog REST API: paste a target series, choose a
horizon, and see the median forecast with the 10–90% quantile band. It consumes
the TypeScript SDK (`@precog/sdk`) directly from `packages/sdk-ts/src`.

## Development

```bash
cd webui
npm install
npm run dev        # http://localhost:5173
```

Set the API URL in the form (leave empty to use the same origin). In dev, Vite
proxies `/v1` to `http://localhost:8000`, so the default works against a local
API without CORS changes. For a different API host, either set the URL (the API
must allow CORS) or serve the built assets behind the same origin as the API.

## Build

```bash
npm run build      # typecheck + static assets in dist/
npm run preview    # serve the build locally
```

The output in `dist/` is static and can be served by any web server or embedded
elsewhere. In production, point it at the API (behind TLS / a gateway as
appropriate) via the form or a small config change.

## Scripts

```bash
npm run typecheck  # tsc --noEmit
npm run build      # tsc --noEmit && vite build
```
