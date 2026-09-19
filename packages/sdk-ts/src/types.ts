export type Mode = "univariate" | "multivariate";

export interface SeriesInput {
  id: string;
  target: number[];
  past_covariates?: Record<string, number[]>;
  future_covariates?: Record<string, number[]>;
}

export interface ForecastOptions {
  return_quantiles?: boolean;
  symmetric_averaging?: boolean;
  quantile_spread_scale?: number;
  interpolate_missing?: boolean;
}

export interface ForecastRequest {
  mode?: Mode;
  horizon: number;
  series: SeriesInput[];
  options?: ForecastOptions;
  past_covariates?: Record<string, number[]>;
  future_covariates?: Record<string, number[]>;
}

export interface SeriesForecast {
  id: string;
  forecast: number[];
  quantiles?: number[][] | null;
}

export interface Usage {
  latency_ms: number;
  context_len: number;
}

export interface ForecastResponse {
  model: string;
  horizon: number;
  quantile_levels: number[];
  results: SeriesForecast[];
  usage: Usage;
}

export interface Capabilities {
  model: string;
  model_id: string;
  revision?: string | null;
  engine: string;
  device: string;
  modes: Mode[];
  max_horizon: number;
  max_context: number;
  max_series: number;
  quantile_levels: number[];
  covariates: Record<string, boolean>;
  auth_required: boolean;
}

export interface ProblemDetail {
  type: string;
  title: string;
  status: number;
  detail?: string | null;
}
