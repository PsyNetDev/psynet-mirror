# Design simulation: recommended setup

This page describes a recommended layout and code for a design simulation: a
standalone Python program kept in the experiment's audit that generates many
complete simulated experiments from a response model, analyzes each one, and
saves a results table, a run record and an executed notebook for review. The
terms are explained in [design-simulation-method.md](design-simulation-method.md).

Only the three files PsyNet displays in the audit (`simulation.ipynb`,
`run.json` and `results.csv`) have fixed names; see "Design simulation" in the
PsyNet audit reference (`test/audit_reference`). The `response_model/` package,
`config.toml` and `core.py` are recommendations; PsyNet neither requires nor
runs them. Add files when the method needs them.

## Files

```text
my_experiment/
  experiment.py
  response_model/
    __init__.py
    core.py
  audit/
    simulate/
      design/
        config.toml       # designs, assumptions, simulation settings
        core.py           # runs the simulation
        results.csv       # one row per scenario and analysis target
        run.json          # provenance for the run
        simulation.ipynb  # executed report
```

The stock `deploy.toml` excludes `audit/` from deployment, so the simulation
only runs locally. The `response_model/` package sits beside `experiment.py`
because the experiment's bots import it too.

## Response model package

Keep the response model in a small package that doesn't import PsyNet or use
its database, so that the simulation can call it thousands of times without a
server. Group the parameters in a dataclass, and write one function that takes
arrays of trials and an explicit random number generator:

```python
# response_model/core.py
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ResponseParameters:
    intercept: float = 0.0
    condition_effect: float = 0.4
    participant_sd: float = 0.5
    trial_noise_sd: float = 1.0


def sample_responses(*, condition, participant_bias, parameters, rng):
    expected = (
        parameters.intercept
        + participant_bias
        + parameters.condition_effect * condition
    )
    noise = rng.normal(0.0, parameters.trial_noise_sd, size=expected.shape)
    return np.clip(np.round(expected + noise), -3, 3)
```

Re-export `ResponseParameters` and `sample_responses` from `__init__.py`. The
model is specific to each experiment; this one is only an example. Apply the
rounding and limits of the real response control inside the function, so that
bots and the simulation produce the same values. When several sets of
assumptions are compared, give each parameter set a stable name.

Test that a fixed seed reproduces the same responses and that array inputs give
one response per trial.

## Bot adapter

Bots draw their participant-level values once, in `Experiment.initialize_bot`,
and each trial passes one trial to the same function:

```python
import numpy as np

from .response_model import ResponseParameters, sample_responses

PARAMETERS = ResponseParameters()


class RatingTrial(StaticTrial):
    def show_trial(self, experiment, participant):
        return ModularPage(
            "rating",
            "How pleasant is this sound?",
            NumberControl(bot_response=self.get_bot_response),
        )

    def get_bot_response(self, bot):
        rng = np.random.default_rng()
        return int(sample_responses(
            condition=np.asarray([self.definition["condition"]]),
            participant_bias=np.asarray([bot.var.bias]),
            parameters=PARAMETERS,
            rng=rng,
        )[0])


class Exp(psynet.experiment.Experiment):
    def initialize_bot(self, bot):
        rng = np.random.default_rng()
        bot.var.bias = rng.normal(0.0, PARAMETERS.participant_sd)
```

The adapter only converts the model's output into the answer the page expects.
Record the parameter set's name or values on the bot, for example in `bot.var`,
so that it appears in the export. Add NumPy to `requirements.txt` if the
experiment doesn't already depend on it. How bots answer is described in the
PsyNet docs (`test/backend`).

## Configuration

`config.toml` lists the candidate designs, the assumption sets and the
simulation settings. Every combination of design and assumption values is one
scenario:

```toml
method = "precision-estimation"

[decision]
metric = "margin_of_error"
confidence_level = 0.95
threshold = 0.20
unit = "rating points"
rationale = "Half the smallest condition effect worth finding (0.4 points)."

[design]
n_participants = [40, 60, 80, 100]
trials_per_participant = [30, 60]

[assumptions]
trial_noise_sd = [0.8, 1.0, 1.2]

[simulation]
replicates = 1000
base_seed = 20260824
n_jobs = -2
```

