Removed `psynet export --legacy`. The old engine downloaded the raw database,
replaced the contents of the local database with it, and rebuilt the export
locally. Use the default server-built export, or `psynet load` if you
intentionally want to replace the local database. Existing positional calls to
``ArtifactStorage.download_export`` remain supported with a deprecation warning.
