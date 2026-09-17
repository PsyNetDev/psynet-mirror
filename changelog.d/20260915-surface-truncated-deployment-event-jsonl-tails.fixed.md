Surface a truncated final line in ``data/deployment-events.jsonl`` as a
``log.truncated`` history event, including a split UTF-8 sequence, and start
the next append on a new line so a later valid event is not concatenated onto
the damaged tail.
