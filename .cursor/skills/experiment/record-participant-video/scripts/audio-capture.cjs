// Record a headless Playwright participant walk as an MP4 with audio.
//
//   const { AUDIO_CAPTURE_LAUNCH_ARGS, startParticipantRecording } = require(
//     "../.cursor/skills/psynet/record-participant-video/scripts/audio-capture.cjs",
//   );
//   test.use({ launchOptions: { args: AUDIO_CAPTURE_LAUNCH_ARGS } });
//
//   const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
//   try {
//     const recording = await startParticipantRecording(context);
//     const page = recording.page;
//     // ... drive the participant flow ...
//     await recording.finish("audit/artifacts/participant.mp4");
//   } finally {
//     await context.close();
//   }
//
// Video comes from page.screencast; audio from audio-capture-init.js. Each
// document's audio segment is placed on the video timeline by wall-clock time,
// minus a fixed pipeline latency (see measure-latency.cjs), then mixed,
// limited to -1 dBFS and muxed as H.264/AAC.
const { execFileSync, spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const BINDING = "__psynetAudioCaptureChunk";
const INIT_SCRIPT = path.join(__dirname, "audio-capture-init.js");

/** Chromium flags that let pages start audio without a user gesture. */
const AUDIO_CAPTURE_LAUNCH_ARGS = ["--autoplay-policy=no-user-gesture-required"];

/**
 * Audio pipeline latency subtracted from each segment's start, in ms.
 * Measured with measure-latency.cjs on macOS, Chromium headless shell
 * (Playwright 1.63). Override per environment with PSYNET_AUDIO_LATENCY_MS
 * or the latencyMs option.
 */
const DEFAULT_LATENCY_MS = 100;

function requireFfmpeg() {
  try {
    execFileSync("ffmpeg", ["-hide_banner", "-version"], { stdio: "ignore" });
  } catch (error) {
    if (error.code === "ENOENT") {
      throw new Error(
        "ffmpeg was not found on PATH. Install it (macOS: `brew install ffmpeg`, " +
          "Debian/Ubuntu: `sudo apt-get install ffmpeg`) before recording participant video.",
      );
    }
    throw error;
  }
}

function defaultLatencyMs() {
  const value = process.env.PSYNET_AUDIO_LATENCY_MS;
  if (value === undefined || value === "") return DEFAULT_LATENCY_MS;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    throw new Error(`PSYNET_AUDIO_LATENCY_MS must be a number of milliseconds, got ${value}`);
  }
  return parsed;
}

/**
 * Start recording a participant page with in-page audio capture.
 *
 * @param {import("playwright").BrowserContext} context Fresh browser context.
 *   Launch Chromium with AUDIO_CAPTURE_LAUNCH_ARGS.
 * @param {object} [options]
 * @param {string} [options.workDir] Directory for raw video/audio and
 *   recording.json. Defaults to a new temporary directory.
 * @param {{width: number, height: number}} [options.size] Screencast size.
 *   Defaults to the context viewport, or 1280x720.
 * @returns {Promise<{page: import("playwright").Page, workDir: string,
 *   finish: (outPath: string, options?: object) => Promise<object>}>}
 */
async function startParticipantRecording(context, options = {}) {
  requireFfmpeg();
  const workDir = options.workDir || fs.mkdtempSync(path.join(os.tmpdir(), "psynet-recording-"));
  fs.mkdirSync(workDir, { recursive: true });

  const segments = new Map();
  let page = null;
  await context.exposeBinding(BINDING, (source, message) => {
    if (source.page !== page) return;
    let segment = segments.get(message.segment);
    if (!segment) {
      segment = { url: message.url, startMs: null, chunks: [] };
      segments.set(message.segment, segment);
    }
    if (message.kind === "start") segment.startMs = message.wallMs;
    else if (message.kind === "chunk") segment.chunks[message.seq] = Buffer.from(message.data, "base64");
  });
  await context.addInitScript({ path: INIT_SCRIPT });

  page = await context.newPage();
  if (!page.screencast) {
    throw new Error("startParticipantRecording needs page.screencast; upgrade @playwright/test.");
  }
  const size = options.size || page.viewportSize() || { width: 1280, height: 720 };
  const rawVideo = path.join(workDir, "video.webm");
  const video = { startMs: null };
  await page.screencast.start({
    path: rawVideo,
    size,
    onFrame: ({ timestamp }) => {
      if (video.startMs === null) {
        video.startMs = Number.isFinite(timestamp) ? timestamp : NaN;
      }
    },
  });

  /**
   * Stop recording and write the MP4.
   *
   * @param {string} outPath Output MP4 path, e.g. audit/artifacts/participant.mp4.
   * @param {object} [finishOptions]
   * @param {number} [finishOptions.latencyMs] Audio latency correction in ms.
   * @param {number} [finishOptions.fps] Output frame rate (default 15).
   * @returns {Promise<object>} Recording summary, also saved as recording.json.
   */
  async function finish(outPath, finishOptions = {}) {
    const latencyMs = finishOptions.latencyMs ?? defaultLatencyMs();
    if (!page.isClosed()) {
      await page.evaluate(() => window.__psynetAudioCapture?.flush()).catch((error) => {
        console.warn(`[psynet audio capture] final audio flush failed: ${error.message}`);
      });
      await page.screencast.stop();
    }
    if (video.startMs === null) throw new Error("The screencast produced no frames.");
    if (!Number.isFinite(video.startMs)) {
      throw new Error(
        "Audio synchronization needs Playwright 1.62 or later, which provides screencast frame timestamps.",
      );
    }

    const audioFiles = [];
    const unstarted = [];
    for (const [id, segment] of segments) {
      const chunks = segment.chunks.filter(Boolean);
      if (segment.startMs === null || !chunks.length) {
        unstarted.push(segment.url);
        continue;
      }
      const file = path.join(workDir, `audio-${audioFiles.length}.webm`);
      fs.writeFileSync(file, Buffer.concat(chunks));
      audioFiles.push({ id, url: segment.url, startMs: segment.startMs, file });
    }
    if (unstarted.length) {
      console.warn(
        `[psynet audio capture] ${unstarted.length} page(s) set up audio that was not recorded ` +
          "(the mixing AudioContext never started). Launch Chromium with AUDIO_CAPTURE_LAUNCH_ARGS.",
      );
    }

    fs.mkdirSync(path.dirname(path.resolve(outPath)), { recursive: true });
    muxAudioVideo({
      videoPath: rawVideo,
      videoStartMs: video.startMs,
      segments: audioFiles,
      outPath,
      latencyMs,
      fps: finishOptions.fps ?? 15,
    });
    const summary = { outPath, videoStartMs: video.startMs, latencyMs, segments: audioFiles };
    fs.writeFileSync(path.join(workDir, "recording.json"), JSON.stringify(summary, null, 2));
    return summary;
  }

  return { page, workDir, finish };
}

