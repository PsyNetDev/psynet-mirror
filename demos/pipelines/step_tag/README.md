# README

This demo shows a collaborative create-and-rate pipeline for tagging stimuli.
Step-tag designs are useful when participants both generate labels and evaluate
others' labels, so the stimulus set accumulates consensus over time. In this
example, people listen to short music clips, propose emotion tags, and rate tags
from others until items freeze. Similar logic could be used for captioning
images, naming categories, or any task where creation and rating are interleaved
across a shared stimulus pool.

This demo currently sets ``inplace_timeline_transitions = False`` because the
external StepTag control still uses a complete template. Remove that opt-out
once ``psynet-step`` follows the fragment-template contract.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
