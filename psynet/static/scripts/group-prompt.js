// Live ticks for GroupPrompt.
//
// GroupBarrier sends the seats of the members waiting at it with each
// arrival update, and the seats still in the group; psynet.js turns that
// into a "psynetGroupReady" window event. The server draws the initial
// ticks; this adds the ones sent since, including any that arrived before
// this module activated, and removes those of members who have left.

export async function activate({root, vars}) {
    var config = vars["group_prompt"] || {};
    if (!config.live_ticks) return undefined;
    var announcer = root.querySelector(".psynet-group-announcer");

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
            announcer.textContent = names.join(", ") + " " + (config.answered_label || "");
        }
    }

    function untickAllBut(members) {
        var kept = new Set(members.map(Number));
        root.querySelectorAll(".psynet-group-member--answered").forEach(function (member) {
            if (kept.has(Number(member.dataset.seat))) return;
            member.classList.remove("psynet-group-member--answered");
            var status = member.querySelector(".psynet-group-status");
            if (status) status.textContent = "";
        });
    }

    function onReady(event) {
        var detail = event.detail || {};
        if (detail.groupId !== config.group_id) return;
        if (detail.members) untickAllBut(detail.members);
        tick(detail.seats || []);
    }

    if (window.psynet && psynet.readySeatsFor) tick(psynet.readySeatsFor(config.group_id));
    window.addEventListener("psynetGroupReady", onReady);
    return function cleanup() {
        window.removeEventListener("psynetGroupReady", onReady);
    };
}
