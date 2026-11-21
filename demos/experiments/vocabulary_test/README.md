# Vocabulary test

Vocabulary tests ask participants whether each word is real or made up. This
demo runs three: Dutch WikiVocab, Dutch BibleVocab and English WikiVocab. Each
form shows equal numbers of real and fake words. The Dutch BibleVocab form
repeats four words to check that participants answer consistently. The
English test has two forms and gives feedback after each one.

## Data

Each word is a static node, and every time a word is shown, including a
repeat, PsyNet saves a trial. On each trial, `answer` is the participant's
choice (`"real"` or `"fake"`), `time_taken` is the response time in seconds
and `score` says whether the choice was correct. Within one run of a test
(one `module_state_id`), `position` gives the order of presentation, and
trials with the same `node_id` are repeats of the same word. Each form is
`n_items + n_repeat_items` consecutive trials.

## How it works

Every word's page has the same HTML, so the browser keeps the page and the
page script `vocabtest.js` only swaps in the next word. The tests prepare each
participant's words in advance, so the next word appears after the lag without
waiting for the server, and the next images are fetched while the participant
answers. Answers go to the server in the background, one at a time.

## Interruptions

If the participant reloads or disconnects, the form continues from the first
unanswered word. The response deadline for that word doesn't restart, and
`time_taken` runs from when the word last appeared on screen.

See the [PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/) for run instructions.
