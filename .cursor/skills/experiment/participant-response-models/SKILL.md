---
name: participant-response-models
description: Define a scientific participant-response model used for experiment testing and simulation.
---

# Participant response models

Participant response models implement hypothesized participant behaviour. They
can generate data for scientific bots, power analyses, and standalone adaptive
simulations. They may also share mathematical components with cognitive models
used for inference.

## Layout

Use this layout unless the model is large enough to justify more modules:

```text
response_model/
├── __init__.py
└── core.py
```

Put parameter definitions, expected responses when useful, and the canonical
`sample_responses(...)` function in `core.py`. Re-export the public interface
from `__init__.py`.

Keep this package at the experiment's top level, separate from `experiment.py`
and `power/`. Import the same package from scientific bots, power analyses, and
standalone adaptive simulations. It must not import PsyNet or access its
database.

## Vectorized interface

Use dataclasses for related model parameters and NumPy arrays for batches of
trials. The exact predictors are experiment-specific; this example illustrates
the interface rather than prescribing a scientific model:

```python
from dataclasses import dataclass

import numpy as np
from numpy.random import Generator


@dataclass(frozen=True)
class ResponseParameters:
    intercept: float = 0.0
    condition_effect: float = 0.4
    trial_noise_sd: float = 1.0


def sample_responses(
    *,
    condition: np.ndarray,
    participant_bias: np.ndarray,
    parameters: ResponseParameters,
    rng: Generator,
) -> np.ndarray:
    expected = (
        parameters.intercept
        + participant_bias
        + parameters.condition_effect * condition
    )
    return expected + rng.normal(
        0.0,
        parameters.trial_noise_sd,
        size=expected.shape,
    )
```

The trial arrays should broadcast explicitly and return one response per input
trial. Pass an explicit NumPy random-number generator rather than using global
random state. If the participant-facing response is discrete or bounded, apply
the same rounding and clipping here that simulated participants should exhibit.

A PsyNet bot uses the same batch function for one trial:

```python
response = sample_responses(
    condition=np.asarray([condition]),
    participant_bias=np.asarray([participant_bias]),
    parameters=parameters,
    rng=rng,
)[0]
```

Keep PsyNet-specific answer formatting in a thin adapter near the page or trial
code. The adapter converts `response` into the expected answer shape; it must not
recreate the expectation, noise, rounding, or clipping logic.

## Parameters and provenance

Keep related parameters together rather than scattering constants through bots
and simulation code. Named parameter sets are useful when the experiment
compares several scientific assumptions; give them stable, descriptive keys.

Record the chosen key or parameter values in bot exports. Power-analysis
`run.json` should record the parameter values and a hash or version identifier
for the response-model code used by the run.

## Relationship to estimation and adaptive learning

The response model generates synthetic responses under assumed behaviour. An
estimator attempts to recover scientific quantities from those responses; an
adaptive learner uses its own assumed model to update beliefs and choose what to
present next. Keep these roles separate even when they share mathematical
components.

In adaptive simulations, the response model may match the learner model or
deliberately differ from it to test robustness to misspecification. In a real
experiment, participants supply the responses; the code does not specify their
"actual response model."

## Validation

Test that a fixed seed reproduces the same responses, vectorized inputs produce
the expected output shape, and broadcasting behaves as intended. Check at least
one response through both the standalone simulation interface and the PsyNet bot
adapter, including answer formatting, rounding, and clipping where applicable.
