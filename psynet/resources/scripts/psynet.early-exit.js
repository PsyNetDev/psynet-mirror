/*
 * Client half of the paths that take a participant out of an experiment before
 * normal completion: the voluntary Leave modal, the recovery page's terminal
 * action, and navigation to the error page itself.
 *
 * The server owns every decision here. This script only reads the plan that the
 * server rendered into the DOM, calls the routes the server named, and follows
 * the release URL the server returned; it never chooses a payment outcome or a
 * destination of its own. psynet_layout.html loads it on every participant
 * page, so it must not assume the timeline's psynet.js is present.
 */
(function (global) {
  "use strict";

  let controller = null;
  let autoRedirectTimer = null;

  // Once a participant exists, fatal recovery is stored on the server and
  // rendered from /timeline?unique_id=.... Reach that page with a GET so that
  // reloading never asks the participant to confirm a form resubmission.
  // Pre-participant errors on /start remain with Dallinger until its
  // participant endpoint returns structured error codes. Replacing the history
  // entry also keeps Back off the page that just failed.
  function goToErrorPage(identity) {
    const source =
      identity || (global.dallinger && global.dallinger.identity) || {};
    const uniqueId =
      source.uniqueId || (global.psynet && global.psynet.uniqueId);
    if (uniqueId) {
      global.location.replace(
        "/timeline?unique_id=" + encodeURIComponent(uniqueId),
      );
      return;
    }
    // Untracked / pre-participant: never send enumerable participant_id.
    const params = new URLSearchParams();
    if (source.assignmentId) {
      params.set("assignment_id", source.assignmentId);
    }
    const query = params.toString();
    global.location.replace("/error-page" + (query ? "?" + query : ""));
  }

  function continueToRelease(releaseUrl) {
    if (!releaseUrl) throw new Error("The server did not provide a release URL.");
    if (global.dallinger && global.dallinger.allowExit) {
      global.dallinger.allowExit();
    }
    global.location.replace(releaseUrl);
  }

  async function postForm(url, data) {
    if (!url) throw new Error("The server did not provide the next action.");
    const response = await fetch(url, {
      method: "POST",
      body: new URLSearchParams(data),
    });
    if (!response.ok) throw new Error("The next action did not succeed.");
  }

  async function executePlan(assignmentId, planId, reloadStaleOffer = true) {
    if (!assignmentId || !planId) {
      throw new Error("The server did not provide an early-exit plan.");
    }
    const response = await fetch(
      "/execute_early_exit_plan/" + encodeURIComponent(assignmentId),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: planId }),
      },
    );
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      // A stale offer cannot be fixed by resending it. Voluntary Leave reloads
      // immediately; automatic recovery waits for the participant to retry so
      // a persistently stale server cannot cause a reload loop.
      if (result.error_code === "stale_early_exit_offer") {
        if (reloadStaleOffer) {
          global.location.reload();
          return;
        }
        const error = new Error("The early-exit offer is no longer current.");
        error.code = result.error_code;
        throw error;
      }
      throw new Error("Failed to record early exit.");
    }
    if (!result.release_url) {
      throw new Error("The server did not provide a release URL.");
    }
    return result.release_url;
  }

  function init() {
    if (controller) controller.abort();
    if (autoRedirectTimer) {
      global.clearTimeout(autoRedirectTimer);
      autoRedirectTimer = null;
    }
    controller = new AbortController();
    const { signal } = controller;

    const automatic = document.getElementById("automatic-early-exit");
    if (automatic) {
      const pending = document.getElementById("automatic-early-exit-pending");
      const failure = document.getElementById("automatic-early-exit-failure");
      const retry = document.getElementById("automatic-early-exit-retry");
      const finish = document.getElementById("automatic-early-exit-continue");
      const preparationPostUrl = automatic.dataset.preparationPostUrl;
      const preparationPostData = JSON.parse(
        automatic.dataset.preparationPostData || "{}",
      );
      const actionPostUrl = automatic.dataset.actionPostUrl;
      const actionPostData = JSON.parse(
        automatic.dataset.actionPostData || "{}",
      );
      const destinationUrl = automatic.dataset.destinationUrl;
      const autoRedirectDelay = Number(
        automatic.dataset.autoRedirectDelayMs || 0,
      );
      let releaseUrl = null;
      let reloadOnRetry = false;

      function showFailure(error) {
        reloadOnRetry = error.code === "stale_early_exit_offer";
        pending.hidden = true;
        if (finish) {
          finish.hidden = true;
          finish.disabled = false;
        }
        failure.hidden = false;
        retry.hidden = false;
        if (global.psynet && global.psynet.log) {
          global.psynet.log.error(error.stack || String(error));
        }
      }

      function showActionPending() {
        failure.hidden = true;
        retry.hidden = true;
        if (finish) {
          finish.hidden = true;
          finish.disabled = true;
        }
        pending.hidden = false;
      }

      async function followParticipantAction() {
        if (autoRedirectTimer) {
          global.clearTimeout(autoRedirectTimer);
          autoRedirectTimer = null;
        }
        showActionPending();
        try {
          if (automatic.dataset.offerId && !releaseUrl) {
            releaseUrl = await executePlan(
              automatic.dataset.assignmentId,
              automatic.dataset.offerId,
              false,
            );
          }
          if (preparationPostUrl) {
            await postForm(preparationPostUrl, preparationPostData);
          }
          if (actionPostUrl) {
            await postForm(actionPostUrl, actionPostData);
          }
          // Recruiter-specific POSTs (for example Prolific Submit) run first.
          // Confirmation is a later timeline page reached through release_url,
          // not a rewrite of this error document.
          continueToRelease(destinationUrl || releaseUrl);
        } catch (error) {
          showFailure(error);
        }
      }

      // Copy is already visible. Reveal the action once handlers exist;
      // show the wait state only while posting or redirecting.
      pending.hidden = true;
      failure.hidden = true;
      retry.hidden = true;
      retry.addEventListener(
        "click",
        () => {
          if (reloadOnRetry) {
            global.location.reload();
          } else {
            followParticipantAction();
          }
        },
        { signal },
      );
      if (finish) {
        finish.addEventListener("click", followParticipantAction, { signal });
        finish.hidden = false;
      }
      if (autoRedirectDelay > 0) {
        autoRedirectTimer = global.setTimeout(
          followParticipantAction,
          autoRedirectDelay,
        );
      }
      return;
    }

    const trigger =
      document.getElementById("early-exit-button") ||
      document.getElementById("early-exit-open");
    const modal = document.getElementById("early-exit-modal");
    const cancel = document.getElementById("early-exit-cancel");
    const confirm = document.getElementById("early-exit-confirm");
    if (!trigger || !modal || !cancel) return;

    function closeModal() {
      modal.hidden = true;
      modal.style.display = "none";
      trigger.focus();
    }

    function openModal() {
      modal.hidden = false;
      modal.style.display = "block";
      cancel.focus();
    }

    trigger.addEventListener("click", openModal, { signal });
    cancel.addEventListener("click", closeModal, { signal });
    modal.addEventListener(
      "click",
      (event) => {
        if (event.target === modal) closeModal();
      },
      { signal },
    );
    document.addEventListener(
      "keydown",
      (event) => {
        if (event.key === "Escape" && !modal.hidden) closeModal();
      },
      { signal },
    );

    if (!confirm) return;
    confirm.addEventListener(
      "click",
      async () => {
        const assignmentId = modal.dataset.assignmentId;
        const offerId = modal.dataset.offerId;
        if (!assignmentId || !offerId) return;

        confirm.disabled = true;
        cancel.disabled = true;
        try {
          const releaseUrl = await executePlan(assignmentId, offerId);
          if (releaseUrl) continueToRelease(releaseUrl);
        } catch (error) {
          confirm.disabled = false;
          cancel.disabled = false;
          if (global.psynet && global.psynet.log) {
            global.psynet.log.error(error.stack || String(error));
            await global.psynet.alert(
              "We could not end the experiment. Please try again.",
            );
          } else {
            goToErrorPage({ assignmentId: assignmentId });
          }
        }
      },
      { signal },
    );
  }

  global.psynetEarlyExit = { init };
  global.psynetErrorPage = { go: goToErrorPage };
})(window);
