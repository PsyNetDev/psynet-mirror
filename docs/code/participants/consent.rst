=======
Consent
=======

Every timeline needs at least one consent page, or
:class:`~psynet.consent.NoConsent` if the study needs none; deployment fails
without one. Put the consent page at the start of the timeline.

Built-in consent forms
----------------------

The consent forms in :mod:`psynet.consent` were written for particular
institutions and ethics approvals, and their text names those institutions
and researchers:

- :class:`~psynet.consent.MainConsent`,
  :class:`~psynet.consent.LucidConsent` and
  :class:`~psynet.consent.VoluntaryWithNoCompensationConsent` say the study is
  run by the Max Planck Institute for Empirical Aesthetics (MPIEA);
- :class:`~psynet.consent.AudiovisualConsent`,
  :class:`~psynet.consent.OpenScienceConsent` and
  :class:`~psynet.consent.DatabaseConsent` add consent for recordings,
  published data or a participant database, and name an MPIEA researcher as
  the contact;
- :class:`~psynet.consent.LabRecruiterStandardConsent` and
  :class:`~psynet.consent.LabRecruiterAudiovisualConsent` are MPIEA's Lab
  Recruiter forms;
- :class:`~psynet.consent.PrincetonConsent` and
  :class:`~psynet.consent.PrincetonLabRecruiterConsent` are Princeton
  University's forms.

Use a built-in form only if your study is covered by that approval. CINT
recruitment requires :class:`~psynet.consent.LucidConsent` (see
:ref:`lab-deployment-cint`). Otherwise, write your own consent page with the
text your ethics committee approved.

Writing your own consent page
-----------------------------

A consent page is any page that also inherits from
:class:`~psynet.consent.Consent`. This one asks the participant to agree and
sends those who decline to the rejected-consent ending:

.. code-block:: python

    from markupsafe import Markup

    from psynet.consent import Consent
    from psynet.modular_page import ModularPage, PushButtonControl
    from psynet.page import RejectedConsentPage
    from psynet.timeline import conditional, join


    class StudyConsentPage(ModularPage, Consent):
        expect_scrolling = True

        def __init__(self):
            super().__init__(
                "consent",
                Markup(
                    "<h1>Consent to take part</h1>"
                    "<p>Replace this with the text your ethics committee approved.</p>"
                ),
                PushButtonControl(
                    ["agree", "decline"],
                    labels=["I agree", "I do not agree"],
                    arrange_vertically=False,
                ),
                time_estimate=30,
                bot_response="agree",
            )


    def study_consent():
        return join(
            StudyConsentPage(),
            conditional(
                "consent_declined",
                lambda participant: participant.answer != "agree",
                RejectedConsentPage(failure_tags=["consent_declined"]),
            ),
        )

Then start the timeline with ``study_consent()``. ``expect_scrolling = True``
tells PsyNet's layout checks that a long consent text may scroll. For a
longer form, build the text with ``dominate`` tags as described in
:doc:`/code/writing_pages`.
