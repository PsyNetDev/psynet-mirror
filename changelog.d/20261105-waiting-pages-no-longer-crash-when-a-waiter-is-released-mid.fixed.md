Fixed a rare crash in which drawing a waiting page, for example for a `Regrouper` with a deadline, failed with a `KeyError` because another request released one of the waiters at the same moment.
