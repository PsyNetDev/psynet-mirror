Last-arrival Redis pins keep a later owner's token after a stale request's pin expires, so the poller cannot process or publish that visit while the newer request is still rendering.
