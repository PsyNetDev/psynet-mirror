export async function activate({root, trial, vars, psynet}) {
    const slider = psynet.page.control.slider.element;

    function findClosestAudio() {
        const mediaLocations = vars.media_locations;
        const locations = Object.values(mediaLocations);
        const value = slider.getAttribute("random-wrap") === "true"
            ? slider.getAttribute("output-value")
            : slider.value;
        const nearest = psynet.utils.closest(parseFloat(value), locations);
        return Object.keys(mediaLocations)[nearest.index];
    }

    function updateValue() {
        root.querySelector("#slider-audio").textContent = findClosestAudio();
        root.querySelector("#slider-raw-value").textContent =
            parseFloat(slider.getAttribute("raw-value")).toFixed(2);
        root.querySelector("#slider-output-value").textContent =
            parseFloat(slider.getAttribute("output-value")).toFixed(2);
        root.querySelector("#phase").textContent =
            parseFloat(slider.getAttribute("phase")).toFixed(2);
        root.querySelector("#random-wrap").textContent =
            slider.getAttribute("random-wrap");
    }

    trial.onEvent("trialConstruct", function () {
        trial.setRepeatingTimer(updateValue, 100);
    });
}
