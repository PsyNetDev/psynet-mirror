"""Domain models for participant exit planning.

Every terminal participant outcome has the same core concerns: PsyNet records
why the session ended, recruiters choose a platform handoff, and payment is
planned before any external transfer occurs.  This module contains the value
objects shared by normal completion, unsuccessful completion, voluntary Leave,
and fatal-error recovery.  Timeline and error-page code remain responsible for
presenting those outcomes appropriately.
"""

import math
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from numbers import Real
from uuid import uuid4

from dallinger.config import get_config


@dataclass(frozen=True)
class PaymentDecision:
    """Describe intended participant payment before spend caps or transfer.

    Parameters
    ----------
    status
        Recruitment-platform outcome, such as ``approved`` or ``screened_out``.
    platform_base
        Amount supplied by the recruitment platform.
    bonus
        Additional amount PsyNet intends to transfer.
    """

    status: str
    platform_base: float
    bonus: float

    def __post_init__(self):
        """Validate that the decision can be safely recorded and transferred."""
        if self.status not in {"approved", "returned", "screened_out"}:
            raise ValueError(f"Unknown payment status {self.status!r}.")
        for name in ("platform_base", "bonus"):
            value = getattr(self, name)
            if (
                not isinstance(value, Real)
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(
                    f"{name} must be a finite, non-negative number (got {value!r})."
                )

    @classmethod
    def from_dict(cls, data: dict) -> "PaymentDecision":
        """Restore a payment decision from primitive participant data."""
        return cls(
            status=data["status"],
            platform_base=cls._stored_amount("platform_base", data["platform_base"]),
            bonus=cls._stored_amount("bonus", data["bonus"]),
        )

    @staticmethod
    def _stored_amount(name: str, value):
        """Reject stored amounts that only become numbers after coercion."""
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(
                f"{name} must be a finite, non-negative number (got {value!r})."
            )
        return float(value)


@dataclass(frozen=True)
class EarlyExitConfirmation:
    """Participant-facing copy for a voluntary Leave offer."""

    title: str
    message: str
    confirm_label: str
    cancel_label: str


class ExitContext(StrEnum):
    """Reason that a participant is leaving the experiment."""

    SUCCESSFUL = "successful"
    UNSUCCESSFUL = "unsuccessful"
    VOLUNTARY = "voluntary"
    ERROR_RECOVERY = "error_recovery"
    REJECTED_CONSENT = "rejected_consent"


class ExitPath(StrEnum):
    """Recruiter handoff selected for a participant exit."""

    END_SESSION = "end_session"
    SCREEN_OUT = "screen_out"
    RETURN_FOR_BONUS = "return_for_bonus"
    RETURN_WITHOUT_PAYMENT = "return_without_payment"
    TERMINATE_PANEL_SESSION = "terminate_panel_session"


class ExitPlanStatus(StrEnum):
    """Lifecycle state of a stored exit plan."""

    PREPARED = "prepared"
    COMMITTED = "committed"


class PaymentState(StrEnum):
    """Completeness of the payment information in an exit plan."""

    NOT_APPLICABLE = "not_applicable"
    PLANNED = "planned"
    DEFERRED = "deferred"


@dataclass(frozen=True)
class ErrorRecoveryPresentation:
    """Recruiter-specific copy and handoff for an error page.

    Whether tracked fatal recovery *shows* this page is recruiter policy
    (``shows_error_recovery_page``), not an inference from ``button_label``.
    ``action_instruction`` is an optional second paragraph before the button.
    """

    message: str
    action_instruction: str | None = None
    failure_message: str | None = None
    researcher_contact_message: str | None = None
    button_label: str | None = None
    preparation_post_url: str | None = None
    preparation_post_data: dict[str, str] = field(default_factory=dict)
    action_post_url: str | None = None
    action_post_data: dict[str, str] = field(default_factory=dict)
    destination_url: str | None = None
    auto_redirect_delay_ms: int | None = None

    def __post_init__(self):
        """Reject presentations whose declared handoff cannot be executed."""
        if self.preparation_post_data and not self.preparation_post_url:
            raise ValueError("Preparation POST data requires a URL.")
        if self.action_post_data and not self.action_post_url:
            raise ValueError("Action POST data requires a URL.")
        if (self.action_post_url or self.destination_url) and not self.button_label:
            raise ValueError("A participant handoff requires a button label.")
        if self.auto_redirect_delay_ms is not None:
            if self.auto_redirect_delay_ms <= 0:
                raise ValueError("An automatic redirect delay must be positive.")
            if not self.destination_url:
                raise ValueError("An automatic redirect requires a destination URL.")

    def without_handoff(self) -> "ErrorRecoveryPresentation":
        """Return a copy that explains the error without a participant action."""
        return replace(
            self,
            action_instruction=None,
            failure_message=None,
            button_label=None,
            preparation_post_url=None,
            preparation_post_data={},
            action_post_url=None,
            action_post_data={},
            destination_url=None,
            auto_redirect_delay_ms=None,
        )


@dataclass(frozen=True)
class ExitPlan:
    """Server-owned plan for one participant's terminal outcome.

    ``payment_state`` distinguishes recruiters that do not pay through PsyNet
    from error-recovery plans whose final amount must be calculated later.
    """

    plan_id: str
    context: ExitContext
    path: ExitPath
    status: ExitPlanStatus
    payment: PaymentDecision | None
    currency: str
    confirmation: EarlyExitConfirmation | None = None
    payment_state: PaymentState = PaymentState.PLANNED
    source_page_uuid: str | None = None

    def __post_init__(self):
        """Reject contradictory plan state before it reaches participant data."""
        if self.context is ExitContext.VOLUNTARY:
            if self.confirmation is None:
                raise ValueError("A voluntary exit plan requires confirmation.")
        elif self.confirmation is not None:
            raise ValueError("Confirmation is only valid for a voluntary exit plan.")

        if (
            self.source_page_uuid is not None
            and self.context is not ExitContext.VOLUNTARY
        ):
            raise ValueError("A source page is only valid for a voluntary exit plan.")

        if self.payment_state is PaymentState.PLANNED and self.payment is None:
            raise ValueError("A planned payment requires a payment decision.")
        if (
            self.payment_state is PaymentState.NOT_APPLICABLE
            and self.payment is not None
        ):
            raise ValueError("A non-applicable payment cannot have a payment decision.")
        if (
            self.payment_state is PaymentState.DEFERRED
            and self.context is not ExitContext.ERROR_RECOVERY
        ):
            raise ValueError("Only error recovery can defer its payment decision.")

        if self.path is ExitPath.SCREEN_OUT:
            self._require_payment_status("screened_out")
        elif self.path is ExitPath.RETURN_FOR_BONUS:
            self._require_payment_status("returned")
            if self.payment.platform_base != 0:
                raise ValueError("A returned submission cannot have platform base pay.")
        elif self.path is ExitPath.RETURN_WITHOUT_PAYMENT:
            self._require_payment_status("returned")
            if self.payment.platform_base != 0 or self.payment.bonus != 0:
                raise ValueError("A return without payment requires a zero payment.")
            if self.payment_state is not PaymentState.PLANNED:
                raise ValueError("A return without payment must be fully planned.")
        elif self.path is ExitPath.TERMINATE_PANEL_SESSION:
            if self.payment_state is not PaymentState.NOT_APPLICABLE:
                raise ValueError("Panel termination cannot include a PsyNet payment.")

    def _require_payment_status(self, status: str) -> None:
        """Require a payment decision with the status implied by the path."""
        if self.payment is None or self.payment.status != status:
            raise ValueError(
                f"The {self.path.value!r} path requires a {status!r} payment decision."
            )

    @classmethod
    def create(
        cls,
        *,
        context: ExitContext,
        path: ExitPath,
        payment: PaymentDecision | None,
        confirmation: EarlyExitConfirmation | None = None,
        payment_state: PaymentState | None = None,
        currency: str = "$",
        source_page_uuid: str | None = None,
    ) -> "ExitPlan":
        """Create a prepared exit plan."""
        if payment_state is None:
            payment_state = (
                PaymentState.PLANNED
                if payment is not None
                else PaymentState.NOT_APPLICABLE
            )
        return cls(
            plan_id=str(uuid4()),
            context=context,
            path=path,
            status=ExitPlanStatus.PREPARED,
            payment=payment,
            currency=currency,
            confirmation=confirmation,
            payment_state=payment_state,
            source_page_uuid=source_page_uuid,
        )

    def to_dict(self) -> dict:
        """Return primitive data suitable for participant storage."""
        data = asdict(self)
        data["context"] = self.context.value
        data["path"] = self.path.value
        data["status"] = self.status.value
        data["payment_state"] = self.payment_state.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ExitPlan":
        """Restore an exit plan from participant storage."""
        try:
            status = ExitPlanStatus(data["status"])
        except ValueError as exc:
            raise ValueError("Invalid exit plan status.") from exc
        confirmation = data.get("confirmation")
        payment = data.get("payment")
        return cls(
            plan_id=data["plan_id"],
            context=ExitContext(data["context"]),
            path=ExitPath(data["path"]),
            status=status,
            payment=(None if payment is None else PaymentDecision.from_dict(payment)),
            currency=data.get("currency", "$"),
            confirmation=(
                None if confirmation is None else EarlyExitConfirmation(**confirmation)
            ),
            payment_state=PaymentState(data["payment_state"]),
            source_page_uuid=data.get("source_page_uuid"),
        )

    def mark_committed(self) -> "ExitPlan":
        """Return a committed copy of this plan."""
        return replace(self, status=ExitPlanStatus.COMMITTED)

    def for_source_page(self, page_uuid: str) -> "ExitPlan":
        """Bind a prepared voluntary plan to the page that displays it."""
        return replace(self, source_page_uuid=page_uuid)


def _format_exit_amount(amount: float, currency: str | None = None) -> str:
    """Format a currency amount for participant-facing exit copy."""
    if currency is None:
        currency = get_config().get("currency", "$")
    return f"{currency}{float(amount):.2f}"


def _format_planned_payment_amount(plan: ExitPlan, name: str) -> str:
    """Format one amount from an exit plan's payment decision."""
    if plan.payment is None:
        raise ValueError("This exit plan has no payment decision.")
    return _format_exit_amount(getattr(plan.payment, name), plan.currency)


def _committed_exit_plan(participant) -> ExitPlan | None:
    """Return the participant's committed exit plan, if present."""
    plan = _stored_exit_plan(participant)
    if plan is None or plan.status is not ExitPlanStatus.COMMITTED:
        return None
    return plan


def _stored_exit_plan(participant) -> ExitPlan | None:
    """Return a valid stored exit plan in either lifecycle state."""
    data = getattr(participant, "exit_plan", None)
    if not isinstance(data, dict):
        return None
    try:
        plan = ExitPlan.from_dict(data)
    except (KeyError, TypeError, ValueError):
        return None
    return plan


def _exit_returns_without_payment(participant) -> bool:
    """Return whether the committed plan records an unpaid return."""
    plan = _committed_exit_plan(participant)
    return plan is not None and plan.path is ExitPath.RETURN_WITHOUT_PAYMENT
