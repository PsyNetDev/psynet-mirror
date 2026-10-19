"""1-up/1-down staircase policy with no PsyNet or SQLAlchemy imports."""

ITEMS = (1, 2, 3, 4, 5, 6, 7)
START = 4
MAX_TRIALS = 8
MAX_REVERSALS = 2


def select_difficulty(history):
    """Return the next integer difficulty from prior yes/no outcomes."""
    if not history:
        return START
    last = history[-1]
    step = 1 if last["correct"] else -1
    return min(max(ITEMS[0], last["difficulty"] + step), ITEMS[-1])


def n_reversals(history):
    """Count direction changes between successive administered difficulties."""
    signs = []
    for previous, current in zip(history, history[1:]):
        delta = current["difficulty"] - previous["difficulty"]
        if delta:
            signs.append(1 if delta > 0 else -1)
    return sum(left != right for left, right in zip(signs, signs[1:]))


def should_stop(history):
    """Stop after a trial cap or enough reversals, whichever comes first."""
    return len(history) >= MAX_TRIALS or n_reversals(history) >= MAX_REVERSALS
