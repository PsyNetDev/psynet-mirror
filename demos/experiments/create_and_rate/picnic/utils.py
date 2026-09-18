# pylint: disable=unused-import,abstract-method,unused-argument
from markupsafe import Markup

from psynet.modular_page import ModularPage, Prompt, TextControl
from psynet.page import InfoPage
from psynet.timeline import join
from psynet.utils import get_logger

logger = get_logger()

instructions = join(
    InfoPage(
        Markup(
            """
            <h1>Welcome to the Picnic game!</h1>
            <p>
                In this game, you will be asked to guess a secret rule that describes a set of items that must be
                 included (positive examples) and a set of items that must be excluded (negative examples).

                You will then be asked to rate the guesses submitted by other participants.
                You will switch between these two roles multiple times during the experiment.
            </p>
            """
        ),
        time_estimate=2,
    ),
    InfoPage(
        Markup(
            """
            <h1>Guess a Rule</h1>
            <p>
                Let's say you are asked to guess a rule that describes the following examples:
                <br>
                <div class="row">
                    <div class="col text-success text-center p-3">
                        <p>
                            <span class="font-weight-bold">Here are items that are included (positive examples):</span>
                        </p>
                        maple tree, sunflower, bamboo
                    </div>
                    <div class="col text-danger text-center p-3">
                        <p>
                            <span class="font-weight-bold">Here are items that are excluded (negative examples):</span>
                        </p>
                        brick, basket, dog
                    </div>
                </div>

                You might guess that the rule is "<strong>only plants</strong>".

                An example for a bad guess would be "<strike><strong>only trees</strong></strike>", because it doesn't cover all the positive examples.
            </p>
            """
        ),
        time_estimate=5,
    ),
    InfoPage(
        Markup(
            """
            <h1>Rate Guesses</h1>
            <p>
                Let's say other players were asked to guess a rule that describes the following examples:
                <br>
                <div class="row">
                    <div class="col text-success text-center p-3">
                        <p>
                            <span class="font-weight-bold">Here are items that are included (positive examples):</span>
                        </p>
                        maple tree, sunflower, bamboo
                    </div>
                    <div class="col text-danger text-center p-3">
                        <p>
                            <span class="font-weight-bold">Here are items that are excluded (negative examples):</span>
                        </p>
                        brick, basket, dog
                    </div>
                </div>

                The intended rule was: "<strong>only plants</strong>".
                <br>
                Players submitted the following guesses:
                <ul>
                    <li>only trees</li>
                    <li>Just Plants</li>
                </ul>

                You should check the guesses that are correct and uncheck the guesses that are incorrect, i.e.:
                 <div class="form-check">
                    <input class="form-check-input" type="checkbox" disabled>
                    <label class="form-check-label">only trees</label>
                </div>
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" disabled checked>
                    <label class="form-check-label">Just Plants</label>
                </div>
                <br>
                <div class="alert alert-primary" role="alert">
                    <strong>Note:</strong> You are only rating if the meaning of the guessed rule matches the intended rule. You can ignore differences in spelling and phrasing.
                </div>
            """
        ),
        time_estimate=5,
        css=[
            """
            .form-check-input:disabled ~ .form-check-label,
            .form-check-input[disabled] ~ .form-check-label {
                color: #000;
            }
            """
        ],
    ),
    InfoPage(
        Markup(
            """
            <p>
                The experiment starts on the next page.
            </p>
            <div class="alert alert-warning" role="alert">
                <strong>Important</strong> You will be asked to rate the guesses of other players. If you provide
                 low quality guesses, the experiment will terminate early and you will be compensated for the time
                 spent.
            </div>
            """
        ),
        time_estimate=5,
    ),
)

final_questionnaire = join(
    ModularPage(
        "strategy",
        Prompt(
            """
        Please tell us in a few words about your experience taking the task.
        What was your strategy?
        Did you find the task easy or difficult?
        Did you find it interesting or boring?
        """
        ),
        control=TextControl(one_line=False),
        time_estimate=10,
    ),
    ModularPage(
        "technical",
        Prompt(
            """
        Did you experience any technical problems during the task?
        If so, please describe them.
        """
        ),
        control=TextControl(one_line=False),
        time_estimate=10,
    ),
)
