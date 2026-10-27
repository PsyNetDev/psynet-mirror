#!/usr/bin/env node
// Measure the audio latency correction for startParticipantRecording.
//
// Records sync-probe.html (a white flash with a simultaneous beep every
// second) through audio-capture.cjs, then measures how late each beep is
// relative to its flash in the MP4. Run from the experiment directory so that
// @playwright/test resolves from its node_modules:
//
//   node .cursor/skills/psynet/record-participant-video/scripts/measure-latency.cjs
//
// Options:
//   --seconds N          Probe duration (default 20). Use 180+ to check drift.
//   --navigate-after N   Reload into a second document after N seconds.
//   --latency-ms N       Correction applied while muxing (default 0, i.e. raw).
//   --out DIR            Output directory (default: a temporary directory).
//   --headed             Run a headed browser.
//
// Prints a JSON summary; recommendedLatencyMs is the value to pass as
// PSYNET_AUDIO_LATENCY_MS in this environment.
const { execFileSync } = require("child_process");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const { AUDIO_CAPTURE_LAUNCH_ARGS, startParticipantRecording } = require("./audio-capture.cjs");

const SAMPLE_RATE = 48000;
const ANALYSIS_FPS = 60;

function parseArgs(argv) {
  const args = { seconds: 20, navigateAfter: 0, latencyMs: 0, out: null, headed: false };
  for (let i = 0; i < argv.length; i++) {
    const flag = argv[i];
    const value = () => {
      if (i + 1 >= argv.length) throw new Error(`${flag} needs a value`);
      return argv[++i];
    };
    if (flag === "--seconds") args.seconds = Number(value());
    else if (flag === "--navigate-after") args.navigateAfter = Number(value());
    else if (flag === "--latency-ms") args.latencyMs = Number(value());
    else if (flag === "--out") args.out = path.resolve(value());
    else if (flag === "--headed") args.headed = true;
    else throw new Error(`Unknown option ${flag}`);
  }
  return args;
}

function loadChromium() {
  for (const name of ["@playwright/test", "playwright"]) {
    try {
      return require(require.resolve(name, { paths: [process.cwd(), __dirname] })).chromium;
    } catch (error) {
      if (error.code !== "MODULE_NOT_FOUND") throw error;
    }
  }
  throw new Error("Could not find @playwright/test; run this from a directory with it installed.");
}

function serveProbe() {
  const html = fs.readFileSync(path.join(__dirname, "sync-probe.html"));
  const server = http.createServer((request, response) => {
    response.writeHead(200, { "Content-Type": "text/html" });
    response.end(html);
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

function decode(file, args) {
  return execFileSync("ffmpeg", ["-v", "error", "-i", file, ...args, "-"], { maxBuffer: 1 << 30 });
}

function flashOnsets(file) {
  const pixels = 32 * 18;
  const raw = decode(file, ["-vf", `fps=${ANALYSIS_FPS},scale=32:18,format=gray`, "-f", "rawvideo"]);
  const onsets = [];
  let wasBright = false;
  for (let frame = 0; frame * pixels < raw.length; frame++) {
    let sum = 0;
    for (let i = frame * pixels; i < (frame + 1) * pixels; i++) sum += raw[i];
    const bright = sum / pixels > 128;
    if (bright && !wasBright) onsets.push(frame / ANALYSIS_FPS);
    wasBright = bright;
  }
  return onsets;
}

function beepOnsets(file) {
  const raw = decode(file, ["-ac", "1", "-ar", String(SAMPLE_RATE), "-f", "f32le"]);
  const pcm = new Float32Array(raw.buffer, raw.byteOffset, Math.floor(raw.length / 4));
  const hop = SAMPLE_RATE / 1000;
  const window = 4 * hop;
  const envelope = [];
  for (let start = 0; start + window <= pcm.length; start += hop) {
    let energy = 0;
    for (let i = start; i < start + window; i++) energy += pcm[i] * pcm[i];
    envelope.push(Math.sqrt(energy / window));
  }
  const threshold = 0.25 * envelope.reduce((a, b) => Math.max(a, b), 0);
  const onsets = [];
  let last = -Infinity;
  for (let i = 1; i < envelope.length; i++) {
    const t = i / 1000;
    if (envelope[i] > threshold && envelope[i - 1] <= threshold && t - last > 0.3) {
      onsets.push(t);
      last = t;
    }
  }
  return onsets;
}

function summarise(values) {
  if (!values.length) return { mean: null, sd: null };
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const sd = Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / values.length);
  return { mean: Math.round(mean * 10) / 10, sd: Math.round(sd * 10) / 10 };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const out = args.out || fs.mkdtempSync(path.join(os.tmpdir(), "psynet-sync-probe-"));
  fs.mkdirSync(out, { recursive: true });
  const server = await serveProbe();
  const url =
    `http://127.0.0.1:${server.address().port}/sync-probe.html?seconds=${args.seconds}` +
    (args.navigateAfter ? `&navigateAfter=${args.navigateAfter}` : "");

  const browser = await loadChromium().launch({ headless: !args.headed, args: AUDIO_CAPTURE_LAUNCH_ARGS });
  let summary;
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
    const recording = await startParticipantRecording(context, { workDir: out });
    await recording.page.goto(url);
    await recording.page.waitForFunction(() => window.probeDone === true, null, {
      timeout: (args.seconds + 60) * 1000,
    });
    await recording.page.waitForTimeout(500);
    summary = await recording.finish(path.join(out, "sync-probe.mp4"), {
      latencyMs: args.latencyMs,
      fps: ANALYSIS_FPS,
    });
  } finally {
    await browser.close();
    server.close();
  }

  const flashes = flashOnsets(summary.outPath);
  const beeps = beepOnsets(summary.outPath);
  const pairs = [];
  for (const flash of flashes) {
    const nearest = beeps.reduce((best, b) => (Math.abs(b - flash) < Math.abs(best - flash) ? b : best), Infinity);
    if (Math.abs(nearest - flash) < 0.4) pairs.push({ t: flash, offsetMs: (nearest - flash) * 1000 });
  }
  const offsets = pairs.map((p) => p.offsetMs);
  const all = summarise(offsets);
  const result = {
    video: summary.outPath,
    seconds: args.seconds,
    audioSegments: summary.segments.length,
    appliedLatencyMs: args.latencyMs,
    flashes: flashes.length,
    beeps: beeps.length,
    matched: pairs.length,
    offsetMs: all,
    firstFiveMeanMs: summarise(offsets.slice(0, 5)).mean,
    lastFiveMeanMs: summarise(offsets.slice(-5)).mean,
    framePeriodMs: Math.round((1000 / ANALYSIS_FPS) * 10) / 10,
    recommendedLatencyMs: all.mean === null ? null : Math.round(args.latencyMs + all.mean),
    offsets: pairs.map((p) => [Math.round(p.t * 100) / 100, Math.round(p.offsetMs)]),
  };
  fs.writeFileSync(path.join(out, "sync-probe.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ ...result, offsets: undefined }, null, 2));
  if (!pairs.length) {
    console.error("No flash/beep pairs were matched; inspect the MP4 in", out);
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
