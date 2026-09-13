from typing import List, Optional, Union

import dominate
from dominate import tags

from psynet import exit as exit_domain
from psynet.modular_page import NullControl
from psynet.timeline import (
    CodeBlock,
    Elt,
    EltCollection,
    Page,
    PageMaker,
    TimelineLogic,
    join,
)
from psynet.utils import get_translator


class ExitLogic(EltCollection):
    """Shared recruiter release behavior for terminal timeline branches."""

    def release_participant(self, experiment, participant) -> TimelineLogic:
        """Return the recruiter-specific participant handoff."""
        try:
            return experiment.recruiter.release_participant(experiment, participant)
        except AttributeError:
            raise ValueError(
                f"The selected recruiter ({experiment.recruiter}) is not fully implemented in PsyNet. "
                "No release_participant method was found."
            )


class EndLogic(ExitLogic):
    """Show a terminal debrief before recruiter release."""

    exit_context: exit_domain.ExitContext

    def resolve(self) -> Union[Elt, List[Elt]]:
        return join(
            CodeBlock(self.prepare_debrief),
            PageMaker(self.debrief_participant, time_estimate=0.0),
            CodeBlock(self.after_debrief),
            PageMaker(self.release_participant, time_estimate=0.0),
        )

    def prepare_debrief(self, experiment, participant) -> None:
        """Apply outcome state, then store its recruiter exit decision."""
        self.before_debrief(experiment, participant)
        self.prepare_exit(experiment, participant)

    def before_debrief(self, experiment, participant) -> None:
        pass

    def debrief_participant(self, experiment, participant) -> TimelineLogic:
        raise NotImplementedError

    def prepare_exit(self, experiment, participant) -> None:
        """Store the recruiter decision shared by debrief and settlement."""
        plan = exit_domain._stored_exit_plan(participant)
        if plan is not None and (
            plan.status is exit_domain.ExitPlanStatus.COMMITTED
            or plan.context is exit_domain.ExitContext.ERROR_RECOVERY
        ):
            return
        plan = experiment.plan_exit(
            participant,
            self.exit_context,
        )
        participant.exit_plan = plan.mark_committed().to_dict()

    def after_debrief(self, experiment, participant) -> None:
        from psynet.bot import Bot

        if isinstance(participant, Bot):
            participant.status = "approved"

    def debrief_page(
        self, content, experiment, participant, show_finish_button=True
    ) -> TimelineLogic:
        from .modular_page import ModularPage, PushButtonControl

        _ = get_translator()

        # Todo - Once automatic translation is updated, revisit the logic in
        # RejectedConsentPage and ask the participant to return their platform
        # submission if appropriate.
        if show_finish_button:
            # The choice key "Finish" stays untranslated so that recorded answers
            # are locale-independent; only the visible label is translated.
            control = PushButtonControl(["Finish"], labels=[_("Finish")])
        else:
            control = NullControl()

        return ModularPage(
            self.__class__.__name__,
            content,
            control,
            show_next_button=False,
        )

    @property
    def should_show_reward(self) -> bool:
        """See :attr:`psynet.experiment.Experiment.show_reward`.

        Lucid needs no special case here: it hides rewards by default and
        refuses an explicit opt-in.
        """
        from psynet.experiment import get_experiment

        return get_experiment().show_reward

    def summarize_reward(self, experiment, participant):
        """Return HTML summarizing the participant's time and performance rewards."""
        from psynet.utils import get_config

        config = get_config()
        _p = get_translator(context=True)

        # Todo - translation should not have HTML hard-coded.
        # Fix that and then refactor using dominate package.
        currency = config.get("currency")
        performance_reward = participant.performance_reward or 0.0

        text = _p(
            "final-page-rewards",
            "You will receive a reward of <strong>{CURRENCY}{TIME_REWARD}</strong> for the time you spent. ",
        ).format(
            CURRENCY=currency,
            TIME_REWARD=f"{participant.time_reward:.2f}",
        )

        if round(performance_reward, 2) != 0:
            text += _p(
                "final-page-performance-reward",
                "You have also been awarded a performance reward of <strong>{CURRENCY}"
                "{PERFORMANCE_REWARD}</strong>. ",
            ).format(
                CURRENCY=currency,
                PERFORMANCE_REWARD=f"{performance_reward:.2f}",
            )

        return dominate.util.raw(text)

    def _finish_next_step(self, experiment) -> str:
        """Tell the participant what Finish does on this debrief."""
        _ = get_translator()
        if experiment.with_lucid_recruitment():
            return _("Click Finish to return to your panel.")
        return _("Click Finish to finalize the session.")


class SuccessfulEndLogic(EndLogic):
    exit_context = exit_domain.ExitContext.SUCCESSFUL

    def after_debrief(self, experiment, participant):
        super().after_debrief(experiment, participant)
        participant.complete = True
        participant.progress = 1.0

    def debrief_participant(self, experiment, participant) -> TimelineLogic:
        _ = get_translator()
        _p = get_translator(context=True)

        html = tags.span()

        with html:
            tags.h1(_p("final_page_successful", "That's the end!"))

            if self.should_show_reward:
                tags.p(self.summarize_reward(experiment, participant))

            tags.p(_("Thank you for taking part."))
            tags.p(self._finish_next_step(experiment))

        return self.debrief_page(html, experiment, participant)


