from typing import Optional

from psynet.timeline import CodeBlock

from .page import RejectedConsentPage
from .timeline import Elt, Module, NullElt, Page, conditional, get_template, join


class Consent(Elt):
    """
    Inherit from this class to mark a timeline element as being part of a consent form.
    PsyNet requires you have at least one such element in your timeline,
    to make sure you don't forget to include a consent form.
    See ``LabRecruiterAudiovisualConsentPage`` for an example.
    If you're sure you want to omit the consent form, include a ``NoConsent``
    element in your timeline.
    """

    is_consent = True


class NoConsent(Consent, NullElt):
    """
    If you want to have no consent form in your timeline, use this element as an empty placeholder.
    """

    pass


#################
# Lab Recruiter #
#################
class LabRecruiterStandardConsent(Module):
    """
    The Lab Recruiter standard consent form.

    Parameters
    ----------

    time_estimate:
        Time estimated for the page.
    """

    def __init__(
        self,
        time_estimate: Optional[float] = 30,
    ):
        label = "lab-recruiter_standard_consent"
        elts = join(
            self.LabRecruiterStandardConsentPage(time_estimate=time_estimate),
            conditional(
                "lab-recruiter_standard_consent_conditional",
                lambda experiment, participant: (
                    not participant.answer["lab-recruiter_standard_consent"]
                ),
                RejectedConsentPage(),
            ),
            CodeBlock(
                lambda participant: participant.var.set(
                    "lab-recruiter_standard_consent",
                    participant.answer["lab-recruiter_standard_consent"],
                )
            ),
        )
        super().__init__(label, elts)

    class LabRecruiterStandardConsentPage(Page, Consent):
        """
        This page displays the Lab Recruiter standard consent page.

        Parameters
        ----------

        time_estimate:
            Time estimated for the page.
        """

        expect_scrolling = True

        def __init__(
            self,
            time_estimate: Optional[float] = 30,
        ):
            super().__init__(
                time_estimate=time_estimate,
                template_str=get_template(
                    "consents/cap-recruiter_standard_consent.html"
                ),
                framework_owned_template=True,
            )

        def format_answer(self, raw_answer, **kwargs):
            return {"lab-recruiter_standard_consent": raw_answer}

        def get_bot_response(self, experiment, bot):
            return {
                "lab-recruiter_standard_consent": True,
            }


class LabRecruiterAudiovisualConsent(Module):
    """
    The Lab Recruiter audiovisual recordings consent form.

    Parameters
    ----------

    time_estimate:
        Time estimated for the page.
    """

    def __init__(
        self,
        time_estimate: Optional[float] = 30,
    ):
        label = "lab-recruiter_audiovisual_consent"
        elts = join(
            self.LabRecruiterAudiovisualConsentPage(time_estimate=time_estimate),
            conditional(
                "lab-recruiter_audiovisual_consent_conditional",
                lambda experiment, participant: (
                    not participant.answer["lab-recruiter_audiovisual_consent"]
                ),
                RejectedConsentPage(),
            ),
            CodeBlock(
                lambda participant: participant.var.set(
                    "lab-recruiter_audiovisual_consent",
                    participant.answer["lab-recruiter_audiovisual_consent"],
                )
            ),
            CodeBlock(
                lambda participant: participant.var.set(
                    "lab-recruiter_demonstration_purposes_consent",
                    participant.answer["demonstration_purposes_consent"],
                )
            ),
        )
        super().__init__(label, elts)

    class LabRecruiterAudiovisualConsentPage(Page, Consent):
        """
        This page displays the Lab Recruiter audiovisual consent page.

        Parameters
        ----------

        time_estimate:
            Time estimated for the page.
        """

        expect_scrolling = True

        def __init__(
            self,
            time_estimate: Optional[float] = 30,
        ):
            super().__init__(
                time_estimate=time_estimate,
                template_str=get_template(
                    "consents/cap-recruiter_audiovisual_consent.html"
                ),
                framework_owned_template=True,
            )

        def format_answer(self, raw_answer, **kwargs):
            return {
                "lab-recruiter_audiovisual_consent": raw_answer,
                "demonstration_purposes_consent": kwargs["metadata"][
                    "demonstration_purposes_consent"
                ],
            }

        def get_bot_response(self, experiment, bot):
            return {
                "lab-recruiter_audiovisual_consent": True,
                "demonstration_purposes_consent": True,
            }


