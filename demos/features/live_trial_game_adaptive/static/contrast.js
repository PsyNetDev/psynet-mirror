export function activate({root, psynet}) {
    const game = psynet.liveGame;
    const patches = root.querySelector("#patches");
    let position = -1;
    let response = null;
    let frame;

    game.onTrial(view => {
        if (!game.playing || position === view.completed) return;
        position = view.completed;
        patches.dataset.position = position;
        response = null;
        cancelAnimationFrame(frame);
        if (!view.definition) {
            patches.style.visibility = "hidden";
            return;
        }
        frame = requestAnimationFrame(() => {
            for (const side of ["left", "right"]) {
                const grey = view.definition[side];
                root.querySelector(`#${side}-patch`).style.backgroundColor = `rgb(${grey}, ${grey}, ${grey})`;
            }
            patches.style.visibility = "visible";
            response = game.startResponseClock(view);
        });
    });

    function keydown(event) {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        if (!response || event.repeat) return;
        const queued = response.answer(event.key === "ArrowLeft" ? "left" : "right");
        if (queued !== undefined) patches.style.visibility = "hidden";
    }
    document.addEventListener("keydown", keydown);
    return () => {
        document.removeEventListener("keydown", keydown);
        cancelAnimationFrame(frame);
    };
}
