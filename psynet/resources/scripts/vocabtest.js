// One page per scored form. The server's position identifies a presentation,
// including when an item is immediately followed by a repeat of the same word.
export function activate({root, psynet}) {
    const game = psynet.liveGame;
    const config = psynet.var.vocab;
    const target = root.querySelector("#test-stimulus");
    const controls = root.querySelectorAll("[data-choice]");
    const images = new Map();
    let position = -1;
    let response = null;
    let nextAt = 0;
    let timer;
    let active = true;

    function enable(view) {
        response = view ? game.startResponseClock(view) : null;
        for (const button of controls) button.disabled = !view;
    }

    function imageFor(url) {
        if (!images.has(url)) {
            const img = new Image();
            img.alt = "";
            img.src = url;
            img.style.cssText = "max-width:100%;max-height:55vh;object-fit:contain";
            img.width = config.width;
            images.set(url, img);
        }
        return images.get(url);
    }

    async function display(word, expected) {
        if (word.image) {
            const img = imageFor(word.image);
            try {
                await img.decode();
            } catch {
                if (!active || position !== expected) return;
                images.delete(word.image);
                timer = setTimeout(() => display(word, expected), 1000);
                return;
            }
            if (!active || position !== expected) return;
            target.replaceChildren(img);
        } else {
            target.textContent = word.stimulus;
        }
        game.send("shown", {position: expected});
        enable({completed: expected, definition: word});
        timer = setTimeout(() => { target.textContent = "…"; }, config.hideAfter);
    }

    function render(view) {
        if (!game.playing || position === view.completed) return;
        clearTimeout(timer);
        enable(null);
        position = view.completed;
        target.replaceChildren();
        if (!view.definition) return;
        for (const item of view.deck.slice(position + 1, position + 3)) {
            if (item.image) imageFor(item.image);
        }
        timer = setTimeout(() => display(view.definition, view.completed),
                           Math.max(0, nextAt - performance.now()));
    }

    function respond(choice) {
        if (!game.playing || response === null) return;
        // Answering can render the next word synchronously, which reads nextAt.
        const previous = nextAt;
        nextAt = performance.now() + config.lag;
        if (response.answer(choice) === undefined) nextAt = previous;
    }

    game.predict(game.predictTrialAnswer);
    game.onChange(render);
    enable(null);
    function keydown(event) {
        if (event.repeat || !config.keyboard) return;
        if (event.code === config.trueKey) respond("real");
        else if (event.code === config.falseKey) respond("fake");
    }
    function click(event) {
        const choice = event.target.closest("button[data-choice]");
        if (config.buttons && choice) respond(choice.dataset.choice);
    }
    document.addEventListener("keydown", keydown);
    root.addEventListener("click", click);
    return () => {
        active = false;
        clearTimeout(timer);
        document.removeEventListener("keydown", keydown);
        root.removeEventListener("click", click);
    };
}
