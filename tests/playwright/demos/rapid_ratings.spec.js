const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertNoBackendError,
  completeInitialGateway,
  waitForMainBodyContains,
  withExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;

// hold() delays /response requests until release() is called; with
// {reject: message}, the first held request is answered with that rejection.
// eventLogs records the length of each submitted metadata.event_log.
async function responseGate(page) {
  const gate = { held: null, release: null, posted: 0, reject: null, eventLogs: [] };
  gate.hold = ({ reject = null } = {}) => {
    gate.posted = 0;
    gate.reject = reject;
    gate.held = new Promise((resolve) => (gate.release = resolve));
  };
  await page.route("**/response", async (route) => {
    gate.posted += 1;
    const json = route.request().postData().match(/name="json"\r\n\r\n(.*)\r\n/);
    gate.eventLogs.push(JSON.parse(json[1]).metadata.event_log.length);
    await gate.held;
    if (gate.reject) {
      const message = gate.reject;
      gate.reject = null;
      await route.fulfill({ json: { submission: "rejected", message } });
    } else {
      await route.continue();
    }
  });
  return gate;
}

test("ratings advance while the server's replies are held back", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const dir = path.resolve("demos/features/rapid_ratings");

  await withExperiment(page, context, dir, async (participant) => {
    await completeInitialGateway(participant);
    await participant.getByRole("button", { name: "Next", exact: true }).click();
    const picture = participant.locator("#picture");
    const rate = (rating) =>
      participant.getByRole("button", { name: String(rating), exact: true }).click();
    const expectPicture = (name, timeout) =>
      expect(picture).toHaveAttribute("alt", name, { timeout }).then(() =>
        expect(picture).toBeVisible()
      );

    await expectPicture("red circle", STEP_TIMEOUT_MS);
    // A full page load gets its layout key from the page, not a fragment.
    await participant.reload();
    await expectPicture("red circle", STEP_TIMEOUT_MS);
    const gate = await responseGate(participant);

    // Answers go one at a time; the break before the fifth trial stops the
    // prediction after "green square".
    gate.hold();
    await rate(5);
    await expectPicture("orange triangle");
    await rate(4);
    await expectPicture("yellow star");
    await participant.keyboard.press("3");
    await expectPicture("green square");
    await rate(2);
    expect(gate.posted).toBe(1);
    gate.release();
    await waitForMainBodyContains(participant, "Take a short break.", STEP_TIMEOUT_MS);
    // Each answer carries only its own trial's events.
    const [first, ...later] = gate.eventLogs;
    expect(later).toHaveLength(3);
    expect(Math.max(...later)).toBeLessThan(first);
    await participant.getByRole("button", { name: "Next", exact: true }).click();

    // A rejected answer brings its trial back and drops the later answers.
    await expectPicture("teal hexagon", STEP_TIMEOUT_MS);
    gate.hold({ reject: "Please try again." });
    await rate(1);
    await expectPicture("blue diamond");
    await rate(1);
    await expectPicture("purple ring");
    gate.release();
    await expect(participant.locator("#alert-message")).toHaveText("Please try again.", {
      timeout: STEP_TIMEOUT_MS
    });
    await participant.locator("#alert-button").click();
    await expectPicture("teal hexagon");

    for (const next of ["blue diamond", "purple ring", "pink cross"]) {
      await rate(1);
      await expectPicture(next);
    }
    await rate(5);
    await waitForMainBodyContains(
      participant,
      "Your ratings: red circle 5, orange triangle 4, yellow star 3, green square 2, " +
        "teal hexagon 1, blue diamond 1, purple ring 1, pink cross 5.",
      STEP_TIMEOUT_MS
    );
    await assertNoBackendError(participant);
  });
});
