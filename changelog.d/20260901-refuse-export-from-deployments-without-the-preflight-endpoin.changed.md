Remote ``psynet export`` now stops immediately if the deployment has no
``/dashboard/export/preflight`` endpoint, instead of attempting a download this
client cannot publish. Install the earlier PsyNet (see ``constraints.txt``) and
retry, or export from the dashboard.
