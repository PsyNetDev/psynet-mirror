Added a persistent local asset cache (``~/psynet-data/cache/assets``) that
stores read-only content-addressed objects between export runs; subsequent
exports hardlink cached objects into the export directory instead of
re-fetching from storage, writable cache entries are reverified before reuse,
and new ``psynet assets cache info/list/prune`` commands allow inspection and
manual pruning of the cache.
