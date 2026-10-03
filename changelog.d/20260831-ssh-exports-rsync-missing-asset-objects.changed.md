SSH command-line exports copy missing local-storage asset objects with one rsync
into a persistent content-addressed cache, so repeat exports transfer only new
objects. If rsync is unavailable, fails, or cannot supply every requested object,
the export falls back to a complete server-built archive rather than failing or
publishing an incomplete result.
