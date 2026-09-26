/*
Phone-sized screenshots of demos for the "What's PsyNet for?" gallery.

Each entry launches a demo with `psynet debug local`, steps to a page that
shows the paradigm, and saves docs/_static/images/gallery/<demo>.png, where
<demo> is the path under demos/ with "/" replaced by "__".

Run all of them, or pick some with --grep:

  npx playwright test -c docs/scripts/gallery_screenshots
  npx playwright test -c docs/scripts/gallery_screenshots --grep gibbs
*/
const path = require("path");
const { test, expect } = require("@playwright/test");

const {
  beginExperiment,
  clickNextAndWait,
  completeInitialGateway,
  startExperiment,
  stopExperiment,
  waitForTimelinePageReady,
  withExperiment,
  withFreshParticipantIds
} = require("../../../tests/playwright/psynetHarness");

// Dallinger reads config from the environment; the reward gives each page a footer.
process.env.show_reward = "true";
// A missing chrome-path stops Dallinger opening a Chrome window, and leaving a
// temporary profile behind, for every demo launch.
process.env["chrome-path"] = "/nonexistent";

const REPO = path.resolve(__dirname, "../../..");
const OUTPUT_DIR = path.join(REPO, "docs/_static/images/gallery");
const VIEWPORT = { width: 390, height: 760 };
const TIMEOUT_MS = 120000;

test.setTimeout(240000);

async function next(page) {
  await waitForTimelinePageReady(page, TIMEOUT_MS);
  await clickNextAndWait(page, TIMEOUT_MS);
}

async function visible(locator) {
  await expect(locator.first()).toBeVisible({ timeout: 30000 });
}

async function isShown(locator) {
  return (await locator.count()) > 0 && (await locator.first().isVisible());
}

/** Click through consent, Next and push buttons until ``target`` is visible. */
async function advanceUntil(page, target, maxSteps = 60) {
  for (let i = 0; i < maxSteps; i++) {
    if (await isShown(target)) return;
    const consent = page.locator("#consent");
    const nextButton = page.locator("#next-button");
    const pushButton = page.locator(".push-button:visible");
    if (await isShown(consent)) {
      await consent.click();
    } else if ((await isShown(nextButton)) && (await nextButton.isEnabled())) {
      const radio = page.locator("input[type=radio]:visible");
      if ((await radio.count()) && !(await page.locator("input[type=radio]:checked").count())) {
        await radio.first().check();
      }
      await nextButton.click();
    } else if (await isShown(pushButton)) {
      await pushButton.first().click();
    }
    await page.waitForTimeout(1000);
  }
  await visible(target);
}

const DEMOS = {
  "pipelines/simple_rating": async (page) => {
    await next(page);
    await visible(page.getByRole("button", { name: "Play" }));
  },
  "pipelines/similarity": async (page) => {
    await advanceUntil(page, page.getByText("Please listen to Sound A"));
  },
  "experiments/staircase_pitch_discrimination": async (page) => {
    await advanceUntil(page, page.getByText("Which pitch was higher?"));
  },
  "features/trial_cue_adaptive": async (page) => {
    await visible(page.getByText(/Is \d+ a large number\?/));
  },
  "experiments/gibbs": async (page) => {
    await visible(page.locator(".push-button"));
    await page.locator(".push-button").first().click();
    await visible(page.locator("#color-box"));
  },
  "experiments/gibbs_image": async (page) => {
    await visible(page.getByText("Adjust the slider so that the image"));
  },
  "experiments/mcmcp": async (page) => {
    await advanceUntil(page, page.getByText(/Which one is the/));
  },
  "experiments/chain_trial_maker": async (page) => {
    await visible(page.getByText("Read the following story carefully"));
    await next(page);
    await page.locator("input[type=text], textarea").first().fill("A man went to the park and saw a duck");
  },
  "experiments/imitation_chain": async (page) => {
    await visible(page.getByText("Try to remember this 7-digit number"));
  },
  "experiments/tapping_iterated": async (page) => {
    await advanceUntil(page, page.getByText("You will now practice how to tap"));
  },
  "pipelines/tapping": async (page) => {
    await advanceUntil(page, page.getByText("Volume test"));
  },
  "experiments/vertical_processing": async (page) => {
    await advanceUntil(page, page.getByText("Please try singing into the microphone"));
  },
  "experiments/create_and_rate/basic": async (page) => {
    await visible(page.locator(".push-button"));
    await page.locator(".push-button").first().click();
    await visible(page.getByText("Describe the animal"));
    await page.locator("input[type=text], textarea").first().fill("A pug in a knitted jumper");
  },
  "experiments/create_and_rate/robot_voice": async (page) => {
    await visible(page.getByText("Adjust the slider to make the voice"));
  },
  "experiments/create_and_rate/picnic": async (page) => {
    await advanceUntil(page, page.getByText("Guess a Rule"));
  },
  "experiments/unity_autoplay": async (page) => {
    await advanceUntil(page, page.locator("canvas"), 20);
    // The game appears after its splash screen and ends a second or two later.
    await page.waitForTimeout(1800);
  },
  "experiments/language_tests": async (page) => {
    await advanceUntil(page, page.locator(".push-button img"), 80);
    await expect
      .poll(() => page.locator(".push-button img").evaluateAll((imgs) => imgs.every((img) => img.naturalWidth > 0)))
      .toBe(true);
  }
};

