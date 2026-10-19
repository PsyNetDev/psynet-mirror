Folder assets deposited into local storage are now stored with predictable
permissions (`0755` directories, `0644` files) instead of inheriting the source
directory's. A folder deposited from a `tempfile.TemporaryDirectory` was
previously stored as `0700`, which stopped anything running as another user
from reading it, including rsync during an SSH export.
