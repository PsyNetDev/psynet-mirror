WikiVocab and BibleVocab now save one prepared static trial for each word presentation.
The test constructors still take form counts, sizes, and per-form screening thresholds.
For new exports, read the real/fake choice from each trial’s `answer` and response
time in seconds from `time_taken`. Within each `module_state_id`, use `position` for
order and `node_id` to pair repeated words. Older exports retain their form-level
answer lists. Word images are generated on demand from node assets.
