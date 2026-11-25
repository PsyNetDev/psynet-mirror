// Every word's page shares this script. update() shows each word after the
// configured lag, and the next words are preloaded while the participant answers.
export function activate({root, psynet}) {
    const config = psynet.pageConfig.vocab;
    const target = root.querySelector("#test-stimulus");
    const controls = root.querySelectorAll("[data-choice]");
    const images = new Map();
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    let response = null;
    let nextAt = 0;
    let hideTimer;

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

    // Resolves with the decoded image, or null once a newer word replaces this one.
    async function decoded(url, signal) {
        for (let attempt = 1; ; attempt++) {
            const img = imageFor(url);
            try {
                await img.decode();
                return img;
            } catch (error) {
                images.delete(url);
                if (signal.aborted) return null;
                // PsyNet then asks the participant to reload the page.
                if (attempt === 3) throw new Error(`Couldn't load ${url}: ${error}`);
                psynet.log.warn(`Couldn't decode ${url}, retrying: ${error}`);
                await sleep(1000);
                if (signal.aborted) return null;
            }
        }
    }

    function respond(choice) {
        if (response === null) return;
        const handle = response;
        enable(null);
        clearTimeout(hideTimer);
        target.replaceChildren();
        // Answering can call update() with the next word straight away.
        nextAt = performance.now() + config.lag;
        handle.answer(choice);
    }

    function keydown(event) {
        if (event.repeat || !config.keyboard) return;
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        if (event.target.closest?.("input, textarea, select, [contenteditable]")) return;
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
        async update({contents, upcomingContents, response: handle, signal}) {
            clearTimeout(hideTimer);
            enable(null);
            target.replaceChildren();
            for (const item of upcomingContents.slice(0, 2)) {
                if (item.image) imageFor(item.image);
            }
            await sleep(Math.max(0, nextAt - performance.now()));
            if (signal.aborted) return;
            if (contents.image) {
                const img = await decoded(contents.image, signal);
                if (img === null) return;
                target.replaceChildren(img);
            } else {
                target.textContent = contents.stimulus;
            }
            enable(handle);
            handle.startClock();
            hideTimer = setTimeout(() => { target.textContent = "…"; }, config.hideAfter);
        },
        cleanup() {
            clearTimeout(hideTimer);
            document.removeEventListener("keydown", keydown);
            root.removeEventListener("click", click);
        },
    };
}
