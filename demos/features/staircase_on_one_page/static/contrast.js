// The screen stays blank for at least this long between trials, with the
// chosen side in bold, so that each answer visibly ends its trial.
const GAP_MS = 200;

export function activate({root}) {
    const patches = root.querySelector("#patches");
    const counter = root.querySelector("#trial-counter");
    const labels = {left: root.querySelector("#left-label"), right: root.querySelector("#right-label")};
    let response = null;
    let answeredAt = -Infinity;

    function keydown(event) {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        if (response === null || event.repeat) return;
        const side = event.key === "ArrowLeft" ? "left" : "right";
        response.answer(side);
        response = null;
        patches.style.visibility = "hidden";
        labels[side].style.fontWeight = "bold";
        answeredAt = performance.now();
    }

    document.addEventListener("keydown", keydown);
    return {
        update({contents, response: handle, signal}) {
            const wait = Math.max(0, answeredAt + GAP_MS - performance.now());
            setTimeout(() => {
                if (signal.aborted) return;  // a newer trial has started
                counter.textContent = `Trial ${contents.trial} of ${contents.n_trials}`;
                for (const side of ["left", "right"]) {
                    const grey = contents[side];
                    root.querySelector(`#${side}-patch`).style.backgroundColor = `rgb(${grey}, ${grey}, ${grey})`;
                    labels[side].style.fontWeight = "";
                }
                patches.style.visibility = "visible";
                response = handle;
                handle.startClock();
            }, wait);
        },
        cleanup: () => document.removeEventListener("keydown", keydown),
    };
}
