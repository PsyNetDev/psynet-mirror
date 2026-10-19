Replaced trial assignment hooks ``find_networks``, ``find_node``, and
``prioritize_networks`` with paradigm-specific APIs. Chain trial makers use
``find_chains``, ``select_chain``, and ``custom_chain_filter``; static trial
makers use ``find_nodes``, ``select_node``, and ``custom_node_filter``.
Selection hooks receive a nonempty eligible list and may return the selected
value or ``Selection(value, context)``. Returning ``None`` from
``select_chain`` or ``select_node`` raises ``TypeError``. ``find_chains`` and
``find_nodes`` must return a list, ``"wait"``, or ``"exit"``; ``None`` raises
``TypeError``. The selected object must be one of the supplied eligible values
(object identity); a re-queried copy with the same id raises ``ValueError``. ``get_trial_class``
must return a trial class for every eligible selection; synchronized followers
reuse their leader's concrete trial class without calling this hook again.
PsyNet raises an actionable ``TypeError`` at construction when a removed or
wrong-paradigm hook is overridden. ``CreateAndRateTrialMakerMixin`` no longer
provides ``get_non_failed_creations``; classify nodes with
``get_creation_phases`` and load finalized creations with
``get_finished_creations``. Heads that still have unfinalized creator
trials wait or exit instead of raising. ``Trial.position`` is now a stored,
zero-based creation sequence shared across all trial classes in a participant's
trial maker, rather than a live index within each concrete trial class.
