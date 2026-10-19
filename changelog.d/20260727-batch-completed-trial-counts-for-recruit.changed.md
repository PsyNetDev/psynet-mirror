Batched completed-trial counting in ``ChainTrialMaker.n_trials_still_required``
via ``count_completed_trials_for_networks``, avoiding one query per network when
evaluating the ``n_trials`` recruit criterion.
