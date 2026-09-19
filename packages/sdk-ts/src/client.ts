import {
  PrecogAPIError,
  PrecogConnectionError,
  PrecogError,
  PrecogTimeoutError,
  PrecogValidationError,
} from "./errors.js";
import type { Capabilities, ForecastRequest, ForecastResponse, ProblemDetail } from "./types.js";

const RETRY_STATUS = new Set([429, 500, 502, 503, 504]);

export interface PrecogClientOptions {
  /** API base URL, e.g. `http://localhost:8000`. */
  baseUrl: string;
  /** Optional bearer token. */
  apiKey?: string;
  timeoutMs?: number;
  maxRetries?: number;
  backoffMs?: number;
  /** Injectable fetch (defaults to the global `fetch`). */
  fetch?: typeof fetch;
}

export class PrecogClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly backoffMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(options: PrecogClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.apiKey = options.apiKey;
    this.timeoutMs = options.timeoutMs ?? 300_000;
    this.maxRetries = options.maxRetries ?? 2;
    this.backoffMs = options.backoffMs ?? 500;
    // Bind to globalThis: in browsers `fetch` throws "Illegal invocation" if
    // called with a different `this`.
    this.fetchImpl = (options.fetch ?? fetch).bind(globalThis) as typeof fetch;
  }

  /** Run a synchronous forecast (`POST /v1/forecast`). */
  forecast(request: ForecastRequest): Promise<ForecastResponse> {
    if (!Array.isArray(request?.series) || request.series.length === 0) {
      return Promise.reject(new PrecogValidationError("series must be a non-empty array"));
    }
    if (!Number.isInteger(request.horizon) || request.horizon <= 0) {
      return Promise.reject(new PrecogValidationError("horizon must be a positive integer"));
    }
    return this.request<ForecastResponse>("/v1/forecast", {
      method: "POST",
      body: JSON.stringify(request),
    });
  }

  /** Fetch model and API capabilities (`GET /v1/capabilities`). */
  capabilities(): Promise<Capabilities> {
    return this.request<Capabilities>("/v1/capabilities", { method: "GET" });
  }

  private async request<T>(path: string, init: RequestInit): Promise<T> {
    const headers: Record<string, string> = { accept: "application/json" };
    if (init.body !== undefined) headers["content-type"] = "application/json";
    if (this.apiKey) headers["authorization"] = `Bearer ${this.apiKey}`;

    let lastError: PrecogError | undefined;
    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      let response: Response;
      try {
        response = await this.fetchImpl(`${this.baseUrl}${path}`, {
          ...init,
          headers,
          signal: controller.signal,
        });
      } catch (error) {
        clearTimeout(timer);
        lastError =
          (error as Error)?.name === "AbortError"
            ? new PrecogTimeoutError("request timed out")
            : new PrecogConnectionError(
                `cannot reach ${this.baseUrl}: ${(error as Error).message}`,
              );
        if (attempt < this.maxRetries) {
          await this.sleep(attempt);
          continue;
        }
        throw lastError;
      }
      clearTimeout(timer);

      if (response.ok) {
        return (await response.json()) as T;
      }
      if (RETRY_STATUS.has(response.status) && attempt < this.maxRetries) {
        await this.sleep(attempt, response);
        continue;
      }
      throw await this.apiError(response);
    }
    throw lastError ?? new PrecogError("request failed");
  }

  private async apiError(response: Response): Promise<PrecogAPIError> {
    let payload: ProblemDetail | undefined;
    try {
      payload = (await response.json()) as ProblemDetail;
    } catch {
      payload = undefined;
    }
    const title = payload?.title ?? response.statusText ?? "error";
    return new PrecogAPIError(response.status, title, payload?.detail, payload);
  }

  private async sleep(attempt: number, response?: Response): Promise<void> {
    let delay = this.backoffMs * 2 ** attempt;
    const retryAfter = response?.headers.get("retry-after");
    if (retryAfter) {
      const seconds = Number(retryAfter);
      if (!Number.isNaN(seconds)) delay = seconds * 1000;
    }
    await new Promise((resolve) => setTimeout(resolve, delay));
  }
}
