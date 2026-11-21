// Shows the trials of a ModularPage with a built-in prompt and push buttons
// one after another on the same page, for trial makers that prepare their
// trials in advance. The page renders without what differs between trials;
// update() fills that in from contents.modular_page, then restarts the page's
// trial events so that the prompt plays and the buttons enable as they would
// on a freshly loaded page.
export function activate({psynet, root}) {
    const text = root.querySelector("#prompt-text");
    const image = root.querySelector("#prompt-image");
    // The page's media spec loads the first trial's sound as usual.
    let audioUrl = psynet.media.requests?.audio?.prompt ?? null;
    let response = null;
    let shown = 0;

    psynet.page.control.pushButtons.handleClick = (button, id) => {
        if (response === null) return;
        const handle = response;
        response = null;
        psynet.trial.registerEvent("pushButtonClicked", {info: {buttonId: id}});
        psynet.response.disable();
        // Answering can call update() with the next trial straight away.
        handle.answer(id);
    };

    return {
        async update({contents, upcomingContents, response: handle}) {
            const current = ++shown;
            response = null;
            psynet.response.disable();
            await psynet.trial.stop({force: true});
            const {prompt} = contents.modular_page;
            if (text) {
                text.innerHTML = prompt.text;
            }
            if (prompt.image !== undefined) {
                image.style.opacity = 0;
                image.src = prompt.image;
                await image.decode().catch(() => {});
            }
            if (prompt.audio !== undefined && prompt.audio !== audioUrl) {
                psynet.audio.prompt = await psynet.media.loadAudio(prompt.audio);
                audioUrl = prompt.audio;
            }
            if (current !== shown) return;
            for (const next of upcomingContents) {
                const url = next.modular_page?.prompt.audio;
                if (url !== undefined) {
                    // Decoded now so that the next sound plays without delay;
                    // a failure shows when that trial loads it again.
                    psynet.media.loadAudio(url).catch(() => {});
                }
            }
            response = handle;
            handle.startClock();
            await psynet.trial.restart();
        },
    };
}
