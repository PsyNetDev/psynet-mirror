# Power-analysis terminology

The central distinction is between what the experimenter chooses, what the
analysis assumes about the world, and what the analysis tries to learn.

## Design

A **design** describes an experiment that could be run. It contains quantities
under the experimenter's control, such as the number of participants, number of
stimuli, trials per participant, allocation across conditions, or adaptive
budget.

For a colour–chord experiment, one design might be:

```toml
n_participants = 60
chords_per_category = 3
n_hues = 6
trials_per_participant = 54
```

Changing any of these choices produces a different design.

## Assumptions

**Assumptions** describe the world in which a proposed design is evaluated. They
are not directly chosen when running the real experiment and are often uncertain
before data collection. Examples include trial noise, participant variation,
stimulus variation, the strength of a relationship, missing responses, or the
population from which stimuli are sampled.

For example:

```toml
trial_noise_sd = 0.65
participant_variation_sd = 0.35
chord_specific_variation_sd = 0.20
roughness_slope = 0.30
```

Evaluate several plausible assumption sets when uncertainty about them could
change the design decision. A design that works only under optimistic assumptions
is less convincing than one that remains adequate across a reasonable range.

Some closely related quantities fall on different sides of this distinction.
The number of stimuli is a design choice; the population distribution from which
those stimuli are sampled is an assumption.

## Scenario

A **scenario** is one design combined with one complete set of assumptions. For
example:

```text
Design:
    60 participants
    3 chords per category
    54 trials per participant

Assumptions:
    trial noise SD = 0.65
    chord-specific variation SD = 0.20
    roughness slope = 0.30
```

Assign each combination a stable `scenario_id`. If the configuration contains
five participant counts, two trial counts, and three noise assumptions, it
defines `5 × 2 × 3 = 30` scenarios.

## Replicate

A **replicate** is one complete synthetic experiment generated under a scenario.
Replicates share the same design and population assumptions, but contain newly
sampled participants, responses, and—when the intended generalization requires
it—stimuli.

Replicates apply only to stochastic methods. In simulation-based precision
estimation, repeated replicates yield a sampling distribution for every analysis
target. Analytical methods may evaluate a scenario without generating any
replicates.

## Analysis target

An **analysis target** is one scientific quantity or question evaluated for a
scenario. A scenario can have several targets, all evaluated using the same
design and assumptions.

Under the default precision-estimation method, a target connects a scientific
question to an **estimand** and an **estimator**. The estimand is the underlying
quantity of interest; the estimator is the procedure applied to observed data to
estimate it. Other power-analysis methods may instead define a target around a
hypothesis test, decision, or utility.

For the colour–chord experiment, possible targets include:

```text
analysis_id = "chord_profiles"
Question: How precisely can each sampled chord profile be estimated?
Estimand: Each chord's population response profile.
Estimator: The fitted chord-by-colour profile from the planned model.
```

```text
analysis_id = "category_profiles"
Question: How precisely can category profiles be estimated?
Estimand: The population response profile for each chord category.
Estimator: The fitted category profiles from the planned model.
```

```text
analysis_id = "roughness_slope"
Question: How precisely can the relationship with roughness be estimated?
Estimand: The profile change for a one-SD increase in roughness.
Estimator: The fitted roughness coefficient from the planned model.
```

These targets do not require separate simulated worlds. One replicate can be
generated from a coherent response model and then analysed for all three.

## Decision metric and decision criterion

A **decision metric** summarizes how well a design performs for an analysis
target. A **decision criterion** states the threshold the metric must meet for the
design to be considered adequate.

For the default precision-estimation workflow, these might be:

```text
Decision metric:
    95% margin of error in trial-noise SD units

Decision criterion:
    margin of error <= 0.20
```

Other methods can use different metrics and criteria.

## Mapping to results

Each scenario is ordinarily evaluated for every analysis target. This produces
several rows with the same `scenario_id` and different `analysis_id` values:

```csv
result_id,scenario_id,analysis_id
scenario_001--chord_profiles,scenario_001,chord_profiles
scenario_001--category_profiles,scenario_001,category_profiles
scenario_001--roughness_slope,scenario_001,roughness_slope
```

`result_id` is a stable unique identifier for the row. Here it is derived from
`scenario_id` and `analysis_id`; if a target produces several parameter-level
rows, include `parameter_id` as a third component.

The resulting rows answer: under this design and these assumptions, how well
does the chosen method perform for each scientific target? The final design
decision then considers all primary targets, plausible assumption sets, and
participant costs.
