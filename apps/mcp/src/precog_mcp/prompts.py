"""Optional MCP workflow prompts.

Prompts are user-invoked recipes, distinct from the always-on semantic guidance
in the server instructions, tool descriptions and ``precog://capabilities``.
They encode *how to use forecasting well* (evaluation discipline) without
encoding *what business problem to solve*: no vertical/domain-specific
assumptions, no fixed success thresholds, no backend internals, and no
redefinition of the ``forecast``/``backtest`` request/response schemas.

The optional ``objective`` argument is the only input: prompts otherwise guide
the model from the current conversation context rather than recreating the tool
schemas.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

EVALUATE_FORECASTABILITY_DESCRIPTION = (
    "Evidence-based workflow to decide whether Precog provides useful "
    "forecasting signal for a time-series problem."
)

EVALUATE_FORECASTABILITY_PROMPT = """\
Evaluate whether Precog provides useful forecasting signal for the user's \
time-series problem.

Work from the user's actual forecasting objective. Choose an evaluation horizon \
that matches that objective. If the horizon is not explicit but can be \
reasonably inferred, state the assumption; do not invent a domain-specific \
horizon without saying so.

Use any tools available in the host environment to obtain the source data. \
Before calling Precog, ensure each series is numeric, equally sampled, \
time-aligned, ordered from oldest to newest, and free of unresolved missing \
values. Preserve the meaning and units of the original series. If you resample, \
interpolate, smooth, aggregate, clip, or otherwise transform the data, state the \
transformation and recognize that it changes what is being forecast.

If several targets represent one related forecasting problem, evaluate them \
jointly in one Precog backtest. Do not split related targets merely because \
their units or numeric scales differ. Use separate forecasting problems for \
genuinely unrelated series.

Start with backtest rather than forecast. Precog backtest evaluates a single \
held-out tail: the final horizon samples are ground truth and the preceding \
samples are forecast context. Treat the result as evidence from that window, not \
as cross-validation or proof of general performance.

Interpret results per target:
- MAE and RMSE are expressed in the target's native units;
- sMAPE is scale-relative but can be unstable or misleading when actual and \
forecast values are near zero;
- interval coverage describes the requested forecast interval on the evaluated \
points, but coverage from a short holdout is not a robust calibration estimate.

Do not apply universal thresholds such as "sMAPE below X is good". Decide \
usefulness relative to the user's objective and the behavior of the series.

When practical, compare Precog with a simple baseline computed outside Precog, \
such as persistence using the last observed value. A low forecast error does not \
by itself show that the forecasting model adds value if a trivial baseline \
performs as well or better.

When enough history is available and the decision matters, repeat the evaluation \
at multiple historical cutoffs by truncating the input series and running \
additional backtests with the same horizon. Do not describe a single Precog \
backtest as a rolling backtest.

Report:
1. the data preparation and horizon used;
2. per-target backtest evidence;
3. baseline comparison when available;
4. whether each target appears useful to forecast for the stated objective;
5. uncertainty, limitations, and any transformations that affect interpretation.

Do not claim or infer backend architecture, model internals, or why joint \
forecasting worked or failed unless that information is explicitly provided by \
Precog. Judge the observed forecasting behavior, not an assumed implementation.
"""

COMPARE_JOINT_VS_INDEPENDENT_DESCRIPTION = (
    "Evidence-based workflow to decide whether related targets benefit from "
    "being forecast jointly rather than independently."
)

COMPARE_JOINT_VS_INDEPENDENT_PROMPT = """\
Determine whether a set of related target series benefits from being forecast \
jointly rather than as independent forecasting problems.

Use exactly the same source observations, sampling interval, data preparation, \
horizon, quantiles, and evaluation cutoffs for both variants. Do not smooth, \
normalize, aggregate, or otherwise transform only one side of the comparison.

First run one joint Precog backtest containing all related targets in the same \
request.

Then run one independent Precog backtest for each target using that target \
alone, with the same horizon and corresponding historical observations.

Compare joint and independent results per target. Use the reported MAE, RMSE, \
sMAPE, forecast values, actual values, and interval coverage as evidence. \
Remember that MAE and RMSE are in each target's own units, sMAPE can be unstable \
near zero, and short-window coverage is only descriptive.

Do not assume joint forecasting is better merely because the series are related, \
and do not assume independent forecasting is better merely because targets have \
different units or scales. Let the observed results decide.

When enough history is available, repeat the comparison over multiple historical \
cutoffs by truncating all series consistently and rerunning both joint and \
independent evaluations. Aggregate the evidence per target rather than drawing a \
strong conclusion from one holdout window.

For each target, classify the evidence only in relative terms:
- joint performs better;
- independent performs better;
- no meaningful difference is demonstrated;
- evidence is insufficient or inconsistent.

Explain the size and consistency of the observed difference rather than using \
arbitrary universal thresholds.

If a simple baseline is available, use it as additional context so that "joint \
beats independent" is not confused with "either approach is operationally \
useful".

Report:
1. the exact comparison setup;
2. per-target joint versus independent metrics;
3. results across evaluation windows, if multiple windows were used;
4. which targets appear to benefit from joint modeling;
5. whether the evidence is strong enough to change how the user should structure \
future Precog requests;
6. important limitations.

Do not infer or explain backend model internals. The purpose of this workflow is \
to measure the effect of joint versus independent Precog requests empirically.
"""


def _compose(body: str, objective: str) -> str:
    """Optionally prepend the user's stated objective to a workflow body."""
    objective = objective.strip()
    if not objective:
        return body
    return f"Forecasting objective (from the user): {objective}\n\n{body}"


def register_prompts(server: MCPServer) -> None:
    """Register the optional generic forecasting workflow prompts."""

    @server.prompt(
        name="evaluate_forecastability",
        title="Evaluate forecastability",
        description=EVALUATE_FORECASTABILITY_DESCRIPTION,
    )
    def evaluate_forecastability(objective: str = "") -> str:
        return _compose(EVALUATE_FORECASTABILITY_PROMPT, objective)

    @server.prompt(
        name="compare_joint_vs_independent",
        title="Compare joint vs independent forecasting",
        description=COMPARE_JOINT_VS_INDEPENDENT_DESCRIPTION,
    )
    def compare_joint_vs_independent(objective: str = "") -> str:
        return _compose(COMPARE_JOINT_VS_INDEPENDENT_PROMPT, objective)


__all__ = [
    "COMPARE_JOINT_VS_INDEPENDENT_DESCRIPTION",
    "COMPARE_JOINT_VS_INDEPENDENT_PROMPT",
    "EVALUATE_FORECASTABILITY_DESCRIPTION",
    "EVALUATE_FORECASTABILITY_PROMPT",
    "register_prompts",
]
