`dev-lucid-recruiter`, which `get_lucid_settings(debug_recruiter=True)`
selects for `psynet debug local`, now simulates Lucid: the server logs survey
and respondent requests instead of sending them. Local runs no longer create a
real Lucid survey and no longer need Lucid credentials, and a deployment that
sets `recruiter = dev-lucid-recruiter` no longer publishes a real survey on the
marketplace. The dev recruiter's status also no longer breaks the recruiter
status check every minute.
