#!/bin/sh
# Entrypoint of the Playwright CI image: give the browsers an audio output and,
# for headed runs, an X display, then run the given command.
#
# Containers have no sound card. Without an audio output, Firefox never lets
# an AudioContext leave the "suspended" state, so every page that plays audio
# waits forever. A PulseAudio null sink accepts the audio and discards it.
#
# Firefox runs headed (HEADLESS=false), because it can only capture a screen
# on an X display. Xvfb provides one; if it does not come up, fail at once
# with its log rather than leave the browser waiting for a display.
set -eu
pulseaudio --daemonize --exit-idle-time=-1 --log-target=stderr --log-level=error \
    --load="module-null-sink sink_name=null" 2>/dev/null || true

if [ "${HEADLESS:-TRUE}" = false ] && [ -z "${DISPLAY:-}" ]; then
    Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
    export DISPLAY=:99
    tries=0
    until [ -S /tmp/.X11-unix/X99 ]; do
        tries=$((tries + 1))
        if [ "$tries" -gt 100 ]; then
            echo "Xvfb did not start:" >&2
            cat /tmp/xvfb.log >&2
            exit 1
        fi
        sleep 0.1
    done
fi

exec "$@"
