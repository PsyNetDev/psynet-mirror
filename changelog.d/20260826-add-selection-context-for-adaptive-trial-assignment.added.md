Added ``Selection`` and ``NetworkTrialMaker.on_trial_created`` so adaptive
experiments can record why a node or chain was assigned. Static ``select_node``
and chain ``select_chain`` hooks may return their selected value directly or
wrap it in ``Selection`` when request-local decision context must reach
``on_trial_created``. The hook runs once per primary policy choice, after the
trial is fully prepared and excluding repeat trials and synchronized follower
copies.
