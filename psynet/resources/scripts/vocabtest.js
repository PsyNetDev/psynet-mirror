// Every word's page shares this script. update() shows each word after the
// configured lag, and the next words are preloaded while the participant answers.
export function activate({root, psynet}) {
    const config = psynet.var.vocab;
    const target = root.querySelector("#test-stimulus");
    const controls = root.querySelectorAll("[data-choice]");
    const images = new Map();
    let response = null;
    let latest = null;
    let nextAt = 0;
    let timer;

    function enable(handle) {
        response = handle;
        for (const button of controls) button.disabled = !handle;
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

    async function display(word, handle) {
        if (word.image) {
            const img = imageFor(word.image);
            try {
                await img.decode();
            } catch (error) {
                if (latest !== handle) return;
                psynet.log.warn(`Couldn't decode ${word.image}, retrying: ${error}`);
                images.delete(word.image);
                timer = setTimeout(() => display(word, handle), 1000);
                return;
            }
            if (latest !== handle) return;
            target.replaceChildren(img);
        } else {
            target.textContent = word.stimulus;
        }
        enable(handle);
        handle.startClock();
        timer = setTimeout(() => { target.textContent = "…"; }, config.hideAfter);
    }

    function respond(choice) {
        if (response === null) return;
        const handle = response;
        enable(null);
        // Answering can call update() with the next word straight away.
        nextAt = performance.now() + config.lag;
        handle.answer(choice);
    }

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
    return {
        update({contents, upcoming, response: handle}) {
            clearTimeout(timer);
            latest = handle;
            enable(null);
            target.replaceChildren();
            for (const item of upcoming.slice(0, 2)) {
                if (item.image) imageFor(item.image);
            }
            timer = setTimeout(() => display(contents, handle),
                               Math.max(0, nextAt - performance.now()));
        },
        cleanup() {
            clearTimeout(timer);
            document.removeEventListener("keydown", keydown);
            root.removeEventListener("click", click);
        },
    };
}
