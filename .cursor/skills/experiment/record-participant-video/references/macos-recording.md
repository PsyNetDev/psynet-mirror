# macOS participant recording

Use `ffmpeg` with `avfoundation`. macOS usually needs a virtual audio device
such as BlackHole 2ch to capture browser/system audio.

1. Route browser or system output to BlackHole, or another configured virtual
   audio device.
2. List available capture devices:

```bash
ffmpeg -f avfoundation -list_devices true -i ""
```

1. Record using the selected screen and audio device:

```bash
ffmpeg -y \
  -f avfoundation -framerate 30 -i "1:BlackHole 2ch" \
  -t 180 -vf "scale='trunc(min(1,min(1280/iw,720/ih))*iw/2)*2':'trunc(min(1,min(1280/iw,720/ih))*ih/2)*2',fps=15" \
  -c:v libx264 -preset medium -crf 32 -pix_fmt yuv420p \
  -c:a aac -b:a 96k -movflags +faststart \
  audit/artifacts/participant.mp4
```

The screen device index may differ between machines. Use the device list rather
than assuming `1` is correct.

