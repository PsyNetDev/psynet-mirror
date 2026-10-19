Warn at page construction when ``js_vars`` keys collide with existing
``window`` properties such as ``name``, ``status``, ``event``, and ``history``,
so legacy global reads cannot silently return the browser's value.
