"""Shared HTTP caching policy for content-addressed resources."""

IMMUTABLE_CACHE_MAX_AGE = 365 * 24 * 60 * 60
IMMUTABLE_CACHE_CONTROL = f"public, max-age={IMMUTABLE_CACHE_MAX_AGE}, immutable"
