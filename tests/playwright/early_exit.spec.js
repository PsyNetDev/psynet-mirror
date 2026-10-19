const fs = require("fs");
const path = require("path");
const { test, expect } = require("./fixtures");

const EARLY_EXIT_JS = fs.readFileSync(
  path.resolve("psynet/resources/scripts/psynet.early-exit.js"),
  "utf8"
);

const PROLIFIC_EXIT_PROCESS_SCRIPT = `
  (function () {
    const button = document.getElementById("js-exit-button");
    const pending = document.getElementById("prolific-exit-pending");
    const failure = document.getElementById("prolific-exit-failure");
    const retry = document.getElementById("prolific-exit-retry");
    function showPending() {
      button.hidden = true;
      button.disabled = true;
      retry.hidden = true;
      retry.disabled = true;
      failure.hidden = true;
      pending.hidden = false;
    }
    function showFailure() {
      pending.hidden = true;
      button.hidden = true;
      failure.hidden = false;
      retry.hidden = false;
      retry.disabled = false;
    }
    function submit() {
      showPending();
      const data = new URLSearchParams();
      data.append("assignmentId", "assignment-123");
      data.append("participantId", "7");
      fetch("/prolific-submission-listener", {method: "POST", body: data})
        .then((response) => {
          if (!response.ok) {
            throw new Error("submission listener failed");
          }
          window.location.replace(
            window.location.pathname + window.location.search
          );
        })
        .catch(() => { showFailure(); });
    }
    button.addEventListener("click", submit);
    retry.addEventListener("click", submit);
  })();
`;

test(
  "untracked error recovery does not execute an exit plan",
  { tag: "@both" },
  async ({ page }) => {
    let executeRequests = 0;
    let completionAttempts = 0;
    await page.route("http://psynet.test/error", async (route) => {
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body: `
          <div id="automatic-early-exit"
               data-assignment-id="assignment-1"
               data-offer-id=""
               data-preparation-post-url="">
            <p id="automatic-early-exit-ready">
              Unfortunately an error occurred and we cannot continue.
              However, your responses so far have been saved. You may close this page.
            </p>
            <p id="automatic-early-exit-pending" hidden>Saving...</p>
            <p id="automatic-early-exit-failure" hidden>Try again.</p>
            <button id="automatic-early-exit-retry" hidden>Try again</button>
          </div>
        `
      });
    });
    await page.route("**/execute_early_exit_plan/**", async (route) => {
      executeRequests += 1;
      await route.abort();
    });
    await page.route("http://psynet.test/worker_complete", async (route) => {
      completionAttempts += 1;
      await route.abort();
    });

    await page.goto("http://psynet.test/error");
    await expect(page.locator("#automatic-early-exit-ready")).toBeVisible();
    await expect(page.locator("#automatic-early-exit-pending")).toBeHidden();

    await page.addScriptTag({ content: EARLY_EXIT_JS });
    await page.evaluate(() => window.psynetEarlyExit.init());

    await expect(page.locator("#automatic-early-exit-ready")).toBeVisible();
    await expect(page.locator("#automatic-early-exit-continue")).toHaveCount(0);
    expect(executeRequests).toBe(0);
    expect(completionAttempts).toBe(0);
  }
);

