The local database lock now follows the database URL, so experiments on different databases, including parallel CI slots, no longer wait on each other. One database still has a single shared lock.
