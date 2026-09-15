Replaced auto-loaded trial and network count ``column_property`` attributes with
explicit query helpers.

``TrialNetwork`` no longer defines PsyNet aggregates such as ``n_all_trials`` or
``n_completed_trials`` that ran correlated subqueries on every ORM load. Chain
allocation now uses ``count_viable_trials_for_nodes`` and related helpers.
``ModuleState.n_completed_trials`` remains a stored counter. Also fixed
``TrialNetwork.alive_nodes`` / ``failed_nodes`` to filter by node failure state.
