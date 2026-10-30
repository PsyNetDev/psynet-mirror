#!/bin/sh
# Entrypoint of the Playwright CI image: start a PulseAudio server whose only
# output is a null sink, then run the given command.
#
# Containers have no sound card. Without an audio output, Firefox never lets
# an AudioContext leave the "suspended" state, so every page that plays audio
# waits forever. A null sink accepts the audio and discards it.
set -eu
pulseaudio --daemonize --exit-idle-time=-1 --log-target=stderr --log-level=error \
    --load="module-null-sink sink_name=null" 2>/dev/null || true
exec "$@"