test(
  "Prolific recovery explains and performs its direct submission",
  { tag: "@both" },
  async ({ page }) => {
    let prolificSubmission;
    await page.route("http://psynet.test/error", async (route) => {
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body: `
          <div id="automatic-early-exit"
               data-assignment-id="assignment-1"
               data-offer-id="offer-1"
               data-action-post-url="/prolific-submission-listener"
               data-action-post-data='{"assignmentId":"assignment-1","participantId":"42"}'>
            <div id="automatic-early-exit-ready">
              <p>
              Unfortunately an error occurred and we cannot continue.
              However, your responses so far have been saved. We will pay you
              for your progress so far: you will receive £0.25 through Prolific.
              </p>
              <p>Select Submit to Prolific to complete your submission.</p>
            </div>
            <p id="automatic-early-exit-pending" hidden>Saving...</p>
            <p id="automatic-early-exit-failure" hidden>Try again.</p>
            <button id="automatic-early-exit-retry" hidden>Try again</button>
            <button id="automatic-early-exit-continue" hidden>
              Submit to Prolific
            </button>
          </div>
        `
      });
    });
    await page.route(
      "http://psynet.test/execute_early_exit_plan/assignment-1",
      async (route) => {
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({
            release_url: "http://psynet.test/release"
          })
        });
      }
    );
    await page.route(
      "http://psynet.test/prolific-submission-listener",
      async (route) => {
        prolificSubmission = Object.fromEntries(
          new URLSearchParams(route.request().postData())
        );
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ status: "success" })
        });
      }
    );
    await page.route("http://psynet.test/release", async (route) => {
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body: `
          <h1>Your submission has been sent to Prolific.</h1>
          <p>You may close this page.</p>
        `
      });
    });

    await page.goto("http://psynet.test/error");
    await expect(page.locator("#automatic-early-exit-ready")).toContainText(
      "you will receive £0.25 through Prolific."
    );
    await expect(page.locator("#automatic-early-exit-continue")).toBeHidden();
    await expect(page.locator("#automatic-early-exit-pending")).toBeHidden();

    await page.addScriptTag({ content: EARLY_EXIT_JS });
    await page.evaluate(() => window.psynetEarlyExit.init());

    await expect(page.locator("#automatic-early-exit-ready")).toContainText(
      "you will receive £0.25 through Prolific."
    );
    await expect(page.locator("#automatic-early-exit-ready p").nth(1)).toHaveText(
      "Select Submit to Prolific to complete your submission."
    );
    await expect(page.locator("#automatic-early-exit-continue")).toHaveText(
      "Submit to Prolific"
    );
    expect(prolificSubmission).toBeUndefined();

    await page.locator("#automatic-early-exit-continue").click();
    await expect(page).toHaveURL("http://psynet.test/release");
    await expect(page.locator("h1")).toHaveText(
      "Your submission has been sent to Prolific."
    );
    await expect(page.locator("p")).toHaveText("You may close this page.");
    expect(prolificSubmission).toEqual({
      assignmentId: "assignment-1",
      participantId: "42"
    });
  }
);

test(
  "error recovery shows a wait state only while submitting",
  { tag: "@both" },
  async ({ page }) => {
    let releaseExecute;
    const executeStarted = new Promise((resolve) => {
      releaseExecute = resolve;
    });
    await page.route("http://psynet.test/error", async (route) => {
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body: `
          <div id="automatic-early-exit"
               data-assignment-id="assignment-1"
               data-offer-id="offer-1">
            <p id="automatic-early-exit-ready">
              Unfortunately an error occurred and we cannot continue.
            </p>
            <div id="automatic-early-exit-pending" hidden>Please wait.</div>
            <p id="automatic-early-exit-failure" hidden>Try again.</p>
            <button id="automatic-early-exit-retry" hidden>Try again</button>
            <button id="automatic-early-exit-continue" hidden>Continue</button>
          </div>
        `
      });
    });
    await page.route(
      "http://psynet.test/execute_early_exit_plan/assignment-1",
      async (route) => {
        await executeStarted;
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ release_url: "http://psynet.test/release" })
        });
      }
    );
    await page.route("http://psynet.test/release", async (route) => {
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body: "<h1>Done</h1>"
      });
    });

    await page.goto("http://psynet.test/error");
    await expect(page.locator("#automatic-early-exit-ready")).toBeVisible();
    await expect(page.locator("#automatic-early-exit-pending")).toBeHidden();
    await page.addScriptTag({ content: EARLY_EXIT_JS });
    await page.evaluate(() => window.psynetEarlyExit.init());

    await page.locator("#automatic-early-exit-continue").click({
      noWaitAfter: true
    });
    await expect(page.locator("#automatic-early-exit-pending")).toBeVisible();
    await expect(page.locator("#automatic-early-exit-ready")).toBeVisible();
    await expect(page.locator("#automatic-early-exit-continue")).toBeHidden();
    releaseExecute();
    await expect(page).toHaveURL("http://psynet.test/release");
  }
);

