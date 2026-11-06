// Countdown for a page with a time_limit (see Page.time_limit).
//
// The server sends the seconds left when the page is drawn, so a reload
// continues the same countdown. Elements with data-psynet-seconds-left show
// it; without one, the module adds a "N s left" chip where timeline holds
// show their status, hidden while the page is being submitted or held. At
// zero the page submits with time_limit_reached in its metadata, and the
// server records the page's time_limit_answer.

export function activate({root, vars, psynet}) {
    var config = vars["timeLimit"];
    if (!config) return undefined;
    var deadline = Date.now() + Number(config.secondsLeft) * 1000;
    var labels = Array.from(root.querySelectorAll("[data-psynet-seconds-left]"));
    var line = null;
    if (labels.length === 0) {
        line = document.createElement("div");
        line.className = "psynet-status-chip psynet-time-limit";
        var parts = String(config.text).split("{SECONDS}");
        line.append(parts[0]);
        var label = document.createElement("span");
        label.setAttribute("data-psynet-seconds-left", "");
        line.append(label, parts.slice(1).join("{SECONDS}"));
        (document.getElementById("timeline-hold-region") || root).append(line);
        labels = [label];
    }
    var timer = null;
    var submitted = false;

    function submit() {
        if (submitted) return;
        if (!psynet.pageReady || psynet.nextPagePending || psynet.timelineHold) {
            // Another submission is under way, or the page is still loading.
            timer = window.setTimeout(submit, 500);
            return;
        }
        submitted = true;
        var staged = (psynet.response && psynet.response.staged) || {};
        var metadata = Object.assign({}, staged.metadata || {}, {time_limit_reached: true});
        psynet.nextPage(null, metadata, {});
    }

    function tick() {
        var left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
        labels.forEach(function (label) {
            label.textContent = left;
        });
        if (line) line.hidden = Boolean(psynet.nextPagePending || psynet.timelineHold);
        if (left > 0) timer = window.setTimeout(tick, 250);
        else submit();
    }

    tick();
    return function () {
        submitted = true;
        window.clearTimeout(timer);
        if (line) line.remove();
    };
}
