Removed the Asset ``personal`` flag.

Passing ``personal=...`` to asset constructors, the ``asset()`` helper, or
recording controls now raises an informative error. Selected assets are always
exported when requested; treat exported media as potentially identifying.
