# Vocabulary test

The demo presents Dutch WikiVocab, Dutch BibleVocab, and English WikiVocab.
Each form samples equal numbers of real and fake words. The Dutch BibleVocab
form repeats four words to score consistency. The English test has two forms
and gives feedback after each one.

Each word is a static node. Each presentation, including a repeat, has its own
trial row. Read `answer` for the real/fake choice, `time_taken` for the response
time in seconds, and `score` for accuracy. Within a module run, `position` gives
the presentation order and `node_id` identifies repeated presentations. A form
contains `n_items + n_repeat_items` consecutive trials.

See the [PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/) for run instructions.
