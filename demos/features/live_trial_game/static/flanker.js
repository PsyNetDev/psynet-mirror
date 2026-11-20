export function activate({root, psynet}) {
    const game = psynet.liveGame;
    const target = root.querySelector("#arrows");
    let position = -1;
    let shownAt = null;
    let timer;

    game.predict((view, type, message) => {
        if (type === "arrow_key" && view.completed === message.position && view.definition) {
            view.completed++;
            view.definition = view.deck[view.completed] ?? null;
        }
    });

    game.onChange(view => {
        if (!game.playing || view.completed === position) return;
        const blankMs = position === -1 ? 0 : 150;
        position = view.completed;
        shownAt = null;
        target.textContent = "";
        clearTimeout(timer);
        if (view.definition) {
            timer = setTimeout(() => {
                target.textContent = view.definition.arrows;
                shownAt = performance.now();
            }, blankMs);
        }
    });

    function keydown(event) {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        if (event.repeat || shownAt === null || !game.playing) return;
        game.send("arrow_key", {
            position,
            direction: event.key === "ArrowLeft" ? "←" : "→",
            seconds: (performance.now() - shownAt) / 1000,
        });
    }
    document.addEventListener("keydown", keydown);
    return () => {
        clearTimeout(timer);
        document.removeEventListener("keydown", keydown);
    };
}
