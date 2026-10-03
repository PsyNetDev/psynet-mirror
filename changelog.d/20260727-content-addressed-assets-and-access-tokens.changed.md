Changed managed assets to SHA-256 content-addressed ``objects/sha256/<digest>``
storage with permanent ``/asset/<access_token>`` URLs, and removed the
``obfuscate`` flag. Exported archives materialize those bytes under semantic
``export_path`` trees with ``assets/manifest.csv``. Generated assets are hashed
after their content has been prepared.
