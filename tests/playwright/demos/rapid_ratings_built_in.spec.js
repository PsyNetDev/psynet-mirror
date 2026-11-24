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
async function responseGate(page) {
  const gate = { held: null, release: null, posted: 0, reject: null };
  gate.hold = ({ reject = null } = {}) => {
    gate.posted = 0;
    gate.reject = reject;
    gate.held = new Promise((resolve) => (gate.release = resolve));
  };
  await page.route("**/response", async (route) => {
    gate.posted += 1;
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

test("built-in rating pages advance while the server's replies are held back", {
  tag: "@inplace-only"
}, async ({ page, context }) => {
  const dir = path.resolve("demos/features/rapid_ratings_built_in");

  await withExperiment(page, context, dir, async (participant) => {
    await completeInitialGateway(participant);
    const gate = await responseGate(participant);
    const next = () => participant.getByRole("button", { name: "Next", exact: true }).click();

    // The instructions page comes straight after the intro, so it is shown
    // while the intro's answer is still on its way.
    gate.hold();
    await next();
    await waitForMainBodyContains(participant, "Rate each picture from 1", STEP_TIMEOUT_MS);
    // Sent once the swap has finished, which may be just after the text shows.
    await expect.poll(() => gate.posted).toBe(1);
    gate.release();
    await next();

    const picture = participant.locator("#prompt-image");
    const rate = (rating) =>
      participant.getByRole("button", { name: String(rating), exact: true }).click();
    const expectPicture = async (name, timeout) => {
      await expect(picture).toHaveAttribute("src", new RegExp(`${name.replace(" ", "-")}\\.svg\\?v=`), {
        timeout
      });
      await expect(picture).toHaveCSS("opacity", "1", { timeout });
    };

    await expectPicture("red circle", STEP_TIMEOUT_MS);

    // Answers go one at a time. Two trials are prepared ahead, so the third
    // answer waits for the server before the fourth trial shows.
    gate.hold();
    await rate(5);
    await expectPicture("orange triangle");
    await rate(4);
    await expectPicture("yellow star");
    await rate(3);
    expect(gate.posted).toBe(1);
    gate.release();
    await expectPicture("green square", STEP_TIMEOUT_MS);
    await rate(2);
    await waitForMainBodyContains(participant, "Take a short break.", STEP_TIMEOUT_MS);
    await next();

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
    await expectPicture("teal hexagon", STEP_TIMEOUT_MS);

    for (const name of ["blue diamond", "purple ring", "pink cross"]) {
      await rate(1);
      await expectPicture(name, STEP_TIMEOUT_MS);
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
