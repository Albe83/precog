export class PrecogError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}

export class PrecogConnectionError extends PrecogError {}

export class PrecogTimeoutError extends PrecogError {}

export class PrecogValidationError extends PrecogError {}

export class PrecogAPIError extends PrecogError {
  constructor(
    public readonly status: number,
    public readonly title: string,
    public readonly detail?: string | null,
    public readonly payload?: unknown,
  ) {
    super(`${status} ${title}${detail ? `: ${detail}` : ""}`);
  }
}
