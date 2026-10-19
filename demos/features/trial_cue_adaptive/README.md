# README

Shows participant-level adaptation with `Trial.cue` rather than a trial maker.
A 1-up/1-down staircase picks the next integer difficulty, records each
assignment in a decision table, and stops after two reversals or eight trials.

Selection and stopping live in `adaptive_logic.py` so they can be tested
without starting PsyNet. `experiment.py` only maps that policy onto a
`while_loop`.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
