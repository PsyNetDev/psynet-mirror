import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SOURCE = fs.readFileSync(
  path.join(ROOT, "psynet/resources/scripts/psynet.js"),
  "utf8"
);
const code = ["psynet\\.updatePageModules = async", "psynet\\.deactivatePageJavascript = async"]
  .map((name) => {
    const found = SOURCE.match(new RegExp(`${name} function[\\s\\S]*?\\n    \\};`));
    assert.ok(found, `could not extract ${name}`);
    return found[0];
  })
  .join("\n");

function modulePage(update) {
  const psynet = {
    answers: {},
    pageModuleGeneration: 0,
    pageModuleUpdates: [update],
    activeJSPageBehaviors: [],
    predictedContents: () => [{ trial: 1 }],
    createResponseHandle: () => ({}),
  };
  new Function("psynet", code)(psynet);
  return psynet;
}

describe("update()'s signal", () => {
  it("is aborted by the next update() and by leaving the page", async () => {
    const signals = [];
    const psynet = modulePage(({ signal }) => signals.push(signal));
    await psynet.updatePageModules(0);
    await psynet.updatePageModules(0);
    assert.deepEqual(signals.map((s) => s.aborted), [true, false]);
    await psynet.deactivatePageJavascript();
    assert.equal(signals[1].aborted, true);
  });

  it("lets a superseded update() end with an AbortError", async () => {
    let calls = 0;
    const psynet = modulePage(async ({ signal }) => {
      if (++calls > 1) return;
      await new Promise((resolve) => setTimeout(resolve, 10));
      signal.throwIfAborted();
    });
    const first = psynet.updatePageModules(0);
    await psynet.updatePageModules(0);
    await first;
  });
});

describe("sounds", () => {
  it("started with the page belong to its first update(), but not to the next", async () => {
    const psynet = modulePage(() => {});
    const startedWithPage = (psynet.soundScope = {});
    await psynet.updatePageModules(0);
    assert.equal(psynet.soundScope, startedWithPage);
    await psynet.updatePageModules(0);
    assert.notEqual(psynet.soundScope, startedWithPage);
  });
});
