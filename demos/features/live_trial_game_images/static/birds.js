export function activate({root, trial, psynet}) {
    const game = psynet.liveGame;
    const photos = root.querySelector("#birds");
    let ready = false;
    let position = -1;
    let shownAt = null;
    let frame;

    function show(view) {
        if (!ready || !view || !game.playing || position === view.completed) return;
        position = view.completed;
        shownAt = null;
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
            for (const img of photos.children) {
                img.hidden = img.id !== view.definition?.bird;
            }
            if (view.definition) shownAt = performance.now();
        });
    }

    // MediaSpec assigns a local blob URL to each matching <img> during trialConstruct.
    trial.onEvent("trialStart", async () => {
        await Promise.all(Array.from(photos.children, img => img.decode()));
        if (!photos.isConnected) return;
        ready = true;
        show(game.predictedView());
    });

    game.predict((view, type, message) => {
        if (type === "direction" && view.completed === message.position && view.definition) {
            view.completed++;
            view.definition = view.deck[view.completed] ?? null;
        }
    });
    game.onChange(show);

    function keydown(event) {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        if (!game.playing || shownAt === null || event.repeat) return;
        game.send("direction", {
            position,
            direction: event.key === "ArrowLeft" ? "left" : "right",
            seconds: (performance.now() - shownAt) / 1000,
        });
    }
    document.addEventListener("keydown", keydown);
    return () => {
        cancelAnimationFrame(frame);
        document.removeEventListener("keydown", keydown);
    };
}
