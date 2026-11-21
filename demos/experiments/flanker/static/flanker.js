// Every trial shares this page. A trial is a blank gap, a fixation cross, then
// the arrows until the participant responds or the deadline passes. The
// trial's time_taken runs from the frame that shows the arrows to the key
// press or tap, using the timestamps the browser gives both.
export function activate({psynet, root}) {
    const {timings} = psynet.var.flanker;
    const stimulus = root.querySelector("#flanker-stimulus");
    const buttons = root.querySelectorAll("button[data-response]");
    const keys = {KeyF: "left", KeyJ: "right"};
    let response = null;
    let blankUntil = 0;
    let timers = [];
    let frame = null;

    function clear() {
        timers.forEach(clearTimeout);
        timers = [];
        cancelAnimationFrame(frame);
    }

    function respond(answer, at) {
        if (response === null) return;
        const handle = response;
        response = null;
        clear();
        stimulus.textContent = "";
        blankUntil = performance.now() + timings.blank_ms;
        // Answering can call update() with the next trial straight away.
        handle.answer(answer, {at});
    }

    function keydown(event) {
        if (event.repeat || !(event.code in keys)) return;
        event.preventDefault();
        respond(keys[event.code], event.timeStamp);
    }

    function pointerdown(event) {
        // Also keeps the button from taking focus and looking selected.
        event.preventDefault();
        respond(event.currentTarget.dataset.response, event.timeStamp);
    }

    document.addEventListener("keydown", keydown);
    buttons.forEach((button) => button.addEventListener("pointerdown", pointerdown));
    return {
        update({contents, response: handle}) {
            clear();
            response = null;
            stimulus.textContent = "";
            const blank = Math.max(0, blankUntil - performance.now());
            timers.push(setTimeout(() => {
                stimulus.textContent = "+";
                timers.push(setTimeout(() => {
                    stimulus.textContent = contents.arrows;
                    // The callback runs at the start of the frame that paints
                    // the arrows, and receives that frame's time.
                    frame = requestAnimationFrame((shownAt) => {
                        response = handle;
                        handle.startClock(shownAt);
                        timers.push(setTimeout(
                            () => respond("timeout"),
                            timings.deadline_ms,
                        ));
                    });
                }, timings.fixation_ms));
            }, blank));
        },
        cleanup() {
            clear();
            document.removeEventListener("keydown", keydown);
            buttons.forEach((button) => button.removeEventListener("pointerdown", pointerdown));
        },
    };
}
