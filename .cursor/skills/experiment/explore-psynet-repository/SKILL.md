---
name: explore-psynet-repository
description: Find the PsyNet demo, documentation page and source code closest to an experiment, whether PsyNet was installed with pip or from a source checkout. Use before starting a new experiment or when looking for an example of a PsyNet feature.
---

# Explore PsyNet repository

## Read first

Read these pages before acting. Get the docs folder once with `psynet docs path`, then read `<folder>/<page>.txt` (or `.rst` in a source checkout) and search with `rg -n -i --no-ignore "<term>" <folder>`. If there is no local copy, fetch the pages from the website URL that `psynet docs path` prints.

- `code/project/agentic_programming` — implementing an experiment with a coding agent
- `code/project/creating_an_experiment` — creating an experiment directory from a demo
- `demos/index` — what every demo shows, with links to its code

## Finding demo code

The demos live in the `demos/` directory of the PsyNet repository:

- `demos/experiments/` for complete experiments;
- `demos/features/` for focused feature examples;
- `demos/pipelines/` for end-to-end pipelines for common paradigms.

Pick a demo from `demos/index`, then read its code in one of these ways:

- Run `psynet docs demos` once and read the demo under the printed folder, for
  example `<folder>/features/headphone_test/experiment.py`. Search all demos
  with `rg -n --no-ignore "<term>" <folder>`. Release installs bundle the
  demos' code and text files for the installed version, but not their media or
  vendored libraries; in a source checkout the folder is the repository's
  `demos/`.
- If `psynet docs demos` reports no local copy (for example in a Git install),
  open the demo's GitLab tree link from `demos/index`, for example
  `https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/headphone_test`.
  Fetch single files from the raw URL, for example
  `https://gitlab.com/PsyNetDev/PsyNet/-/raw/master/demos/features/headphone_test/experiment.py`.
  Replace `master` with `v<version>` to match `psynet --version`.
- Use a local clone of `https://gitlab.com/PsyNetDev/PsyNet` if one exists
  (often `~/PsyNet`), or clone one when the user agrees. A clone is optional,
  but it makes it easy to search all demos and the PsyNet source at once.

When starting a new experiment, copy the closest demo's authored files into a
new directory, then prefer `psynet setup` over hand-written boilerplate. Details
live in `implement-experiment/SKILL.md` (Setup).

## Useful demos

- `demos/experiments/hello_world` for a minimal experiment.
- `demos/experiments/simple_audio_rating` for static trials, audio prompts, and
  rating controls.
- `demos/experiments/timeline` for timeline control flow, modules, variables,
  conditional logic, and custom routes.
- `demos/features/color_vocabulary` for prescreening and bot checks.
- `demos/features/headphone_test` for headphone prescreeners with a bot that
  fails them.
