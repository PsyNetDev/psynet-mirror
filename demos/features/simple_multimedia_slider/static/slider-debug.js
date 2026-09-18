export async function activate({root, trial, psynet}) {
    const slider = psynet.page.control.slider.element;

    function updateValue() {
        root.querySelector("#slider-audio").textContent = slider.audio;
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
