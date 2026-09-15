SurveyJS
========

Source: ``demos/experiments/survey_js``

PsyNet integrates with SurveyJS, a flexible survey design tool that is particularly
good for implementing questionnaires and multi-response interfaces.
One uses the ``SurveyJSControl`` class, and passes it a JSON-style dictionary
which contains all the survey specifications.

The recommended way to design a SurveyJS survey is to use their free
`Survey Creator <https://surveyjs.io/create-free-survey>`_ tool.
You design your survey using the interactive editor.
Once you are done, click the "JSON Editor" tab. Copy and paste the provided JSON
into the ``design`` argument of your ``SurveyJSControl``. You may need to update a few details
to match Python syntax, for example replacing ``true`` with ``True``; your syntax highlighter
should flag up points that need updating. That's it!

Note, near the bottom of the script, the use of the argument ``bot_response``.
This is used to tell PsyNet how to simulate the response of a participant to a given page,
and is most commonly used by automated tests.
We provide it with a function that generates the kind of questionnaire response that a real
participant might produce. In the current example the function just hard-codes a value,
but alternatively this function could include a random component, and it could refer to
the state of the participant itself.


.. literalinclude:: ../../demos/experiments/survey_js/experiment.py
   :language: python