async function save(page, demo, { settle = true } = {}) {
  if (settle) {
    await waitForTimelinePageReady(page, TIMEOUT_MS).catch(() => {});
    await page.waitForTimeout(500);
  }
  await page.screenshot({ path: path.join(OUTPUT_DIR, `${demo.replace(/\//g, "__")}.png`) });
}

for (const [demo, reachPage] of Object.entries(DEMOS)) {
  test(demo, async ({ page, context }) => {
    await withExperiment(page, context, path.join(REPO, "demos", demo), async (experimentPage) => {
      await experimentPage.setViewportSize(VIEWPORT);
      await completeInitialGateway(experimentPage);
      await reachPage(experimentPage);
      await save(experimentPage, demo, { settle: demo !== "experiments/unity_autoplay" });
    });
  });
}

test("experiments/translation", async ({ page, context }) => {
  // The footer's reward label has no German translation until the next release.
  process.env.show_reward = "false";
  try {
    await withExperiment(page, context, path.join(REPO, "demos/experiments/translation"), async (experimentPage) => {
      await experimentPage.setViewportSize(VIEWPORT);
      await experimentPage.locator("#consent").click();
      await waitForTimelinePageReady(experimentPage, TIMEOUT_MS);
      await save(experimentPage, "experiments/translation");
    });
  } finally {
    process.env.show_reward = "true";
  }
});

/** Run a demo with two participants and screenshot the first one's page. */
async function withPair(browser, demo, run) {
  const { proc, urlPromise } = startExperiment(path.join(REPO, "demos", demo));
  const contexts = [await browser.newContext({ viewport: VIEWPORT }), await browser.newContext({ viewport: VIEWPORT })];
  try {
    const url = await urlPromise;
    const pages = [];
    for (const [i, context] of contexts.entries()) {
      const page = await beginExperiment(await context.newPage(), context, withFreshParticipantIds(url, `p${i + 1}`));
      await completeInitialGateway(page);
      pages.push(page);
    }
    await run(...pages);
    await save(pages[0], demo);
  } finally {
    for (const context of contexts) await context.close().catch(() => {});
    await stopExperiment(proc);
  }
}

test("experiments/chatroom_simple", async ({ browser }) => {
  await withPair(browser, "experiments/chatroom_simple", async (first, second) => {
    for (const page of [first, second]) await advanceUntil(page, page.locator("#chatroom-chat-input"), 20);
    for (const [page, message] of [[first, "Hi! Shall we start?"], [second, "Sure, go ahead"]]) {
      await page.locator("#chatroom-chat-input").fill(message);
      await page.locator("#chatroom-send-btn").click();
      await expect(first.locator("#chatroom-messages")).toContainText(message, { timeout: 30000 });
    }
  });
});

test("experiments/rock_paper_scissors", async ({ browser }) => {
  await withPair(browser, "experiments/rock_paper_scissors", async (first, second) => {
    for (const page of [first, second]) {
      await advanceUntil(page, page.getByRole("button", { name: /rock/i }), 20);
    }
  });
});