# Backward compatibility aliases
CAPRecruiterStandardConsent = LabRecruiterStandardConsent
CAPRecruiterAudiovisualConsent = LabRecruiterAudiovisualConsent


#########
# Lucid #
#########
class LucidConsent(Module):
    """
    The Lucid consent form.

    Parameters
    ----------

    time_estimate:
        Time estimated for the page.
    """

    def __init__(
        self,
        time_estimate: Optional[float] = 30,
    ):
        label = "lucid_consent"
        elts = join(
            self.LucidConsentPage(time_estimate=time_estimate),
            conditional(
                "lucid_consent_conditional",
                lambda experiment, participant: not participant.answer["lucid_consent"],
                RejectedConsentPage(),
            ),
            CodeBlock(
                lambda participant: participant.var.set(
                    "lucid_consent",
                    participant.answer["lucid_consent"],
                )
            ),
        )
        super().__init__(label, elts)

    class LucidConsentPage(Page, Consent):
        """
        This page displays the Lucid consent page.

        Parameters
        ----------

        time_estimate:
            Time estimated for the page.
        """

        expect_scrolling = True

        def __init__(
            self,
            time_estimate: Optional[float] = 30,
        ):
            super().__init__(
                time_estimate=time_estimate,
                template_str=get_template("consents/lucid_consent.html"),
                framework_owned_template=True,
            )

        def format_answer(self, raw_answer, **kwargs):
            return {"lucid_consent": raw_answer}

        def get_bot_response(self, experiment, bot):
            return {"lucid_consent": True}


#############
# Princeton #
#############
class PrincetonConsent(Module):
    """
    The Princeton University consent form.

    Parameters
    ----------

    time_estimate:
        Time estimated for the page.
    """

    def __init__(
        self,
        time_estimate: Optional[float] = 30,
    ):
        label = "princeton_consent"
        elts = join(
            self.PrincetonConsentPage(time_estimate=time_estimate),
            conditional(
                "princeton_consent_conditional",
                lambda experiment, participant: (
                    not participant.answer["princeton_consent"]
                ),
                RejectedConsentPage(),
            ),
            CodeBlock(
                lambda participant: participant.var.set(
                    "princeton_consent", participant.answer["princeton_consent"]
                )
            ),
        )
        super().__init__(label, elts)

    class PrincetonConsentPage(Page, Consent):
        """
        This page displays the Princeton University consent page.

        Parameters
        ----------

        time_estimate:
            Time estimated for the page.
        """

        expect_scrolling = True

        def __init__(
            self,
            time_estimate: Optional[float] = 30,
        ):
            super().__init__(
                time_estimate=time_estimate,
                template_str=get_template("consents/princeton_consent.html"),
                framework_owned_template=True,
            )

        def format_answer(self, raw_answer, **kwargs):
            return {"princeton_consent": raw_answer}

        def get_bot_response(self, experiment, bot):
            return {"princeton_consent": True}


class PrincetonLabRecruiterConsent(Module):
    """
    The Princeton University consent form to be used in conjunction with Lab Recruiter.

    Parameters
    ----------

    time_estimate:
        Time estimated for the page.
    """

    def __init__(
        self,
        time_estimate: Optional[float] = 30,
    ):
        label = "princeton_lab_recruiter_consent"
        elts = join(
            self.PrincetonLabRecruiterConsentPage(time_estimate=time_estimate),
            conditional(
                "princeton_lab_recruiter_consent_conditional",
                lambda experiment, participant: (
                    not participant.answer["princeton_lab_recruiter_consent"]
                ),
                RejectedConsentPage(),
            ),
            CodeBlock(
                lambda participant: participant.var.set(
                    "princeton_lab_recruiter_consent",
                    participant.answer["princeton_lab_recruiter_consent"],
                )
            ),
        )
        super().__init__(label, elts)

    class PrincetonLabRecruiterConsentPage(Page, Consent):
        """
        This page displays the Princeton University consent page to be used in conjunction with Lab Recruiter.

        Parameters
        ----------

        time_estimate:
            Time estimated for the page.
        """

        expect_scrolling = True

        def __init__(
            self,
            time_estimate: Optional[float] = 30,
        ):
            super().__init__(
                time_estimate=time_estimate,
                template_str=get_template(
                    "consents/princeton_lab_recruiter_consent.html"
                ),
                framework_owned_template=True,
            )

        def format_answer(self, raw_answer, **kwargs):
            return {"princeton_lab_recruiter_consent": raw_answer}

        def get_bot_response(self, experiment, bot):
            return {"princeton_lab_recruiter_consent": True}