class ErrorRecoveryPage(Page):
    """Timeline wrapper around the recruiter's tracked error-recovery page."""

    requires_full_page_reload = True

    def __init__(self):
        super().__init__(
            time_estimate=0.0,
            delegated_render=True,
            requires_full_page_reload=True,
            save_answer=False,
            show_early_exit_button=False,
            label="error_recovery",
        )

    def render(self, experiment, participant, partial_mode=False):
        """Render recruiter-specific recovery copy as a successful timeline page."""
        assert not partial_mode
        from psynet.utils import get_locale

        plan = exit_domain._stored_exit_plan(participant)
        return experiment._render_error_page(
            participant=participant,
            plan=plan,
            recruiter=experiment.recruiter,
            error_text=None,
            external_submit_url=None,
            locale=get_locale(),
        )


class RecordedSubmissionPage(Page):
    """Timeline wrapper for the shared Prolific confirmation document.

    ``/timeline`` and ``/recruiter-exit`` both render
    ``exit_recruiter_prolific_submitted.html`` through
    ``recruiter.exit_response()``, so this page must not use timeline chrome,
    a progress bar, or a reward footer. It does not store confirmation copy;
    that lives on the recruiter (``_recorded_submission_copy``).
    """

    requires_full_page_reload = True

    def __init__(self):
        super().__init__(
            time_estimate=0.0,
            delegated_render=True,
            requires_full_page_reload=True,
            save_answer=False,
            show_early_exit_button=False,
            label="prolific_submission_sent",
        )

    def render(self, experiment, participant, partial_mode=False):
        """Render the shared Prolific confirmation document."""
        assert not partial_mode
        from flask import make_response

        response = make_response(
            experiment.recruiter.exit_response(experiment, participant)
        )
        response.headers["Cache-Control"] = "no-store"
        return response


class ImmediateExitLogic(ExitLogic):
    """Show prepared error recovery when the recruiter has something to ask."""

    def resolve(self) -> Union[Elt, List[Elt]]:
        return PageMaker(self._release_sequence, time_estimate=0.0)

    def _release_sequence(self, experiment, participant) -> TimelineLogic:
        """Insert recovery UI only when the recruiter presents it."""
        plan = exit_domain._stored_exit_plan(participant)
        recovery_page = (
            ErrorRecoveryPage()
            if plan is not None
            and plan.context is exit_domain.ExitContext.ERROR_RECOVERY
            and plan.status is exit_domain.ExitPlanStatus.PREPARED
            and experiment.recruiter.shows_error_recovery_page(plan)
            else None
        )
        return join(
            recovery_page,
            PageMaker(self.release_participant, time_estimate=0.0),
        )


class UnsuccessfulEndLogic(EndLogic):
    exit_context = exit_domain.ExitContext.UNSUCCESSFUL

    def __init__(self, failure_tags: Optional[List] = None, **kwargs):
        super().__init__()

        if failure_tags is None:
            failure_tags = []
        failure_tags = [*failure_tags, "UnsuccessfulEndPage"]
        self.failure_tags = failure_tags

        if "template_filename" in kwargs:
            raise ValueError(
                "UnsuccessfulEndPage no longer accepts a template_filename argument. "
                "Instead you should customize its content by subclassing its message attribute."
            )

    def before_debrief(self, experiment, participant) -> None:
        super().before_debrief(experiment, participant)
        participant.append_failure_tags(*self.failure_tags)
        participant.fail()

    def debrief_participant(self, experiment, participant) -> TimelineLogic:
        _ = get_translator()
        _p = get_translator(context=True)

        html = tags.span()

        with html:
            tags.h1(
                _p(
                    "final_page_unsuccessful",
                    "Unfortunately we have to stop early.",
                )
            )

            if self.should_show_reward:
                tags.p(
                    _p(
                        "final_page_unsuccessful",
                        "However, you will still be paid for the time you spent already.",
                    )
                )
                tags.p(self.summarize_reward(experiment, participant))

            tags.p(_("Thank you for taking part."))
            tags.p(self._finish_next_step(experiment))

        return self.debrief_page(html, experiment, participant)


class RejectedConsentLogic(UnsuccessfulEndLogic):
    exit_context = exit_domain.ExitContext.REJECTED_CONSENT

    def before_debrief(self, experiment, participant) -> None:
        super().before_debrief(experiment, participant)

        # For Lucid recruitment, terminate the participant on Lucid's side
        # before showing the page, since the auto-redirect bypasses the normal
        # release_participant flow (user won't click Finish)
        if experiment.with_lucid_recruitment():
            experiment.recruiter.terminate_participant(
                participant=participant, reason="consent-rejected"
            )

        participant.recruiter.after_rejected_consent(experiment, participant)

    def debrief_participant(self, experiment, participant) -> TimelineLogic:
        _ = get_translator()
        _p = get_translator(context=True)

        html = tags.span()

        with html:
            tags.h1(_p("final_page_rejected_consent", "You chose not to continue."))
            tags.p(_p("final_page_rejected_consent", "You may close this page."))

            # For Lucid recruitment, auto-redirect back to Lucid
            if experiment.with_lucid_recruitment():
                tags.p(_("We will return you to your panel in a few seconds."))
                # Consent reject is a terminate, not a panel Complete: progress
                # may be 1 after debrief bookkeeping, but that is estimated
                # timeline used, not Lucid RIS 10.
                external_submit_url = experiment.recruiter.external_submit_url(
                    participant=participant,
                    allow_complete=False,
                )
                tags.script(
                    dominate.util.raw(
                        f'setTimeout(() => {{ window.location = "{external_submit_url}"; }}, 2000)'
                    )
                )

        return self.debrief_page(
            html, experiment, participant, show_finish_button=False
        )
