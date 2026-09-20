export type Mode = "univariate" | "multivariate";

export interface HistoricalSeries {
  id: string;
  values: number[];
}

export interface KnownFutureSeries {
  id: string;
  history: number[];
  future: number[];
}

export interface ForecastRequest {
  horizon: number;
  targets: HistoricalSeries[];
  past_covariates?: HistoricalSeries[];
  known_future_covariates?: KnownFutureSeries[];
  quantiles?: number[];
}

export interface QuantileForecast {
  level: number;
  values: number[];
}

export interface TargetForecast {
  id: string;
  forecast: number[];
  quantiles?: QuantileForecast[];
}

export interface ModelProvenance {
  id: string;
  revision?: string | null;
}

export interface Usage {
  latency_ms: number;
  context_len: number;
}

export interface ForecastResponse {
  horizon: number;
  targets: TargetForecast[];
  model: ModelProvenance;
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
  max_variates?: number | null;
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
