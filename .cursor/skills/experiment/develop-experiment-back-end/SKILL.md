---
name: develop-experiment-back-end
description: Choose the trial architecture (static, chain, or graph trial maker, or Trial.cue) and write the timeline, trials, stimulus manifests, and experiment logic of a PsyNet experiment faithfully to its design. Use when writing or changing experiment.py logic.
---

# Develop experiment back end

## Read first

Read these pages before acting. Get the docs folder once with `psynet docs path`, then read `<folder>/<page>.txt` (or `.rst` in a source checkout) and search with `rg -n -i --no-ignore "<term>" <folder>`. If there is no local copy, fetch the pages from the website URL that `psynet docs path` prints.

- `design/trials` and `design/chains`: trials, nodes, and chains as design concepts
- `code/writing_a_timeline`: timelines, code blocks, loops, and variables
- `code/writing_a_trial_maker`: static trial makers, scoring, and `Trial.cue`
- `code/writing_a_chain_experiment`: chain and graph trial makers
- `code/project/experiment_directory`: experiment files and importing sibling modules
- `code/using_stimuli`: `static/` files and assets
- `code/participants/prescreening_and_questionnaires`: volume calibration, headphone tests, and questionnaires
- `test/backend`: bots and `test_check_bot`

## Choose the trial architecture

Decide how trials are chosen before writing code, and record the choice and
its reason in the plan:

- `StaticTrialMaker`: a fixed bank of nodes whose responses should be
  balanced across participants.
- `ChainTrialMaker` or one of its built-in paradigms (imitation chains,
  Gibbs, MCMCP): nodes that evolve from earlier responses. Use
  `GraphChainTrialMaker` when chains form a graph of vertices and edges
  rather than a single line.
- `Trial.cue` inside timeline loops: complex ordering, custom adaptive
  selection, or a space of trial configurations too large to store as nodes
  (for example, random draws of several items from a large bank). For
  adaptive designs, also read `make-experiment-adaptive/SKILL.md`.

Inspect the closest demo and the trial maker's source before committing to
one (`explore-psynet-repository/SKILL.md`). When participants are grouped or
wait for each other, also read `synchronous-experiments/SKILL.md`.

Keep `experiment.py` for the timeline and experiment class, and put
substantial logic in sibling modules imported as described in
`code/project/experiment_directory`.

## Fidelity

The back-end logic must implement the experiment design exactly. If
something seems very hard to achieve, stop and ask the user rather than
deviate.

## Design defaults

Apply these unless the user's specification says otherwise:

- Add a brief practice phase before scored trials of a nontrivial task.
- Do not add replay controls to memory tasks; relistening changes the task.
- For nontrivial stimulus sets, commit a deterministic manifest (for example
  a JSON file produced by a separate generation script) and read it at
  runtime, rather than sampling or hard-coding stimuli in `experiment.py`.
- For audio tasks, start with volume calibration, enable Next only after the
  stimulus has finished playing, and add the headphone or comprehension checks
  that the task's listening demands call for.
- Build instructions, tables, and lists with `dominate` tags; see
  `code/writing_pages` for how they interact with `Markup`.
- For cross-cultural, multilingual, or international studies, mark
  participant-facing text as you write it (`prepare-for-translation/SKILL.md`).

## Testing

Test throughout. `psynet test local` runs bots end to end; override
`test_check_bot` to assert that the data the design needs was saved. For
audio experiments, use committed or generated demo audio, check that each
file's duration matches the task, document how real stimuli replace the demo
set, and assert that responses are saved against the correct stimulus IDs.
For screenshots or video, use `record-participant-video/SKILL.md` sparingly.
