`dev-lucid-recruiter` (`get_lucid_settings(debug_recruiter=True)`) now
simulates Lucid: it logs survey and respondent requests instead of sending
them, so local runs and deployments with it no longer create, change or close
a real survey, and no longer need Lucid credentials. Previously it created a
real survey on launch, which went live on the marketplace in a live deployment
with `publish_experiment = true`. The dashboard's Lucid status buttons also no
longer fail before the first Lucid status has been recorded, and the dev
recruiter's status no longer breaks the recruiter status check every minute.
