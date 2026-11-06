// Live ticks and members for GroupPrompt.
//
// After each arrival, departure or join in the group, psynet.js fetches the
// seats of the members waiting in it and of all its members, and sends them
// in a "psynetGroupReady" window event. The server draws the initial
// display; this makes the ticks match each event, starting with any that
// arrived before this module activated, and fetches the display again from
// the server when members have joined or left.

export async function activate({root, vars}) {
    var config = vars["group_prompt"] || {};
    if (!config.live_ticks && !config.live_members) return undefined;
    var announcer = root.querySelector(".psynet-group-announcer");
    var latestSeats = [];
    var redrawing = false;
    var redrawAgain = false;
    var failedRedraws = 0;
    var request = null;
    var retryTimer = null;
    // Pages can change in place, keeping root, so a redraw that ends after
    // cleanup would draw this page's group on the next page.
    var closed = false;

    function memberAt(seat) {
        return root.querySelector('.psynet-group-member[data-seat="' + Number(seat) + '"]');
    }

    function tick(seats) {
        var names = [];
        seats.forEach(function (seat) {
            var member = memberAt(seat);
            if (!member || member.classList.contains("psynet-group-member--answered")) return;
            member.classList.add("psynet-group-member--answered");
            var status = member.querySelector(".psynet-group-status");
            if (status) status.textContent = config.answered_label || "";
            if (!member.classList.contains("psynet-group-member--me")) {
                names.push(member.getAttribute("title"));
            }
        });
        if (announcer && names.length) {
            announcer.textContent = names
                .map(function (name) {
                    return (config.answered_announcement || "").replace("{NAME}", name);
                })
                .join(" ");
        }
    }

    function untickAllBut(seats) {
        var kept = new Set(seats.map(Number));
        root.querySelectorAll(".psynet-group-member--answered").forEach(function (member) {
            if (kept.has(Number(member.dataset.seat))) return;
            member.classList.remove("psynet-group-member--answered");
            var status = member.querySelector(".psynet-group-status");
            if (status) status.textContent = "";
        });
    }

    function showTicks(seats) {
        if (!config.live_ticks) return;
        untickAllBut(seats);
        tick(seats);
    }

    function drawnMembers() {
        return Array.from(root.querySelectorAll(".psynet-group-member[data-seat]"))
            .map(function (member) { return Number(member.dataset.seat); })
            .sort(function (a, b) { return a - b; });
    }

    function sameMembers(seats) {
        var drawn = drawnMembers();
        var wanted = seats.map(Number).sort(function (a, b) { return a - b; });
        return drawn.length === wanted.length && drawn.every(function (seat, i) {
            return seat === wanted[i];
        });
    }

    // Replaces the members, keeping the note and the live region.
    function replaceMembers(html) {
        var current = root.querySelector(".psynet-group-prompt");
        var template = document.createElement("template");
        template.innerHTML = html;
        var fresh = template.content.querySelector(".psynet-group-prompt");
        if (!current || !fresh || !current.firstElementChild || !fresh.firstElementChild) return;
        current.className = fresh.className;
        current.firstElementChild.replaceWith(fresh.firstElementChild);
    }

    function redraw() {
        retryTimer = null;
        if (closed || !config.redraw_token || typeof $ === "undefined") return;
        if (redrawing) {
            redrawAgain = true;
            return;
        }
        redrawing = true;
        request = $.ajax({
            url: "/timeline/group_prompt",
            cache: false,
            data: {uniqueId: psynet.uniqueId, token: config.redraw_token},
        }).done(function (data) {
            if (closed) return;
            failedRedraws = 0;
            if (data && data.html) replaceMembers(data.html);
        }).fail(function () {
            if (closed) return;
            failedRedraws += 1;
            if (failedRedraws <= 3 && !redrawAgain) {
                retryTimer = setTimeout(redraw, 2000 * failedRedraws);
            }
        }).always(function () {
            request = null;
            if (closed) return;
            redrawing = false;
            showTicks(latestSeats);
            if (redrawAgain) {
                redrawAgain = false;
                redraw();
            }
        });
    }

    function onReady(event) {
        var detail = event.detail || {};
        if (detail.groupId !== config.group_id) return;
        latestSeats = detail.seats || [];
        showTicks(latestSeats);
        if (detail.members && !sameMembers(detail.members)) redraw();
    }

    // The ticks say who is ready, so the arrival notice would repeat them.
    var releaseNotice =
        config.live_ticks && window.psynet && psynet.suppressArrivalNotice
            ? psynet.suppressArrivalNotice()
            : null;
    if (config.live_ticks && window.psynet && psynet.readySeatsFor) {
        tick(psynet.readySeatsFor(config.group_id));
    }
    window.addEventListener("psynetGroupReady", onReady);
    return function cleanup() {
        closed = true;
        clearTimeout(retryTimer);
        if (request) request.abort();
        window.removeEventListener("psynetGroupReady", onReady);
        if (releaseNotice) releaseNotice();
    };
}
