Fixed vocabulary tests so chosen item hashes stay on the trial after
creation. Item selection now happens in ``VocabTrial.finalize_definition``.
``VocabTest`` rejects synchronized groups, which would otherwise assign
followers a different item set.
