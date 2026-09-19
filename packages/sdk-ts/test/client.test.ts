import assert from "node:assert/strict";
import test from "node:test";

import { PrecogAPIError, PrecogClient, PrecogConnectionError } from "../src/index.js";

const RESPONSE = {
  model: "timesfm-3.0",
  horizon: 2,
  quantile_levels: [0.1, 0.5, 0.9],
  results: [{ id: "a", forecast: [1, 2] }],
  usage: { latency_ms: 1, context_len: 3 },
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("forecast parses the response", async () => {
  const client = new PrecogClient({
    baseUrl: "http://api.test",
    fetch: async () => jsonResponse(RESPONSE),
  });
  const result = await client.forecast({
    horizon: 2,
    series: [{ id: "a", target: [1, 2, 3] }],
  });
  assert.equal(result.model, "timesfm-3.0");
  assert.deepEqual(result.results[0]?.forecast, [1, 2]);
});

test("api errors are mapped", async () => {
  const client = new PrecogClient({
    baseUrl: "http://api.test",
    maxRetries: 0,
    fetch: async () =>
      jsonResponse({ title: "Unprocessable Entity", detail: "horizon exceeds max" }, 422),
  });
  await assert.rejects(
    () => client.forecast({ horizon: 99999, series: [{ id: "a", target: [1] }] }),
    (error: unknown) => {
      assert.ok(error instanceof PrecogAPIError);
      assert.equal(error.status, 422);
      assert.equal(error.detail, "horizon exceeds max");
      return true;
    },
  );
});

test("transient errors are retried", async () => {
  let calls = 0;
  const client = new PrecogClient({
    baseUrl: "http://api.test",
    maxRetries: 1,
    backoffMs: 0,
    fetch: async () => {
      calls += 1;
      return calls === 1 ? jsonResponse({}, 503) : jsonResponse(RESPONSE);
    },
  });
  const result = await client.forecast({ horizon: 2, series: [{ id: "a", target: [1, 2, 3] }] });
  assert.equal(calls, 2);
  assert.equal(result.model, "timesfm-3.0");
});

test("connection errors are mapped", async () => {
  const client = new PrecogClient({
    baseUrl: "http://api.test",
    maxRetries: 0,
    fetch: async () => {
      throw new Error("refused");
    },
  });
  await assert.rejects(
    () => client.forecast({ horizon: 1, series: [{ id: "a", target: [1] }] }),
    PrecogConnectionError,
  );
});

test("invalid requests are rejected locally", async () => {
  const client = new PrecogClient({ baseUrl: "http://api.test", fetch: async () => jsonResponse({}) });
  await assert.rejects(
    () => client.forecast({ horizon: 0, series: [{ id: "a", target: [1] }] }),
    /horizon must be a positive integer/,
  );
});
