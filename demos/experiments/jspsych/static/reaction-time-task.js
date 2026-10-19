export function buildTimeline({jsPsych, vars}) {
    const timeline = [];

    const preload = {
        type: jsPsychPreload,
        images: ["/static/img/blue.png", "/static/img/orange.png"]
    };
    timeline.push(preload);

    const welcome = {
        type: jsPsychHtmlKeyboardResponse,
        stimulus: vars["welcome_message"]
    };
    timeline.push(welcome);

    const instructions = {
        type: jsPsychHtmlKeyboardResponse,
        stimulus: `
            <p>In this experiment, a circle will appear in the center
            of the screen.</p><p>If the circle is <strong>blue</strong>,
            press the letter F on the keyboard as fast as you can.</p>
            <p>If the circle is <strong>orange</strong>, press the letter J
            as fast as you can.</p>
            <div style='width: 700px;'>
            <div style='float: left;'><img src='/static/img/blue.png'></img>
            <p class='small'><strong>Press the F key</strong></p></div>
            <div style='float: right;'><img src='/static/img/orange.png'></img>
            <p class='small'><strong>Press the J key</strong></p></div>
            </div>
            <p>Press any key to begin.</p>
        `,
        post_trial_gap: 2000
    };
    timeline.push(instructions);

    const testStimuli = [
        {stimulus: "/static/img/blue.png", correct_response: "f"},
        {stimulus: "/static/img/orange.png", correct_response: "j"}
    ];

    const fixation = {
        type: jsPsychHtmlKeyboardResponse,
        stimulus: '<div style="font-size:60px;">+</div>',
        choices: "NO_KEYS",
        trial_duration: function () {
            return jsPsych.randomization.sampleWithoutReplacement(
                vars["trial_durations"],
                1
            )[0];
        },
        data: {
            task: "fixation"
        }
    };

    const test = {
        type: jsPsychImageKeyboardResponse,
        stimulus: jsPsych.timelineVariable("stimulus"),
        choices: ["f", "j"],
        data: {
            task: "response",
            correct_response: jsPsych.timelineVariable("correct_response")
        },
        on_finish: function (data) {
            data.correct = jsPsych.pluginAPI.compareKeys(
                data.response,
                data.correct_response
            );
        }
    };

    timeline.push({
        timeline: [fixation, test],
        timeline_variables: testStimuli,
        repetitions: 5,
        randomize_order: true
    });

    timeline.push({
        type: jsPsychHtmlKeyboardResponse,
        stimulus: function () {
            const trials = jsPsych.data.get().filter({task: "response"});
            const correctTrials = trials.filter({correct: true});
            const accuracy = Math.round(
                correctTrials.count() / trials.count() * 100
            );
            const rt = Math.round(correctTrials.select("rt").mean());
            return `<p>You responded correctly on ${accuracy}% of the trials.</p>
                <p>Your average response time was ${rt}ms.</p>
                <p>Press any key to complete the experiment. Thank you!</p>`;
        }
    });

    return timeline;
}