test(
  "Prolific recruiter-exit Submit reloads confirmation instead of rewriting in place",
  { tag: "@both" },
  async ({ page }) => {
    let listenerPosted = false;
    let exitLoads = 0;
    await page.route("http://psynet.test/recruiter-exit**", async (route) => {
      exitLoads += 1;
      const body = listenerPosted
        ? `
          <title>Your submission has been sent to Prolific.</title>
          <h1>Your submission has been sent to Prolific.</h1>
          <p id="prolific-exit-done">You may close this page.</p>
        `
        : `
          <title>Submit to Prolific</title>
          <h1>Submit to Prolific</h1>
          <p id="prolific-exit-instructions">
            Click below to send your submission to Prolific. You will not need to enter a completion code.
          </p>
          <div id="prolific-exit-pending" hidden>Please wait.</div>
          <p id="prolific-exit-failure" hidden>
            We could not send your submission to Prolific. Please try again. If this keeps happening, message the researcher through Prolific.
          </p>
          <button id="prolific-exit-retry" hidden>Try again</button>
          <button id="js-exit-button">Submit to Prolific</button>
          <script>${PROLIFIC_EXIT_PROCESS_SCRIPT}</script>
        `;
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body
      });
    });
    await page.route(
      "http://psynet.test/prolific-submission-listener",
      async (route) => {
        listenerPosted = true;
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ status: "success" })
        });
      }
    );

    await page.goto("http://psynet.test/recruiter-exit");
    await expect(page).toHaveTitle("Submit to Prolific");
    await expect(page.locator("h1")).toHaveText("Submit to Prolific");
    await page.locator("#js-exit-button").click();
    await expect(page.locator("#prolific-exit-done")).toHaveText(
      "You may close this page."
    );
    await expect(page).toHaveTitle("Your submission has been sent to Prolific.");
    await expect(page.locator("h1")).toHaveText(
      "Your submission has been sent to Prolific."
    );
    await expect(page.locator("#js-exit-button")).toHaveCount(0);
    expect(exitLoads).toBe(2);
  }
);

test(
  "Prolific recruiter-exit Submit can retry after a failed listener post",
  { tag: "@both" },
  async ({ page }) => {
    let listenerPosts = 0;
    let listenerPosted = false;
    await page.route("http://psynet.test/recruiter-exit**", async (route) => {
      const body = listenerPosted
        ? `
          <h1>Your submission has been sent to Prolific.</h1>
          <p id="prolific-exit-done">You may close this page.</p>
        `
        : `
          <h1>Submit to Prolific</h1>
          <div id="prolific-exit-pending" hidden>Please wait.</div>
          <p id="prolific-exit-failure" hidden>
            We could not send your submission to Prolific. Please try again.
          </p>
          <button id="prolific-exit-retry" hidden>Try again</button>
          <button id="js-exit-button">Submit to Prolific</button>
          <script>${PROLIFIC_EXIT_PROCESS_SCRIPT}</script>
        `;
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body
      });
    });
    await page.route(
      "http://psynet.test/prolific-submission-listener",
      async (route) => {
        listenerPosts += 1;
        if (listenerPosts === 1) {
          await route.fulfill({ status: 500, body: "no" });
          return;
        }
        listenerPosted = true;
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ status: "success" })
        });
      }
    );

    await page.goto("http://psynet.test/recruiter-exit");
    await page.locator("#js-exit-button").click();
    await expect(page.locator("#prolific-exit-failure")).toBeVisible();
    await expect(page.locator("#prolific-exit-retry")).toBeVisible();
    await expect(page.locator("#js-exit-button")).toBeHidden();
    await page.locator("#prolific-exit-retry").click();
    await expect(page.locator("#prolific-exit-done")).toHaveText(
      "You may close this page."
    );
    expect(listenerPosts).toBe(2);
  }
);

test(
  "Lucid recovery keeps its readable page before redirecting",
  { tag: "@both" },
  async ({ page }) => {
    await page.route("http://psynet.test/error", async (route) => {
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body: `
          <h1>An error occurred</h1>
          <div id="automatic-early-exit"
               data-assignment-id="rid-1"
               data-offer-id="offer-1"
               data-destination-url="http://psynet.test/lucid"
               data-auto-redirect-delay-ms="250">
            <p id="automatic-early-exit-ready">
              Unfortunately an error occurred and we cannot continue.
              However, your responses so far have been saved. We will return
              you to your panel in a few seconds.
            </p>
            <div id="automatic-early-exit-pending" hidden>Loading</div>
            <p id="automatic-early-exit-failure" hidden>Try again.</p>
            <button id="automatic-early-exit-retry" hidden>Try again</button>
            <button id="automatic-early-exit-continue" hidden>
              Return to your panel
            </button>
          </div>
        `
      });
    });
    await page.route(
      "http://psynet.test/execute_early_exit_plan/rid-1",
      async (route) => {
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({
            release_url: "http://psynet.test/release"
          })
        });
      }
    );
    await page.route("http://psynet.test/lucid", async (route) => {
      await route.fulfill({
        contentType: "text/html",
        body: "<h1>Lucid</h1>"
      });
    });

    await page.goto("http://psynet.test/error");
    await expect(page.locator("#automatic-early-exit-ready")).toBeVisible();
    await expect(page.locator("#automatic-early-exit-continue")).toBeHidden();

    await page.addScriptTag({ content: EARLY_EXIT_JS });
    await page.evaluate(() => window.psynetEarlyExit.init());

    await expect(page.locator("#automatic-early-exit-ready")).toBeVisible();
    await expect(page.locator("#automatic-early-exit-continue")).toHaveText(
      "Return to your panel"
    );
    await expect(page).toHaveURL("http://psynet.test/lucid");
  }
);

