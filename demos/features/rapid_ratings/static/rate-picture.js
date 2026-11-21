export function activate({root, psynet}) {
    const picture = root.querySelector("#picture");
    let response = null;
    let latest = null;

    function rate(rating) {
        if (response === null) return;
        response.answer(rating);
        response = null;
        picture.style.visibility = "hidden";
    }

    function click(event) {
        const button = event.target.closest("[data-rating]");
        if (button !== null) rate(Number(button.dataset.rating));
    }

    function keydown(event) {
        if (!event.repeat && /^[1-5]$/.test(event.key)) rate(Number(event.key));
    }

    root.addEventListener("click", click);
    document.addEventListener("keydown", keydown);
    return {
        async update({contents, upcoming, response: handle}) {
            latest = handle;
            response = null;
            for (const next of upcoming) new Image().src = next.url;
            picture.src = contents.url;
            picture.alt = contents.name;
            try {
                await picture.decode();
            } catch (error) {
                psynet.log.warn(`Couldn't decode ${contents.url}: ${error}`);
            }
            // A rejected answer can show another trial while this one loads.
            if (latest !== handle) return;
            picture.style.visibility = "visible";
            response = handle;
            handle.startClock();
        },
        cleanup() {
            root.removeEventListener("click", click);
            document.removeEventListener("keydown", keydown);
        },
    };
}
