---
name: power-analysis
description: Plan and implement power analyses for PsyNet experiments. Use when choosing participant counts, stimuli, trials, or other design parameters before data collection.
---

# Power analysis

It is good practice to conduct power analyses prior to conducting an experiment. We encourage power analysis as part of the standard experiment implementation workflow.

There are many ways to conduct power analysis. Today's agents are familiar with most standard paradigms and can straightforwardly implement them for a given experiment. This document outlines PsyNet's expectations for how the power analysis code is structured, and provides some general methodological recommendations.

In the absence of overruling instructions, PsyNet recommends a default precision-estimation approach to power analysis.
This is detailed in the `precision-estimation` skill.

Most PsyNet experiments pay participants for the time they spend on the experiment. Some experiments additionally deliver bonuses for good performance. These financial considerations should form part of the power analysis;
see `references/psynet-costing.md` for information.

## Terminology

| Term | Meaning |
| --- | --- |
| Design | Choices under the experimenter's control |
| Assumptions | Values or processes outside the experimenter's control that are assumed for the analysis |
| Scenario | One complete combination of a design and a set of assumptions |
| Replicate | One synthetic experiment generated under a scenario |
| Analysis target | One scientific quantity or question evaluated for each scenario |
| Decision criterion | The rule used to decide whether a design is adequate |

Read [references/terminology.md](references/terminology.md) for fuller definitions and a worked example.

## Response models

Power-analysis methods that simulate participant responses need a simulation
response model. Follow `participant-response-models/SKILL.md` for this.
Record the response-model parameter values or named parameter set in
`power/config.toml`, and record a code hash or version in `power/run.json`.

## Required files

Every power analysis should use the following layout in the experiment root:

```text
power/
├── config.toml
├── core.py
├── results.csv
├── run.json
└── analysis.ipynb
```
All files are required, but contents can be customized as desired. Additional files are allowed when the method needs them.

A typical data flow is `config.toml` → `core.py` → `results.csv` and `run.json` → `analysis.ipynb` → `audit/PLAN.md`.

### `config.toml`

This should outline key parameters for the power analysis; these will often be lists of parameters such as `n_participants` and `trials_per_participant` that will be explored in a grid search, as well as simulation parameters such as random seed and number of replicates. For example:

```toml
schema_version = "1.0"
method = "precision-estimation"

[decision]
metric = "standardized_margin_of_error"
confidence_level = 0.95
threshold = 0.20

[design]
n_participants = [40, 60, 80, 100]
trials_per_participant = [30, 60]

[assumptions]
trial_noise_sd = [0.8, 1.0, 1.2]

[simulation]
replicates = 1000
base_seed = 20260824
keep_replicates = false
n_jobs = -2
```

### `core.py`

This contains the executable implementation of the chosen method. A suggested
pattern is to read `config.toml`, validate it, evaluate every requested scenario,
and write `results.csv` and `run.json`. A `main()` entry point makes the analysis
easy to run from the experiment root:

```bash
python -m power.core
```

The following pseudocode illustrates the intended orchestration:

```python
def main():
    config = load_toml("power/config.toml")
    rows = []

    for design, assumptions in expand_scenarios(config):
        scenario_id = stable_scenario_id(design, assumptions)
        outcome = run_selected_method(config, design, assumptions)
        for target in outcome.analysis_targets:
            rows.append({
                "result_id": stable_result_id(scenario_id, target.id),
                "scenario_id": scenario_id,
                "analysis_id": target.id,
                "method": config["method"],
                **design,
                **assumptions,
                **target.summary,
            })

    results = DataFrame(rows)
    results.to_csv("power/results.csv", index=False)
    run = {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "method": config["method"],
        "command": "python -m power.core",
        "source_sha256": hash_files("power/config.toml", "power/core.py"),
        "results_sha256": hash_file("power/results.csv"),
        "result_row_count": len(results),
    }
    Path("power/run.json").write_text(json.dumps(run, indent=2))
```

`run_selected_method(...)` and the result summaries are supplied by the chosen
method.

For stochastic methods, reproducibility from the same inputs and random seed is
strongly recommended.

### `results.csv`

This is the tabular output consumed by the notebook and audit. It should be keyed
by the following columns:

- `result_id` - A stable identifier that uniquely identifies the row.
- `scenario_id` - Identifies one combination of a candidate design and a complete
  set of assumptions.
- `analysis_id` - Identifies the analysis target evaluated within that scenario.
- `parameter_id` - Optionally identifies a parameter or component when one
  analysis target produces several result rows. Omit it when each target produces
  exactly one row.

Each `result_id` should be derived from `scenario_id` and `analysis_id`, plus
`parameter_id` when present.

Suggested common columns are:

- `method` - Identifies the power-analysis method.
- `decision_metric` - Names the quantity used to evaluate the design.
- `decision_value` - Gives that metric's value for this row.
- `decision_threshold` - Gives the threshold used to judge adequacy.
- `meets_requirement` - Records whether the row meets the criterion.
- `participant_payment` - Gives the estimated total participant payment for the
  design.
- `currency` - Identifies the currency used for participant payment.

Methods should add their own descriptive and diagnostic columns. Use the same
column names across runs so that notebooks can compare results directly.

### `run.json`

This records provenance for the run that produced `results.csv`. Suggested fields
include the schema version, UTC timestamp, method, invocation, source and result
hashes, Git commit and dirty state, Python and relevant package versions, and
result row count. Include the random seed and replicate count when applicable. A
representative subset is shown in the `core.py` pseudocode above.

### `analysis.ipynb`

This is the executed review document. It should normally read the saved inputs
and outputs rather than rerunning `core.py` or silently altering the results. It
explains the method and assumptions, shows the candidate-design comparison and
participant costs, and states which designs satisfy the decision criterion. Save
the notebook with its review-relevant tables and interactive figures embedded (prefer Plotly unless otherwise specified).

## Related reading

- `make-experiment-adaptive/SKILL.md` explains the implementation of adaptive
  experiments.