Use the same number of replicates for every scenario, so that Monte Carlo error
is comparable across results.

## Simulation script

`core.py` reads `config.toml`, runs every scenario, and writes `results.csv` and
`run.json`. Run it from the experiment directory, so that `response_model` can
be imported:

```shell
python -m audit.simulate.design.core
```

`psynet[experiment]` already installs NumPy, pandas and Joblib, but not
statsmodels, PyArrow (for Parquet) or the notebook tools (Plotly, Jupyter,
nbconvert). Add the
packages the simulation and notebook import to `requirements.txt` and rerun
`psynet setup`; packages installed with `uv pip install` alone are removed by
the next `psynet setup`.

For each scenario, the script simulates every replicate at the trial level with
`sample_responses`, fits the planned analysis to each simulated dataset, and
summarizes the estimates for every analysis target. Use the estimator planned
for the real data, for example a statsmodels regression or mixed model. Count
failed fits instead of dropping them.

Keep each analysis target's question, true value, estimator and resampling rule
together, for example in one small class per target:

```python
import statsmodels.formula.api as smf


class ConditionEffect:
    id = "condition_effect"
    estimand = "mean treatment-minus-control response"

    @staticmethod
    def truth(parameters):
        return parameters.condition_effect

    @staticmethod
    def estimate(data):
        model = smf.ols("response ~ condition", data=data).fit()
        return model.params["condition"]
```

Make results reproducible and independent of how the work is split. Derive each
scenario's random seed from `base_seed` and a stable scenario identifier, and
each replicate's seed from its scenario's seed:

```python
import hashlib

import numpy as np


def seed_for_scenario(base_seed, scenario_id):
    digest = hashlib.sha256(scenario_id.encode("utf-8")).digest()
    return np.random.SeedSequence([base_seed, int.from_bytes(digest[:8], "big")])
```

Adding or reordering scenarios then leaves the others unchanged. To run
scenarios in parallel, one job per scenario with Joblib's `loky` backend works
well; limit numerical libraries to one thread per worker
(`parallel_config(backend="loky", inner_max_num_threads=1)`). Run a small
version with `n_jobs = 1` first to check that the estimator recovers the true
values.

## Results table

`results.csv` has one row per scenario and analysis target, and is keyed by:

- `result_id`, unique for the row and derived from the columns below;
- `scenario_id`, one combination of design and assumptions;
- `analysis_id`, the analysis target;
- `parameter_id`, only when one target produces several rows, such as one per
  stimulus.

Add the design and assumption values, then the summaries: the number of
replicates evaluated, bias, sampling standard error, margin of error, its
Monte Carlo interval, and the number of failed fits. For a profile, also add
the RMS and largest margins of single values and of differences, the true
spread, the profile correlation and the smallest spread for the target
correlation. For the decision, add
`decision_metric`, `decision_value`, `decision_threshold` and
`meets_requirement`, and, if participants are paid, `participant_payment` and
`currency`. Keep column names the same across runs so the notebook can compare
them.

For one target in one scenario, with `estimates` holding one estimate per
replicate:

```python
from statistics import NormalDist

import numpy as np

z = NormalDist().inv_cdf(0.975)
sampling_se = estimates.std(ddof=1)
margin_of_error = z * sampling_se
bias = (estimates - true_value).mean()
margin_of_error_mcse = margin_of_error / np.sqrt(2 * (replicates - 1))
```

For a profile, `estimates` has one row per replicate and one column per value,
and `truth` holds the true values:

```python
def rms(values):
    return np.sqrt(np.mean(np.square(values)))


margins = z * estimates.std(axis=0, ddof=1)
rms_margin_of_error, max_margin_of_error = rms(margins), margins.max()

covariance = np.cov(estimates, rowvar=False)
variances = np.diag(covariance)
difference_variances = variances[:, None] + variances[None, :] - 2 * covariance
pairs = np.triu_indices(len(variances), k=1)
difference_margins = z * np.sqrt(difference_variances[pairs])
rms_difference_margin_of_error = rms(difference_margins)
max_difference_margin_of_error = difference_margins.max()

true_spread = truth.std()
correlations = [np.corrcoef(row, truth)[0, 1] for row in estimates]
profile_correlation = np.tanh(np.mean(np.arctanh(correlations)))  # Fisher-z average
centered = estimates - estimates.mean(axis=1, keepdims=True)
centered_se = np.sqrt(centered.var(axis=0, ddof=1).mean())
target_correlation = 0.9
spread_for_target_correlation = (
    centered_se * target_correlation / np.sqrt(1 - target_correlation**2)
)
```

