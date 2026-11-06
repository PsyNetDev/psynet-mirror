// Countdown for a page with a time_limit (see Page.time_limit).
//
// The server sends the seconds left when the page is drawn, so a reload
// continues the same countdown. Elements with data-psynet-seconds-left show
// it; without one, the module adds a "N s left" chip where timeline holds
// show their status, hidden while the page is being submitted or held and
// once it reaches zero. At
// zero the page submits with time_limit_reached in its metadata, and the
// server records the page's time_limit_answer. If the server's deadline is
// still some way off, it returns the seconds left and the countdown resumes.

export function activate({root, vars, psynet}) {
    var config = vars["timeLimit"];
    if (!config) return undefined;
    // secondsLeft was measured when the server drew the page, before the
    // page's scripts loaded.
    var deadline = (psynet.pageReceivedAt || Date.now()) + Number(config.secondsLeft) * 1000;
    var labels = Array.from(root.querySelectorAll("[data-psynet-seconds-left]"));
    var line = null;
    if (labels.length === 0) {
        line = document.createElement("div");
        line.className = "psynet-status-chip psynet-time-limit";
        var parts = String(config.text).split("{SECONDS}");
        var text = document.createElement("span");
        var label = document.createElement("span");
        label.setAttribute("data-psynet-seconds-left", "");
        text.append(parts[0], label, parts.slice(1).join("{SECONDS}"));
        line.append(text);
        (document.getElementById("timeline-hold-region") || root).append(line);
        labels = [label];
    }
    var timer = null;
    var submitted = false;
    var stopped = false;
    var retries = 0;

    function retry() {
        // A blocked or failed submission is retried a few times.
        if (stopped || retries >= 10 || !root.isConnected) return;
        retries += 1;
        submitted = false;
        timer = window.setTimeout(submit, 1000);
    }

    function submit() {
        if (submitted || stopped) return;
        if (!psynet.pageReady || psynet.nextPagePending || psynet.timelineHold) {
            // Another submission is under way, or the page is still loading.
            timer = window.setTimeout(submit, 500);
            return;
        }
        submitted = true;
        var staged = (psynet.response && psynet.response.staged) || {};
        var metadata = Object.assign({}, staged.metadata || {}, {time_limit_reached: true});
        var early = null;
        var refused = false;
        function onRejection(response) {
            if (response && response.time_limit_seconds_left !== undefined) {
                early = Number(response.time_limit_seconds_left);
            } else if (response && response.message) {
                // For example a stale second tab: the participant has already
                // been told, and retrying would repeat the alert.
                refused = true;
            }
        }
        Promise.resolve()
            .then(function () {
                return psynet.nextPage(null, metadata, {}, onRejection);
            })
            .then(function (accepted) {
                if (accepted !== false || stopped) return;
                if (refused) {
                    stopped = true;
                } else if (early !== null) {
                    deadline = Date.now() + early * 1000;
                    submitted = false;
                    tick();
                } else {
                    retry();
                }
            }, retry);
    }

    function tick() {
        var left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
        labels.forEach(function (label) {
            // The page moves on at zero, so the label never reads "0 s".
            label.textContent = Math.max(left, 1);
        });
        if (line) line.hidden = left === 0 || Boolean(psynet.nextPagePending || psynet.timelineHold);
        if (left > 0) timer = window.setTimeout(tick, 250);
        else submit();
    }

    tick();
    return function () {
        stopped = true;
        window.clearTimeout(timer);
        if (line) line.remove();
    };
}
