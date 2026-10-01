const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const { test, expect } = require("./fixtures");

const {
  completeInitialGateway,
  waitForMainBodyContains,
  waitForNextEnabled,
  withExperiment
} = require("./psynetHarness");
const {
  startParticipantRecording
} = require("../../.cursor/skills/experiment/record-participant-video/scripts/audio-capture.cjs");

const STEP_TIMEOUT_MS = 120000;

/*
Smoke test for the record-participant-video skill's audio-capture helper.

1. Start a recording page in the test context and open the static_audio demo.
2. Clear the gateway and wait on the volume calibration page, which loops a
   sound and enables Next after 2.5 s of playback.
3. Finish the recording and check that the MP4 is non-empty and has both a
   video and an audio stream.

Intentionally not covered: audio/video synchronization and audio content.
*/

function streamTypes(file) {
  const result = spawnSync(
    "ffprobe",
    ["-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", file],
    { encoding: "utf8" }
  );
  expect(result.status, result.stderr).toBe(0);
  return result.stdout.split("\n").filter(Boolean);
}

test("participant recording helper writes an MP4 with audio", { tag: "@both" }, async ({
  context
}, testInfo) => {
  const absDir = path.resolve("demos/experiments/static_audio");
  const outPath = testInfo.outputPath("participant.mp4");
  const recording = await startParticipantRecording(context, {
    workDir: testInfo.outputPath("recording")
  });

  await withExperiment(recording.page, context, absDir, async (experimentPage) => {
    expect(experimentPage).toBe(recording.page);
    await completeInitialGateway(experimentPage);
    await waitForMainBodyContains(
      experimentPage,
      "Please listen to the following sound",
      STEP_TIMEOUT_MS
    );
    await waitForNextEnabled(experimentPage, STEP_TIMEOUT_MS);

    const summary = await recording.finish(outPath);
    expect(summary.segments.length).toBeGreaterThan(0);
  });

  expect(fs.statSync(outPath).size).toBeGreaterThan(0);
  expect(streamTypes(outPath)).toEqual(expect.arrayContaining(["video", "audio"]));
});