# Backward compatibility alias
PrincetonCAPRecruiterConsent = PrincetonLabRecruiterConsent


########
# Main #
########
class MainConsent(Module):
    """
    The main consent form.

    Parameters
    ----------

    time_estimate:
        Time estimated for the page.
    """

    def __init__(
        self,
        time_estimate: Optional[float] = 30,
    ):
        label = "main_consent"
        elts = join(
            self.MainConsentPage(time_estimate=time_estimate),
            conditional(
                "main_consent_conditional",
                lambda experiment, participant: not participant.answer["main_consent"],
                RejectedConsentPage(failure_tags=["main_consent_rejected"]),
            ),
            CodeBlock(
                lambda participant: participant.var.set(
                    "main_consent", participant.answer["main_consent"]
                )
            ),
        )
        super().__init__(label, elts)

    class MainConsentPage(Page, Consent):
        """
        This page displays the main consent page.

        Parameters
        ----------

        time_estimate:
            Time estimated for the page.
        """

        expect_scrolling = True

        def __init__(
            self,
            time_estimate: Optional[float] = 30,
        ):
            super().__init__(
                time_estimate=time_estimate,
                template_str=get_template("consents/main_consent.html"),
                framework_owned_template=True,
            )

        def format_answer(self, raw_answer, **kwargs):
            return {"main_consent": raw_answer}

        def get_bot_response(self, experiment, bot):
            return {"main_consent": True}


############
# Database #
############
class DatabaseConsent(Module):
    """
    The database consent form.

    Parameters
    ----------

    time_estimate:
        Time estimated for the page.
    """

    def __init__(
        self,
        time_estimate: Optional[float] = 30,
    ):
        label = "database_consent"
        elts = join(
            self.DatabaseConsentPage(time_estimate=time_estimate),
            conditional(
                "database_consent_conditional",
                lambda experiment, participant: (
                    not participant.answer["database_consent"]
                ),
                RejectedConsentPage(failure_tags=["database_consent_rejected"]),
            ),
            CodeBlock(
                lambda participant: participant.var.set(
                    "database_consent", participant.answer["database_consent"]
                )
            ),
        )
        super().__init__(label, elts)

    class DatabaseConsentPage(Page, Consent):
        """
        This page displays the database consent page.

        Parameters
        ----------

        time_estimate:
            Time estimated for the page.
        """

        expect_scrolling = True

        def __init__(
            self,
            time_estimate: Optional[float] = 30,
        ):
            super().__init__(
                time_estimate=time_estimate,
                template_str=get_template("consents/database_consent.html"),
                framework_owned_template=True,
            )

        def format_answer(self, raw_answer, **kwargs):
            return {"database_consent": raw_answer}

        def get_bot_response(self, experiment, bot):
            return {"database_consent": True}


