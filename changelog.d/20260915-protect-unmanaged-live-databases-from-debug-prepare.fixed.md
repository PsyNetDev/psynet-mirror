Fixed local database protection so ``psynet debug local`` and ``psynet prepare``
no longer discard an unmanaged live or sandbox database, including databases
whose deployment IDs do not encode a recognized mode.
