import { PrecogClient, type ForecastResponse } from "@precog/sdk";

const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;

const form = $<HTMLFormElement>("form");
const apiUrl = $<HTMLInputElement>("apiUrl");
const seriesInput = $<HTMLTextAreaElement>("series");
const horizonInput = $<HTMLInputElement>("horizon");
const status = $<HTMLParagraphElement>("status");
const canvas = $<HTMLCanvasElement>("chart");

function parseSeries(text: string): number[] {
  return text
    .split(/[\s,]+/)
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
}

function client(): PrecogClient {
  return new PrecogClient({ baseUrl: apiUrl.value });
}

async function loadCapabilities(): Promise<void> {
  try {
    const caps = await client().capabilities();
    status.textContent = `model ${caps.model} · ${caps.device} · horizon ≤ ${caps.max_horizon} · ${caps.modes.join("/")}`;
  } catch (error) {
    status.textContent = `capabilities error: ${(error as Error).message}`;
  }
}

function draw(response: ForecastResponse, context: number[]): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const result = response.targets[0];
  const forecast = result.forecast;
  const quantiles = [...(result.quantiles ?? [])].sort((a, b) => a.level - b.level);
  const lower = quantiles[0]?.values ?? [];
  const upper = quantiles[quantiles.length - 1]?.values ?? [];
  const values = [...context, ...forecast, ...quantiles.flatMap((q) => q.values)];
  if (values.length === 0) return;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = 24;
  const total = context.length + forecast.length;
  const x = (i: number) => pad + (i * (width - 2 * pad)) / Math.max(1, total - 1);
  const y = (v: number) => height - pad - ((v - min) / Math.max(1e-9, max - min)) * (height - 2 * pad);

  const line = (points: number[], offset: number) => {
    ctx.beginPath();
    points.forEach((value, i) => {
      const px = x(offset + i);
      const py = y(value);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.stroke();
  };

  if (upper.length && lower.length) {
    const base = context.length;
    ctx.fillStyle = "rgba(59, 130, 246, 0.20)";
    ctx.beginPath();
    upper.forEach((value, i) => {
      const px = x(base + i);
      const py = y(value);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    for (let i = lower.length - 1; i >= 0; i--) {
      ctx.lineTo(x(base + i), y(lower[i]));
    }
    ctx.closePath();
    ctx.fill();
  }

  ctx.strokeStyle = "#94a3b8";
  line(context, 0);
  ctx.strokeStyle = "#2563eb";
  line(forecast, context.length);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const context = parseSeries(seriesInput.value);
  if (context.length < 2) {
    status.textContent = "enter at least two numeric values";
    return;
  }
  status.textContent = "forecasting…";
  try {
    const response = await client().forecast({
      horizon: Number(horizonInput.value),
      targets: [{ id: "series", values: context }],
      quantiles: [0.1, 0.9],
    });
    draw(response, context);
    status.textContent = `ok · ${response.usage.latency_ms.toFixed(1)} ms · ${response.model.id}`;
  } catch (error) {
    status.textContent = `error: ${(error as Error).message}`;
  }
});

void loadCapabilities();
