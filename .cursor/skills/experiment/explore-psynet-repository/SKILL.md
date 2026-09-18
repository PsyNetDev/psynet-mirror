---
name: explore-psynet-repository
description: Explore the local PsyNet source, demos, feature examples, documentation, and setup guidance.
---

# Explore PsyNet repository

## PsyNet source code

It is essential that you have access to the local PsyNet source code and demos.
Ensure you have a source code repository available at `~/PsyNet`
(if necessary, clone it from `https://gitlab.com/PsyNetDev/PsyNet`).

Useful starting points:

- `~/PsyNet/psynet/` for the PsyNet source code.
- `~/PsyNet/demos/experiments/` for complete experiments (authored files only).
- `~/PsyNet/demos/features/` for focused feature examples.
- `~/PsyNet/docs/` for user-facing documentation.
- `~/PsyNet/docs/experiment_development/agentic_programming.rst` for
  implementing an experiment with a coding agent.
- `~/PsyNet/docs/tutorials/creating_a_new_experiment.rst` for creating an
  experiment directory by copying a demo (prefer `psynet setup`).
- `~/PsyNet/psynet/resources/experiment_scripts/AGENTS.md` for setup and command
  guidance.

When starting a new experiment, copy the closest demo's authored files into a
new directory, then prefer `psynet setup` over hand-written boilerplate. Details
live in `implement-experiment/SKILL.md` (Setup).

## Useful demos

- `~/PsyNet/demos/experiments/hello_world/experiment.py` for a minimal
  experiment.
- `~/PsyNet/demos/experiments/simple_audio_rating/experiment.py` for static
  trials, audio prompts, and rating controls.
- `~/PsyNet/demos/experiments/timeline/experiment.py` for timeline control flow,
  modules, variables, conditional logic, and custom routes.
- `~/PsyNet/demos/features/color_vocabulary/experiment.py` for prescreening and
  bot checks.
