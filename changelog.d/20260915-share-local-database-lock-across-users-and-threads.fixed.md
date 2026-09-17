Fixed the local deployment database lock so it is shared across users on
the same machine, world-writable so those users can take the lock, and so
nested calls cannot let a second thread into the critical section.