The Monte Carlo standard error formula assumes roughly normal estimates.
Otherwise, and for a summary such as the RMS margin of error across a
profile, bootstrap over replicates: resample whole replicates and recompute the
summary each time.

## Run record

`run.json` records how the results were produced. The audit shows `method`,
`command`, `replicates`, `result_row_count`, `created_at` and `note` when they
are present. Also record the random seed, number of workers, response-model
parameters, hashes of `config.toml`, `core.py` and the response model, a hash of
`results.csv`, the Git commit, the Python and package versions, and the
`psynet estimate` output used for costs.

## Costs

Once the timeline represents one candidate design, run:

```shell
psynet estimate --mode both
```

It reports the maximum reward per participant and the duration, from the pages'
`time_estimate` values and `wage_per_hour` (see `code/participants/payment` in
the PsyNet docs). It doesn't include performance bonuses. The command imports
the experiment, so run it once for a reference design, save its output in
`run.json`, and calculate other designs from it rather than calling it inside
the design loop:

```python
reward_per_trial = trial_seconds * wage_per_hour / 3600
fixed_reward = reference_reward - reference_trials * reward_per_trial
results["participant_payment"] = results["n_participants"] * (
    fixed_reward + results["trials_per_participant"] * reward_per_trial
)
```

Run `psynet estimate` again after material timeline changes. Before the
timeline exists, use planned durations and label the costs as provisional.

## Notebook

`simulation.ipynb` reads `config.toml`, `results.csv` and `run.json` rather than
rerunning the simulation. It has a *Power analysis* section and, for an adaptive
experiment, an *Adaptive procedure* section. Order each section as in
"Reporting the results" of the method page: summary, what the results would
look like, one subsection per question, assumptions, then details for
reviewers.

The audit renders the notebook's saved outputs, so execute it before adding it.
Plotly figures stay interactive, offline, if the notebook selects the MIME
renderer before making figures:

```python
import plotly.io as pio

pio.renderers.default = "plotly_mimetype"
pio.templates.default = "plotly_white"
```

For the example dataset, simulate one replicate at the chosen design with
`sample_responses` and a fixed seed, run the planned estimator, and plot each
estimate with its interval, sorted by the estimate.

Plot the decision metric against the number of participants, with other design
factors as facets or line styles, the threshold as a horizontal line, and the
Monte Carlo interval as a shaded band. Give band traces `mode="lines"`;
otherwise Plotly draws a marker at every corner of the band. Label the axis in
the response's units and the legend in plain words. Below it, add a table of
the smallest design meeting the criterion under each assumption set, with its
cost.

For a profile, show how much the ranking depends on the assumed spread: at the
chosen design, plot the expected profile correlation against the true spread,
with the assumed spread and the smallest spread for the target correlation
marked. The expected correlation follows from the smallest spread `s_target`
for the target correlation `r_target`:

```python
spread = np.linspace(0.01, 1.5 * true_spread, 200)
centered_se = s_target * np.sqrt(1 - r_target**2) / r_target
expected_correlation = spread / np.sqrt(spread**2 + centered_se**2)
```

Put the table of every metric at the chosen design in the details section,
with readable column names, such as "Difference margin (points)" rather than
`rms_difference_margin_of_error`. Plotly `updatemenus` buttons can switch a
figure between metrics; ipywidgets and page-level tabs don't work in the
rendered audit. Restyle one set of traces per button instead of adding a set of
traces per metric, which keeps the notebook small. Executed notebooks may be up
to 10 MB. The audit collapses code cells behind a "Show code" toggle, so
readers see the prose, figures and tables first.

## Adding the simulation to the audit

Mark the artifacts present, then render and check the section:

```shell
psynet audit mark-present simulation_notebook
psynet audit mark-present simulation_run
psynet audit mark-present simulation_results
psynet audit serve --render
```

`mark-present` checks that each file exists and that the notebook is valid.
