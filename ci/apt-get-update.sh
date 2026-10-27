#!/bin/sh
# Run `apt-get update` with a time limit and retries.
#
# CI image builds sometimes cannot reach deb.debian.org for minutes at a time.
# Plain `apt-get update` then either hangs on one InRelease fetch until the
# 3-hour job timeout, or gives up with warnings but exit status 0, so the
# following `apt-get install` fails with "Unable to locate package". Here
# each attempt is time-limited and any failed fetch is an error, so both
# cases are retried and the build fails within minutes if the mirror stays
# unreachable.
set -eu

attempts=3
attempt=1
while ! timeout --kill-after=10 300 apt-get update --error-on=any; do
    if [ "$attempt" -ge "$attempts" ]; then
        echo "apt-get update failed after $attempts attempts" >&2
        exit 1
    fi
    echo "apt-get update failed (attempt $attempt of $attempts); retrying in 30 s" >&2
    attempt=$((attempt + 1))
    sleep 30
done
