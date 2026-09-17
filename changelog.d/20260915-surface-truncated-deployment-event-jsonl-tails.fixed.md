Surface a truncated final line in ``data/deployment-events.jsonl`` as a
``log.truncated`` history event, and start the next append on a new line so a
later valid event is not concatenated onto the damaged tail.