###############
# Audiovisual #
###############
class AudiovisualConsent(Module):
    """
    The audiovisual consent form.

    Parameters
    ----------

    time_estimate:
        Time estimated for the page.
    """

    def __init__(
        self,
        time_estimate: Optional[float] = 30,
    ):
        label = "audiovisual_consent"
        elts = join(
            self.AudiovisualConsentPage(time_estimate=time_estimate),
            conditional(
                "audiovisual_consent_conditional",
                lambda experiment, participant: (
                    not participant.answer["audiovisual_consent"]
                ),
                RejectedConsentPage(failure_tags=["audiovisual_consent_rejected"]),
            ),
            CodeBlock(
                lambda participant: participant.var.set(
                    "audiovisual_consent", participant.answer["audiovisual_consent"]
                )
            ),
        )
        super().__init__(label, elts)

    class AudiovisualConsentPage(Page, Consent):
        """
        This page displays the audiovisual consent page.

        Parameters
        ----------

        time_estimate:
            Time estimated for the page.
        """

        expect_scrolling = True

        def __init__(
            self,
            time_estimate: Optional[float] = 30,
        ):
            super().__init__(
                time_estimate=time_estimate,
                template_str=get_template("consents/audiovisual_consent.html"),
                framework_owned_template=True,
            )

        def format_answer(self, raw_answer, **kwargs):
            return {"audiovisual_consent": raw_answer}

        def get_bot_response(self, experiment, bot):
            return {"audiovisual_consent": True}


################
# Open science #
################
class OpenScienceConsent(Module):
    """
    The open science consent form.

    Parameters
    ----------

    time_estimate:
        Time estimated for the page.
    """

    def __init__(
        self,
        time_estimate: Optional[float] = 30,
    ):
        label = "open_science_consent"
        elts = join(
            self.OpenScienceConsentPage(time_estimate=time_estimate),
            conditional(
                "open_science_consent_conditional",
                lambda experiment, participant: (
                    not participant.answer["open_science_consent"]
                ),
                RejectedConsentPage(failure_tags=["open_science_consent_rejected"]),
            ),
            CodeBlock(
                lambda participant: participant.var.set(
                    "open_science_consent", participant.answer["open_science_consent"]
                )
            ),
        )
        super().__init__(label, elts)

    class OpenScienceConsentPage(Page, Consent):
        """
        This page displays the open science consent page.

        Parameters
        ----------

        time_estimate:
            Time estimated for the page.
        """

        expect_scrolling = True

        def __init__(
            self,
            time_estimate: Optional[float] = 30,
        ):
            super().__init__(
                time_estimate=time_estimate,
                template_str=get_template("consents/open_science_consent.html"),
                framework_owned_template=True,
            )

        def format_answer(self, raw_answer, **kwargs):
            return {"open_science_consent": raw_answer}

        def get_bot_response(self, experiment, bot):
            return {"open_science_consent": True}


################################################
# Voluntary participation with no compensation #
################################################
class VoluntaryWithNoCompensationConsent(Module):
    """
    The voluntary participation with no compensation consent form.

    Parameters
    ----------

    time_estimate:
        Time estimated for the page.
    """

    def __init__(
        self,
        time_estimate: Optional[float] = 30,
    ):
        label = "voluntary_with_no_compensation_consent"
        elts = join(
            self.VoluntaryWithNoCompensationConsentPage(time_estimate=time_estimate),
            conditional(
                "voluntary_with_no_compensation_consent_conditional",
                lambda experiment, participant: (
                    not participant.answer["voluntary_with_no_compensation_consent"]
                ),
                RejectedConsentPage(
                    failure_tags=["voluntary_with_no_compensation_consent_rejected"]
                ),
            ),
            CodeBlock(
                lambda participant: participant.var.set(
                    "voluntary_with_no_compensation_consent",
                    participant.answer["voluntary_with_no_compensation_consent"],
                )
            ),
        )
        super().__init__(label, elts)

    class VoluntaryWithNoCompensationConsentPage(Page, Consent):
        """
        This page displays the voluntary participation with no compensation consent page.

        Parameters
        ----------

        time_estimate:
            Time estimated for the page.
        """

        expect_scrolling = True

        def __init__(
            self,
            time_estimate: Optional[float] = 30,
        ):
            super().__init__(
                time_estimate=time_estimate,
                template_str=get_template(
                    "consents/voluntary_with_no_compensation_consent.html"
                ),
                framework_owned_template=True,
            )

        def format_answer(self, raw_answer, **kwargs):
            return {"voluntary_with_no_compensation_consent": raw_answer}

        def get_bot_response(self, experiment, bot):
            return {"voluntary_with_no_compensation_consent": True}
