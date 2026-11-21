export function activate({root, trial, psynet}) {
    const game = psynet.liveGame;
    const photos = root.querySelector("#birds");
    let ready = false;
    let position = -1;
    let response = null;
    let frame;

    function show(view) {
        if (!ready || !view || !game.playing || position === view.completed) return;
        position = view.completed;
        response = null;
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
            for (const img of photos.children) {
                img.hidden = img.id !== view.definition?.bird;
            }
            if (view.definition) response = game.startResponseClock(view);
        });
    }

    // MediaSpec assigns a local blob URL to each matching <img> during trialConstruct.
    trial.onEvent("trialStart", async () => {
        await Promise.all(Array.from(photos.children, img => img.decode()));
        if (!photos.isConnected) return;
        ready = true;
        show(game.predictedView());
    });

    game.predict(game.predictTrialAnswer);
    game.onChange(show);

    function keydown(event) {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        if (!game.playing || response === null || event.repeat) return;
        response.answer(event.key === "ArrowLeft" ? "left" : "right");
    }
    document.addEventListener("keydown", keydown);
    return () => {
        cancelAnimationFrame(frame);
        document.removeEventListener("keydown", keydown);
    };
}
