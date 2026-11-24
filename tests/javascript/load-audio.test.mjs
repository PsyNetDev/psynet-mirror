import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { it } from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SOURCE = fs.readFileSync(
  path.join(ROOT, "psynet/resources/scripts/psynet.js"),
  "utf8"
);
const LOAD_AUDIO = SOURCE.match(
  /psynet\.media\.loadAudio = function[\s\S]*?\n    \};/
)[0];

it("keeps the later sound when two loads share an id", async () => {
  const downloads = {};
  const psynet = {
    audio: {},
    media: {
      data: { audio: {} },
      loadGeneration: 1,
      isCurrentLoadGeneration: () => true,
      initAudioContext() {},
    },
  };
  new Function(
    "psynet",
    "audioLoads",
    "prefetchedData",
    "initMediaType",
    "initStimulus",
    "createAudioStimulus",
    LOAD_AUDIO
  )(
    psynet,
    new Map(),
    (url) => new Promise((resolve) => (downloads[url] = () => resolve(url))),
    () => {},
    () => {},
    async (data, id, generation, isCurrent = () => true) => {
      if (!isCurrent()) return false;
      psynet.audio[id] = data;
      return true;
    }
  );

  const first = psynet.media.loadAudio("/a.wav", "stim");
  const second = psynet.media.loadAudio("/b.wav", "stim");
  downloads["/b.wav"]();
  assert.equal(await second, "/b.wav");
  downloads["/a.wav"]();
  await assert.rejects(first, /replaced by a later load/);
  assert.equal(psynet.audio.stim, "/b.wav");
});
