---
name: precision-estimation
description: Use full trial-level Monte Carlo simulation to choose a PsyNet design for precise estimation. This is the default method selected by the power-analysis skill unless the user requests another approach.
---

# Precision estimation

This method asks how precisely the planned analysis will estimate the scientific
quantities of interest under repeated, complete simulated experiments. Use it as
the default power-analysis method unless the user requests another approach.

Follow `power-analysis/SKILL.md` for the standard `audit/simulate/design/` files, costing,
reporting, and human-review workflow. Use the shared model described in
`participant-response-models/SKILL.md` to generate synthetic responses. For an
adaptive design, also read `make-experiment-adaptive/SKILL.md`.

## Plan the estimands and simulated population

An **estimand** is a quantity the experiment is intended to estimate. Examples
include a population mean, a regression coefficient, a stimulus-specific
response profile, or a variance component. Describe each estimand in ordinary
scientific language and show how the planned analysis returns an estimate of it.

State what is redrawn between simulated experiments. Participants are normally
redrawn. Stimuli should also be redrawn when the study is intended to generalize
beyond the particular sampled stimuli; hold their identities fixed when the
claim is only about that finite set. Apply the same reasoning to groups, items,
networks, and other sampled units.

Describe the response-model assumptions in terms of the task. Use parameter
values from pilot data or literature when available, and identify judgement-based
values clearly. Use one coherent response model for all estimands in a scenario
rather than silently changing the simulated world for each analysis.

Candidate designs are combinations of quantities the experimenter can choose,
such as participants, sampled stimuli, trials per participant, or adaptive budget.
The design grid should be dense enough to reveal the precision/cost frontier.
When an adaptive policy stops early, a cell labelled by its cap is not a
fixed-length design: disable stopping for matched-budget comparisons, or
report realized ``mean_n_observations`` beside precision metrics.

## Configure the simulation

Put shared execution settings, the candidate design grid, and the scientific
parameter values in `audit/simulate/design/config.toml`. Keep the definition of each
estimand, its truth, its estimator, and its resampling rule together in
`audit/simulate/design/core.py`; a
small class per estimand is often a clear way to do this.

Choose one value for `simulation.replicates` and apply it to every combination
of candidate design and response-model parameter scenario. For example, if
`replicates = 1000`, simulate each design-scenario combination independently
1,000 times. This makes Monte Carlo uncertainty comparable across the results.

```toml
[simulation]
replicates = 1000
base_seed = 20260823
keep_replicates = false
n_jobs = -2

[decision]
metric = "standardized_margin_of_error"
confidence_level = 0.95
threshold = 0.20

[design]
n_participants = [40, 60, 80, 100, 120]
trials_per_participant = [30, 60]
```

The values are examples. Extend the design and response sections to represent
the choices and assumptions relevant to the experiment.

When `keep_replicates` is true, save replicate-level estimates in an additional
Parquet file or directory. Otherwise retain only the aggregate results.

## Simulate complete experiments

For every candidate design and response-parameter scenario, simulate independent
trial-level datasets. Each replicate should reproduce the planned allocation,
missingness assumptions, response scale, rounding, clipping, and relevant
hierarchical sources of variation.

Run the simulations as standalone Python code outside PsyNet. Do not launch
participants, browsers, servers, or `psynet test local` for each replicate.
Simulate complete trial ratings rather than substituting analytical calculations,
coefficient-level proxies, or hypothesis-test rejection rates.

Import the canonical vectorized response sampler:

```python
from response_model import ResponseParameters, sample_responses


def run_replicate(design, parameters, rng):
    trials = make_trial_table(design, rng)
    responses = sample_responses(
        condition=trials["condition"].to_numpy(),
        participant_bias=trials["participant_bias"].to_numpy(),
        parameters=parameters,
        rng=rng,
    )
    data = trials.assign(response=responses)
    return fit_planned_analysis(data)
```

`fit_planned_analysis` should use the same estimator planned for the real data.
Statsmodels is the default for conventional regression and mixed-model analyses;
NumPy, pandas, and SciPy are the standard supporting packages. Use another
analysis library when the planned estimator requires it.

Keep the scientific question, estimand description, truth extraction, estimator,
and resampling rule close together. For example:

```python
import statsmodels.formula.api as smf


class ConditionEffect:
    id = "condition_effect"
    question = "How precisely can the condition effect be estimated?"
    estimand = "mean treatment-minus-control response"
    resampling = "participants and trial responses"

    @staticmethod
    def truth(world):
        return world.parameters.condition_effect

    @staticmethod
    def estimate(data):
        model = smf.ols("response ~ condition", data=data).fit()
        return model.params["condition"]
```

This class describes an analysis target; it does not define a separate response
model. Several targets can analyse data generated by the same simulated world.

Record failed estimator fits rather than silently dropping them. Vectorize
response generation and simple estimators across replicates where this preserves
the planned analysis. Do not change the estimator merely to make the simulation
fast.

Use Joblib's process-based `loky` backend for the full run. The default unit of
parallel work is one scenario: simulate its replicate datasets once and evaluate
all analysis targets from those shared datasets. This preserves a coherent
simulated world across targets and avoids repeating response generation. Let
Joblib batch these scenario jobs automatically. The suggested `n_jobs = -2` uses
every available CPU except one; use `n_jobs = 1` for the smoke run and debugging.
Limit numerical libraries to one thread inside each worker to avoid nested
parallelism.

