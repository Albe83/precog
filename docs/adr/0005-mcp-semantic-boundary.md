# ADR 0005 — MCP as the agent-facing semantic interface

- Status: accepted
- Date: 2026-09-19

## Context

Precog exposes TimesFM-3 forecasting through three surfaces: a REST API
(`/v1`), an MCP server (`apps/mcp`) and client SDKs. Those surfaces did not
share the same abstraction boundary. The REST API is shaped around how the
current backend wants a forecasting problem represented (execution `mode`,
request-level vs series-level covariates, model options), and the MCP server
initially forwarded that shape to agents.

That is the wrong boundary for an agent. An agent describes a forecasting
problem in domain terms; it should not need to know how the current engine
packages that problem for inference. The MCP redesign (#135) moved the tool to a
consumer-facing contract; this ADR records the resulting architectural role.

## Decision

The Precog **MCP server is the agent-facing semantic interface**. Its public
contract exposes forecasting concepts meaningful to a consumer, not execution
details of the current forecasting backend.

The MCP consumer provides already-prepared numeric time-series data and asks
Precog to perform semantic operations such as:

- forecast a set of related targets;
- backtest a forecast against a held-out tail;
- discover the semantic capabilities Precog supports.

The MCP server **may translate and orchestrate** calls to the current Precog
REST API to implement those operations. The REST API is an implementation
dependency of the MCP server, not its public contract.

## Responsibilities

The MCP consumer owns:

- fetching source data;
- cleaning and preparing data;
- equal sampling and time alignment;
- units and domain meaning;
- choosing targets and covariates;
- interpreting the result in domain terms.

The MCP server owns:

- the semantic public contract exposed to agents;
- validation of that contract;
- translation to the current execution API;
- orchestration required to implement semantic operations;
- normalization of results and errors into stable MCP-facing structures.

The MCP server must not expose backend-specific controls, including:

- explicit univariate/multivariate execution mode;
- TimesFM-specific configuration;
- symmetric averaging or quantile calibration knobs;
- internal covariate packing (`context + horizon`);
- batch-size or device controls;
- other execution-only options that are not part of the stable semantic
  contract.

## Relationship to the REST API

The MCP server is an HTTP client of the current REST API. A translation layer
(an anti-corruption adapter) converts the semantic MCP request into the REST
request and converts the REST response back into semantic structured content.

This ADR deliberately does **not** decide what the REST API should become. It
documents the present boundary only: today the REST API is execution-oriented
and the MCP server is semantic.

## Consequences

- Agents get a stable, model-independent contract; backend changes do not leak
  into the agent surface.
- The MCP surface can evolve (new semantic operations) without changing the
  REST API, and vice versa.
- The MCP server carries a translation layer that must validate both the
  semantic request and the upstream response (fail closed on malformed data).
- Semantic operations that need more than one REST call (for example
  backtesting) are orchestrated inside the MCP server, not by adding REST
  endpoints.
- Runtime capability limits that affect whether a request can be honored with
  the promised semantics are enforced at the API/engine boundary and surfaced
  to MCP consumers through stable error codes.

## Non-goals / deferred decisions

This ADR does not decide:

- whether the future REST API should be semantic or backend-oriented;
- whether a separate execution API should exist;
- whether Precog will support multiple forecasting engines;
- how engine selection or routing might work;
- whether REST endpoint names or versions should change;
- whether future backends (for example Chronos) will be added;
- any future internal package or directory architecture beyond what is needed to
  describe the present boundary.

Nothing here mandates a new internal structure; it describes the existing one.
