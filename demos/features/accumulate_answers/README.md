# README

By default each page stores its own answer, but sometimes you want several pages
to contribute to a single dictionary instead. Setting `accumulate_answers=True`
on a `PageMaker` or trial class merges those responses under their page labels
(repeating the same label yields `dog`, `dog_1`, `dog_2`, and so on). The
dictionary fills up as each page is submitted, so later pages can read
`participant.answer` to react to earlier ones, and accumulating page makers
nested inside each other share one dictionary. This demo
walks through four cases: a plain multi-page maker, a static trial with
kindness/bravery ratings, a `for_loop` that repeats the same question, and a
nested page maker whose question depends on an earlier answer.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
