Fixed local shutdown so a database whose ID does not match the current
command is still snapshotted under the owning experiment before aborting.
