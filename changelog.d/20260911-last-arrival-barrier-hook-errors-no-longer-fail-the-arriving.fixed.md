Last-arrival ``on_release`` and spec errors now roll back that check and log, instead of failing the arriving participant. The group stays waiting so the poller can retry.
