Remote data exports are now built entirely by the deployed experiment and
streamed to your computer, rather than being reconstructed locally. Your local
database is no longer wiped and repopulated, your local experiment code is no
longer executed against remote data, and archives are streamed to disk instead
of being held in memory, so exporting a large deployment no longer depends on
how much RAM your computer has.

For SSH deployments whose assets live in local storage, PsyNet streams a small
core snapshot and then fetches only the asset objects your computer is missing,
so re-exporting an experiment whose recordings have not changed transfers almost
nothing. Deployments that PsyNet cannot transfer that way (Heroku, S3-backed
assets, or a missing `rsync`) automatically fall back to a complete
server-built archive, and the command says which transport it used.
`psynet export local` builds the export directly from your local deployment's
database instead of downloading it from its own dashboard.
