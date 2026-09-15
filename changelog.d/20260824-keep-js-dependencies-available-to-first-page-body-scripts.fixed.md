Keep ``js_dependencies`` available to first-page body scripts by emitting them
as blocking head tags, while still routing failed loads through the guarded
loader so missing files show the refresh prompt.
