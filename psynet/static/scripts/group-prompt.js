// Live ticks for GroupPrompt.
//
// GroupBarrier sends the seats of the members waiting at it with each
// arrival update; psynet.js turns that into a "psynetGroupReady" window
// event. The server draws the initial ticks; this adds the ones sent since,
// including any that arrived before this module activated.

export async function activate({root, vars}) {
    var config = vars["group_prompt"] || {};
    if (!config.show_progress) return undefined;

    function tick(seats) {
        seats.forEach(function (seat) {
            var member = root.querySelector(
                '.psynet-group-member[data-seat="' + Number(seat) + '"]'
            );
            if (!member || member.classList.contains("psynet-group-member--answered")) return;
            member.classList.add("psynet-group-member--answered");
            var status = member.querySelector(".psynet-group-status");
            if (status) status.textContent = config.answered_label || "";
        });
    }

    function onReady(event) {
        var detail = event.detail || {};
        if (detail.groupId === config.group_id) tick(detail.seats || []);
    }

    if (window.psynet && psynet.readySeatsFor) tick(psynet.readySeatsFor(config.group_id));
    window.addEventListener("psynetGroupReady", onReady);
    return function cleanup() {
        window.removeEventListener("psynetGroupReady", onReady);
    };
}
