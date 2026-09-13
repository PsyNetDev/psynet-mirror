# Linux participant recording

Use X11/Xvfb screen capture plus PulseAudio/PipeWire monitor audio. Prefer a
dedicated display or window size so the recording contains only the experiment.

```bash
ffmpeg -y \
  -video_size 1280x720 -framerate 30 -f x11grab -i "$DISPLAY" \
  -f pulse -i "$(pactl get-default-sink).monitor" \
  -t 180 -vf "scale='trunc(min(1,min(1280/iw,720/ih))*iw/2)*2':'trunc(min(1,min(1280/iw,720/ih))*ih/2)*2',fps=15" \
  -c:v libx264 -preset medium -crf 32 -pix_fmt yuv420p \
  -c:a aac -b:a 96k -movflags +faststart -shortest \
  audit/artifacts/participant.mp4
```

If PulseAudio is unavailable, inspect the available audio inputs and choose the
browser/system monitor source:

```bash
pactl list short sources
```

If no PulseAudio/PipeWire source is exposed in Cursor Cloud, create a PulseAudio
null sink and route the browser through it:

```bash
sudo apt-get update
sudo apt-get install -y pulseaudio pulseaudio-utils

export XDG_RUNTIME_DIR="/tmp/xdg-runtime-$UID"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
pulseaudio --start --exit-idle-time=-1 --log-target=stderr || true
pactl load-module module-null-sink sink_name=psynet_rec \
  sink_properties=device.description=psynet_rec || true
pactl set-default-sink psynet_rec
pactl list short sources
```

Launch Chrome or the scripted browser with the same PulseAudio environment so
WebAudio output is routed into the sink:

```bash
export PULSE_SERVER="unix:$XDG_RUNTIME_DIR/pulse/native"
google-chrome --no-first-run --new-window --window-size=1280,720 "$PARTICIPANT_URL"
```

If Chrome was already open before the sink was created or before `PULSE_SERVER`
was exported, do not reuse that window for audio evidence. Launch a fresh browser
profile from the routed environment; otherwise the recording can contain a valid
but silent audio track.

Record the screen and the null-sink monitor:

```bash
ffmpeg -y \
  -video_size 1280x720 -framerate 30 -f x11grab -i "$DISPLAY" \
  -f pulse -i psynet_rec.monitor \
  -t 180 -vf "scale='trunc(min(1,min(1280/iw,720/ih))*iw/2)*2':'trunc(min(1,min(1280/iw,720/ih))*ih/2)*2',fps=15" \
  -c:v libx264 -preset medium -crf 32 -pix_fmt yuv420p \
  -c:a aac -b:a 96k -movflags +faststart -shortest \
  audit/artifacts/participant.mp4
```

For audio-sensitive recordings in Cursor Cloud, prefer an isolated display and
dedicated sink, then calibrate the recording:

1. Start a fresh Xvfb display and PulseAudio null sink for the recording.
2. Launch only the participant browser on that display and route it to that sink.
3. Record with large input queues and a low-latency x264 preset:

```bash
ffmpeg -y \
  -thread_queue_size 4096 \
  -video_size 1280x720 -framerate 30 -f x11grab -i "$DISPLAY" \
  -thread_queue_size 4096 -isync 0 -f pulse -i psynet_rec.monitor \
  -t 180 \
  -fps_mode cfr \
  -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p \
  -c:a aac -shortest \
  audit/artifacts/participant_raw.mp4
```

4. Before publishing the participant recording, run a short sync probe in the
   same browser/display/sink that flashes the screen and plays a beep from the
   same JavaScript callback.
5. Measure the flash/beep offset from the resulting MP4. If audio is early or
   late, post-process the participant recording using the measured offset, for
   example:

```bash
ffmpeg -y -i audit/artifacts/participant_raw.mp4 \
  -t 180 \
  -filter_complex "[0:v]scale='trunc(min(1,min(1280/iw,720/ih))*iw/2)*2':'trunc(min(1,min(1280/iw,720/ih))*ih/2)*2',fps=15[v];[0:a]adelay=<delay_ms>|<delay_ms>[a]" \
  -map "[v]" -map "[a]" \
  -c:v libx264 -preset medium -crf 32 -pix_fmt yuv420p \
  -c:a aac -b:a 96k -movflags +faststart \
  audit/artifacts/participant.mp4
```

6. Save the sync-probe analysis logs with the evidence. Do not hard-code a
   delay from a previous run; measure it for the current recording environment.

Verify that the MP4 really has a non-silent audio stream:

```bash
ffprobe -hide_banner -show_streams audit/artifacts/participant.mp4
ffmpeg -hide_banner -i audit/artifacts/participant.mp4 \
  -af volumedetect -vn -sn -dn -f null /tmp/volumedetect-null
```