test(
  "untracked Lucid errors use the same redirect presentation without an exit plan",
  { tag: "@both" },
  async ({ page }) => {
    let executeRequests = 0;
    await page.route("http://psynet.test/error", async (route) => {
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body: `
          <div id="automatic-early-exit"
               data-assignment-id="rid-1"
               data-offer-id=""
               data-destination-url="http://psynet.test/lucid"
               data-auto-redirect-delay-ms="100">
            <p id="automatic-early-exit-ready">
              Unfortunately an error occurred and we cannot continue.
              We will return you to your panel in a few seconds.
            </p>
            <div id="automatic-early-exit-pending" hidden>Loading</div>
            <p id="automatic-early-exit-failure" hidden></p>
            <button id="automatic-early-exit-retry" hidden>Try again</button>
            <button id="automatic-early-exit-continue" hidden>
              Return to your panel
            </button>
          </div>
        `
      });
    });
    await page.route("**/execute_early_exit_plan/**", async (route) => {
      executeRequests += 1;
      await route.abort();
    });
    await page.route("http://psynet.test/lucid", async (route) => {
      await route.fulfill({
        contentType: "text/html",
        body: "<h1>Lucid</h1>"
      });
    });

    await page.goto("http://psynet.test/error");
    await expect(page.locator("#automatic-early-exit-ready")).toBeVisible();

    await page.addScriptTag({ content: EARLY_EXIT_JS });
    await page.evaluate(() => window.psynetEarlyExit.init());

    await expect(page.locator("#automatic-early-exit-ready")).toBeVisible();
    await expect(page).toHaveURL("http://psynet.test/lucid");
    expect(executeRequests).toBe(0);
  }
);

test(
  "errors reach a reloadable timeline recovery page instead of a resubmittable form",
  { tag: "@both" },
  async ({ page }) => {
    const methods = [];
    await page.route("http://psynet.test/start", async (route) => {
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body: "<h1>Start</h1>"
      });
    });
    await page.route("http://psynet.test/timeline**", async (route) => {
      methods.push(route.request().method());
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body: "<h1>An error occurred</h1>"
      });
    });

    await page.goto("http://psynet.test/start");
    await page.addScriptTag({ content: EARLY_EXIT_JS });
    await Promise.all([
      page.waitForURL(
        "http://psynet.test/timeline?unique_id=worker-1%3Aassignment-1"
      ),
      // Deferred so the navigation does not tear down this evaluation.
      page.evaluate(() =>
        setTimeout(
          () =>
            window.psynetErrorPage.go({
              uniqueId: "worker-1:assignment-1"
            }),
          0
        )
      )
    ]);

    // A POST-rendered page would prompt the participant to confirm
    // resubmission here rather than simply loading again.
    await page.reload();
    await expect(page.locator("h1")).toHaveText("An error occurred");
    expect(methods).toEqual(["GET", "GET"]);

    // The failed page is replaced rather than pushed, so Back cannot revive it.
    await page.goBack();
    await expect(page).not.toHaveURL(/timeline/);
  }
);

test(
  "automatic recovery does not loop on a stale offer",
  { tag: "@both" },
  async ({ page }) => {
    let pageLoads = 0;
    await page.route("http://psynet.test/error", async (route) => {
      pageLoads += 1;
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body: `
          <div id="automatic-early-exit"
               data-assignment-id="assignment-1"
               data-offer-id="stale">
            <p id="automatic-early-exit-ready">Done.</p>
            <div id="automatic-early-exit-pending" hidden>Loading</div>
            <p id="automatic-early-exit-failure" hidden>Try again.</p>
            <button id="automatic-early-exit-retry" hidden>Try again</button>
            <button id="automatic-early-exit-continue" hidden>Continue</button>
          </div>
        `
      });
    });
    await page.route(
      "http://psynet.test/execute_early_exit_plan/assignment-1",
      async (route) => {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ error_code: "stale_early_exit_offer" })
        });
      }
    );

    await page.goto("http://psynet.test/error");
    await page.addScriptTag({ content: EARLY_EXIT_JS });
    await page.evaluate(() => window.psynetEarlyExit.init());

    await page.locator("#automatic-early-exit-continue").click();
    await expect(page.locator("#automatic-early-exit-failure")).toBeVisible();
    await expect(page.locator("#automatic-early-exit-ready")).toBeVisible();
    expect(pageLoads).toBe(1);

    await page.locator("#automatic-early-exit-retry").click();
    await expect.poll(() => pageLoads).toBe(2);
  }
);
