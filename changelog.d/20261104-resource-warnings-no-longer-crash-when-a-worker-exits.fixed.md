Fixed a `psutil.ZombieProcess` traceback from the RAM and CPU usage warnings when a worker process exits while they list workers, for example when stopping `psynet debug local` with Ctrl+C.
