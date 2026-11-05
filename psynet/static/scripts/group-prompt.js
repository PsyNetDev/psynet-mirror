// Live ticks for GroupPrompt.
//
// GroupBarrier sends the seats of the members waiting at it with each
// arrival update; psynet.js turns that into a "psynetGroupReady" window
// event. The server draws the initial ticks, so this only adds new ones.

export async function activate({root, vars}) {
    var config = vars["group_prompt"] || {};
    if (!config.show_progress) return undefined;

    function onReady(event) {
        var detail = event.detail || {};
        if (detail.groupId !== config.group_id) return;
        (detail.seats || []).forEach(function (seat) {
            var member = root.querySelector(
                '.psynet-group-member[data-seat="' + Number(seat) + '"]'
            );
            if (!member || member.classList.contains("psynet-group-member--answered")) return;
            member.classList.add("psynet-group-member--answered");
            var status = member.querySelector(".psynet-group-status");
            if (status) status.textContent = config.answered_label || "";
        });
    }

    window.addEventListener("psynetGroupReady", onReady);
    return function cleanup() {
        window.removeEventListener("psynetGroupReady", onReady);
    };
}
