# PsyNet participant-cost estimation

Participant count maps directly to recruitment cost, so include participant
payment alongside statistical precision when comparing designs.

If the experiment timeline has not yet been implemented, calculate provisional
costs from the planned fixed-page and per-trial durations and label them as such.
Replace them with the PsyNet estimate once the timeline exists; revisit the design
decision if the difference is material.

After the experiment timeline represents a candidate design, run PsyNet's
estimate once from the experiment root:

```bash
psynet estimate --mode both
```

The command reports the estimated maximum participant reward and completion
time using the timeline's `time_estimate` values and the experiment's configured
`wage_per_hour`. It does not include performance bonuses.

Do not call `psynet estimate` inside a large design loop. Importing and inspecting
the experiment can be slow. Save the reference design and the command's reported
duration and reward, then extrapolate the remaining scenarios mathematically.

When designs differ only in participant count, the calculation is direct:

```python
results["participant_payment"] = (
    results["n_participants"] * reward_per_participant
)
```

When trial count also varies, use the trial's declared time estimate and the
configured hourly wage to separate fixed and per-trial payment. If the reference
design contains `reference_trials` trials:

```python
reward_per_trial = trial_seconds * wage_per_hour / 3600
fixed_reward = (
    reference_reward - reference_trials * reward_per_trial
)


def reward_per_participant(n_trials):
    return fixed_reward + n_trials * reward_per_trial
```

Use the experiment's actual timeline structure when trials do not all have the
same time estimate or when alternative routes differ. Re-run `psynet estimate`
after material timeline changes; it is not necessary to rerun it for every
participant count.

Store the reference command output or its parsed values in `power/run.json`.
State the currency and whether the plotted total includes attrition inflation,
performance bonuses, recruiter fees, or other costs. Do not invent these values;
include them only when the user supplies an assumption or the experiment defines
them.