/**
 * Mux a screencast with audio segments into an MP4.
 *
 * Each segment is delayed (or trimmed) by its start relative to the first
 * video frame, minus latencyMs.
 */
function muxAudioVideo({ videoPath, videoStartMs, segments, outPath, latencyMs = DEFAULT_LATENCY_MS, fps = 15 }) {
  requireFfmpeg();
  const inputs = ["-i", videoPath];
  const filters = [
    "[0:v]scale='trunc(min(1,min(1280/iw,720/ih))*iw/2)*2':'trunc(min(1,min(1280/iw,720/ih))*ih/2)*2'," +
      `fps=${fps}[v]`,
  ];
  segments.forEach((segment, k) => {
    inputs.push("-i", segment.file);
    const offsetMs = Math.round(segment.startMs - videoStartMs - latencyMs);
    const shift =
      offsetMs >= 0
        ? `adelay=${offsetMs}:all=1`
        : `atrim=start=${(-offsetMs / 1000).toFixed(3)},asetpts=PTS-STARTPTS`;
    filters.push(`[${k + 1}:a]aresample=48000:async=1:first_pts=0,${shift}[a${k}]`);
  });
  const audioOutput = [];
  if (segments.length) {
    const mixInputs = segments.map((_, k) => `[a${k}]`).join("");
    // Pad or cut the audio to the video length. (apad with -shortest fails
    // with "No space left on device" in ffmpeg 6.1.)
    const duration = videoDurationSeconds(videoPath);
    const fit = duration ? `,apad=whole_dur=${duration},atrim=end=${duration}` : "";
    // AAC overshoots slightly, so limit the mix to -1 dBFS before encoding.
    filters.push(
      `${mixInputs}amix=inputs=${segments.length}:normalize=0:duration=longest,` +
        `alimiter=limit=0.891:level=disabled${fit}[a]`,
    );
    audioOutput.push("-map", "[a]", "-c:a", "aac", "-b:a", "128k");
  }
  const args = [
    "-hide_banner", "-loglevel", "error", "-y",
    ...inputs,
    "-filter_complex", filters.join(";"),
    "-map", "[v]",
    "-c:v", "libx264", "-preset", "medium", "-crf", "32", "-pix_fmt", "yuv420p",
    ...audioOutput,
    "-movflags", "+faststart",
    outPath,
  ];
  const result = spawnSync("ffmpeg", args, { stdio: ["ignore", "ignore", "pipe"], encoding: "utf8" });
  if (result.error || result.status !== 0) {
    throw new Error(`ffmpeg failed to write ${outPath}:\n${result.stderr || result.error}`);
  }
  printFfmpegMessages(result.stderr);
  return outPath;
}

function videoDurationSeconds(videoPath) {
  const result = spawnSync(
    "ffprobe",
    ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", videoPath],
    { encoding: "utf8" },
  );
  const duration = Number.parseFloat(result.stdout);
  if (result.status === 0 && Number.isFinite(duration) && duration > 0) return duration;
  console.warn("[psynet audio capture] could not read the video duration; audio may end before the video.");
  return null;
}

function printFfmpegMessages(stderr) {
  // A segment left by navigation loses its final chunk (at most 100 ms of audio);
  // the WebM demuxer reports that as a truncated file.
  const lines = stderr.split("\n").filter((line) => line && !line.includes("File ended prematurely"));
  if (lines.length) console.warn(lines.join("\n"));
}

module.exports = {
  AUDIO_CAPTURE_LAUNCH_ARGS,
  DEFAULT_LATENCY_MS,
  muxAudioVideo,
  startParticipantRecording,
};
