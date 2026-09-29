---
name: participant-response-models
description: Build the shared response_model/ package that generates simulated PsyNet participant answers from scientific assumptions, and wire it into bots. Use when bots need realistic answers or a design simulation needs synthetic data; it does not run simulations or choose sample sizes (see power-analysis).
---

# Participant response models

This skill builds one response model that bots, design simulations and
standalone adaptive simulations all import. It stops at a tested model and
bot adapter; `power-analysis` and `simulate-participants` use it.

What a response model is, and how it differs from the estimator and the
adaptive learner, is explained in "Response models" of
[power-analysis/references/design-simulation-method.md](../power-analysis/references/design-simulation-method.md).
The package layout, `sample_responses` and the bot adapter are in "Response
model package" and "Bot adapter" of
[power-analysis/references/design-simulation-setup.md](../power-analysis/references/design-simulation-setup.md).

## Read first

Read these pages before acting. Get the docs folder once with `psynet docs path`, then read `<folder>/<page>.txt` (or `.rst` in a source checkout) and search with `rg -n -i "<term>" <folder>`. If there is no local copy, fetch the pages from the website URL that `psynet docs path` prints.

- `test/backend` — how bots answer, and `psynet audit simulate`
- `test/audits` — where design simulation sits in an audit

## Procedure

1. **Agree the model with the user.** Describe in task terms how a
   response arises (for example participant level plus condition effect plus
   noise, rounded to the scale), list every parameter with its value and
   source (pilot data, literature, or judgment), and name any alternative
   parameter sets with stable keys.
2. **Write `response_model/`** as in the setup reference: a frozen
   dataclass of parameters, one vectorized `sample_responses(...)` with an
   explicit NumPy generator, the response control's rounding and clipping
   inside it, and re-exports in `__init__.py`. It must not import PsyNet or
   touch the database. Split into more modules only when the model is large.
3. **Add the bot adapter** near the trial code: draw participant-level
   values in `Experiment.initialize_bot`, call `sample_responses` with
   one-element arrays, and only reshape the output into the page's answer.
   Do not repeat the expectation, noise, rounding or clipping there. Store
   the parameter-set key or values in `bot.var` so the export records them.
4. **Keep roles separate.** Do not reuse the response model as the
   estimator or adaptive learner, even when they share formulas.
5. **Validate**: a fixed seed reproduces the same responses; array inputs
   return one response per trial and broadcast as intended; at least one
   response passes through both `sample_responses` and the bot adapter with
   the same formatting, rounding and clipping. Run `psynet test local`.
6. **Hand back** the parameter table with sources and the list of
   judgment-based values, so the user can review them before a design
   simulation depends on them.