Build the jobs and their random seeds deterministically before dispatch. Results
should not depend on the worker count or the order in which jobs finish:

```python
import hashlib

import numpy as np
from joblib import Parallel, delayed, parallel_config


def seed_for_scenario(base_seed, scenario_id):
    digest = hashlib.sha256(scenario_id.encode("utf-8")).digest()
    scenario_entropy = int.from_bytes(digest[:8], "big")
    return np.random.SeedSequence([base_seed, scenario_entropy])


jobs = sorted(build_scenario_jobs(config), key=lambda job: job.scenario_id)

with parallel_config(
    backend="loky",
    n_jobs=config["simulation"]["n_jobs"],
    inner_max_num_threads=1,
):
    results = Parallel()(
        delayed(run_scenario)(
            job,
            seed_for_scenario(base_seed, job.scenario_id),
        )
        for job in jobs
    )
```

Deriving seeds from stable scenario identifiers means that adding or reordering
other scenarios does not change an existing scenario's random stream. Within a
scenario, derive replicate streams from its scenario seed before parallel work
begins.

For an adaptive design, simulate the complete selection, response, and update
loop. The response model may match the adaptive learner or deliberately differ
from it to test robustness to misspecification.

## Measure precision

The **sampling standard error** is the standard deviation of an estimator across
independently simulated experiments. It approximates how much estimates from
repeated real experiments would vary:

```python
sampling_se = estimates.std(ddof=1)
```

The **margin of error** is half the width of an approximate confidence interval
around an estimate. At the default 95% confidence level:

```python
from scipy import stats

critical_value = stats.norm.ppf(0.975)
margin_of_error = critical_value * sampling_se
```

For example, an estimate of `0.7` with margin of error `0.2` is approximately
`0.7 ± 0.2`, giving an interval from `0.5` to `0.9`. The total interval width is
`0.4`.

Express margin of error in units of single-trial noise so precision is comparable
across response scales:

```python
standardized_margin_of_error = margin_of_error / trial_noise_sd
```

Unless the user chooses another criterion, require a 95% margin of error no
larger than `0.20` trial-noise standard deviations for every primary estimand:

```python
meets_requirement = standardized_margin_of_error <= 0.20
```

For a vector or profile, compute pointwise margins of error in the estimand's
natural coordinates and state how they are reduced to a design criterion. The
maximum pointwise margin is a conservative default. Do not introduce arbitrary
contrasts merely to obtain a scalar result.

Always report bias beside precision:

```python
errors = estimates - true_value
bias = errors.mean()
```

A narrow sampling distribution does not make a biased estimator acceptable. If
the planned estimator produces confidence intervals, also check their empirical
coverage across replicates.

The **Monte Carlo standard error** is different: it describes uncertainty in the
simulation's estimate of a summary such as the sampling standard error or margin
of error. Under an approximately normal sampling distribution:

```python
margin_of_error_mcse = margin_of_error / np.sqrt(2 * (replicates - 1))
```

Report this uncertainty, or use a bootstrap over replicate estimates when the
sampling distribution is appreciably non-normal. Also use a bootstrap for a
nonlinear decision summary such as the maximum pointwise margin of error: resample
complete replicate vectors and recompute the maximum on every bootstrap draw.
The fixed-point formula above does not account for uncertainty about which point
attains the maximum. Increase the common replicate count when Monte Carlo
uncertainty could change the selected design.

## Save and report the results

In addition to the general columns required by `power-analysis/SKILL.md`, record
the estimand, number of evaluated replicates, bias, sampling standard error,
margin of error, standardized margin of error, Monte Carlo uncertainty,
fit-failure count, and precision decision in `audit/simulate/design/results.csv`. Confirm that
every primary estimand is represented.

For the default criterion, set `decision_metric` to
`standardized_margin_of_error`, copy that row's standardized margin into
`decision_value`, copy `decision.threshold` into `decision_threshold`, and put
the comparison result in `meets_requirement`.

Record the random seed, replicate count, worker count, response parameters,
response-model hash or version, and any retained replicate data in
`audit/simulate/design/run.json`.

Use the Plotly conventions from `power-analysis/SKILL.md`. Plot precision against
participant count, distinguish other design dimensions with facets or line
styles, show the required precision as a horizontal line, and add a ribbon for
Monte Carlo uncertainty:

```python
import plotly.graph_objects as go

ordered = results.sort_values("n_participants")
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=ordered["n_participants"],
    y=ordered["standardized_margin_of_error_mc95_high"],
    line={"width": 0},
    showlegend=False,
))
fig.add_trace(go.Scatter(
    x=ordered["n_participants"],
    y=ordered["standardized_margin_of_error_mc95_low"],
    fill="tonexty",
    line={"width": 0},
    name="Monte Carlo 95% interval",
))
fig.add_trace(go.Scatter(
    x=ordered["n_participants"],
    y=ordered["standardized_margin_of_error"],
    mode="lines+markers",
    name="Margin of error",
))
fig.add_hline(y=0.20, line_dash="dash", annotation_text="Required precision")
fig.show()
```

Present the smallest designs that meet the requirement and nearby alternatives.
Explain sensitivity to the response assumptions rather than presenting a single
sample size without context.

## Validation

Run a small smoke simulation before the full design grid. Check estimator
recovery, bias, confidence-interval coverage when available, and fit failures.
Report enough Monte Carlo uncertainty to show whether simulation noise could
change the selected design.
