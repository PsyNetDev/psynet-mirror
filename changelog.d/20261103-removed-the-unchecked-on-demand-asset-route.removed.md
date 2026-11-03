Removed the `/on-demand-asset?id=…&secret=…` route, which redirected any asset ID to its `/asset/<token>` URL without checking the secret; on-demand assets are served only at `/asset/<access_token>`.
