export function activate({root, psynet}) {
    const game = psynet.liveGame;
    const target = root.querySelector("#arrows");
    let position = -1;
    let response = null;
    let timer;

    game.predict(game.predictTrialAnswer);

    game.onChange(view => {
        if (!game.playing || view.completed === position) return;
        const blankMs = position === -1 ? 0 : 150;
        position = view.completed;
        response = null;
        target.textContent = "";
        clearTimeout(timer);
        if (view.definition) {
            timer = setTimeout(() => {
                target.textContent = view.definition.arrows;
                response = game.startResponseClock(view);
            }, blankMs);
        }
    });

    function keydown(event) {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        if (event.repeat || response === null || !game.playing) return;
        response.answer(event.key === "ArrowLeft" ? "←" : "→");
    }
    document.addEventListener("keydown", keydown);
    return () => {
        clearTimeout(timer);
        document.removeEventListener("keydown", keydown);
    };
}
