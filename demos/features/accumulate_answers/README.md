# README

By default each page stores its own answer, but sometimes you want several pages
to contribute to a single dictionary instead. Setting `accumulate_answers=True`
on a `PageMaker` or trial class merges those responses under their page labels
(repeating the same label yields `dog`, `dog_1`, `dog_2`, and so on). This demo
walks through three cases: a plain multi-page maker, a static trial with
kindness/bravery ratings, and a `for_loop` that repeats the same question.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
