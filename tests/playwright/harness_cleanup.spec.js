const path = require("path");
const { test, expect } = require("./fixtures");
const { startExperiment } = require("./psynetHarness");

// A test that times out never reaches its own stopExperiment. Leaving the
// server running stands in for that: the fixture must stop it before the
// next test, or that test's server would find the port taken.
let leftover = null;

test.describe.configure({ mode: "serial" });

test("a test leaves its server running", { tag: "@both" }, () => {
  const experiment = startExperiment(path.resolve("demos/experiments/survey_js"));
  experiment.urlPromise.catch(() => {});
  leftover = experiment.proc;
  expect(leftover.exitCode).toBeNull();
  expect(leftover.signalCode).toBeNull();
});

test("the leftover server is stopped before the next test", { tag: "@both" }, () => {
  expect(leftover).not.toBeNull();
  expect(leftover.exitCode !== null || leftover.signalCode !== null).toBe(true);
});
