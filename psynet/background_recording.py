"""Optional page recordings, separate from the participant's answer.

Resolved pages enforce consent and control compatibility on the server. Assets
are reserved only after answer validation, linked to the original page and
parent, and never block trial processing or become an answer recording. Browser
capture is best effort; missing media remains an explicit asset outcome.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class VideoRecordConfig:
    """Configure optional background capture with bounded duration and file size.

    ``source`` is camera, screen, or both. Audio is disabled by default. Limits
    apply per source; capture stops when either limit is reached. This initial
    API supports ordinary timeline pages, not delegated or same-session pages.
    """

    source: str = "camera"
    audio: bool = False
    max_duration: int = 120
    max_bytes: int = 16 * 1024 * 1024

    def __post_init__(self):
        if self.source not in {"camera", "screen", "both"}:
            raise ValueError("Invalid background recording source.")
        if type(self.audio) is not bool:
            raise ValueError("audio must be a boolean.")
        if type(self.max_duration) is not int or not 1 <= self.max_duration <= 600:
            raise ValueError("max_duration must be between 1 and 600 seconds.")
        if type(self.max_bytes) is not int or not 1 <= self.max_bytes <= 128 * 1024**2:
            raise ValueError("max_bytes must be between 1 byte and 128 MiB.")

    @property
    def sources(self):
        """Return the independent capture sources requested by this page."""
        return ["camera", "screen"] if self.source == "both" else [self.source]


def _normalize_config(value, page, *, delegated=False, session_id=None):
    """Reject unsupported combinations before a page can acquire devices."""
    if value is None:
        return None
    from .modular_page import AudioRecordControl, VideoRecordControl

    config = VideoRecordConfig(source=value) if isinstance(value, str) else value
    if not isinstance(config, VideoRecordConfig):
        raise TypeError(
            "background_recording must be a source string or VideoRecordConfig."
        )
    if getattr(page, "is_consent", False):
        raise ValueError("Consent pages cannot have background recording.")
    if isinstance(
        getattr(page, "control", None), (AudioRecordControl, VideoRecordControl)
    ):
        raise ValueError("Background recording cannot accompany an answer recorder.")
    if delegated or session_id is not None:
        raise ValueError(
            "Background recording does not yet support delegated, full-reload, or same-session pages."
        )
    return config


def _browser_config(page, experiment, participant):
    """Require stored AV consent when the experiment uses a stock AV module."""
    from .bot import Bot
    from .consent import AudiovisualConsent, LabRecruiterAudiovisualConsent

    config = page.background_recording
    if config is None or isinstance(participant, Bot):
        return None
    for module, key in (
        (AudiovisualConsent, "audiovisual_consent"),
        (LabRecruiterAudiovisualConsent, "lab-recruiter_audiovisual_consent"),
    ):
        if any(isinstance(elt, module) for elt in experiment.timeline.module_list):
            if participant.var.get(key, False) is not True:
                raise ValueError(
                    "Background recording requires stored audiovisual consent."
                )
    return {**asdict(config), "sources": config.sources}


def _accept_background_recordings(page, response, participant, experiment, page_uuid):
    """Reserve optional clips without replacing or changing the ordinary answer."""
    from .media_upload import _reserve_recording, _upload_timeout
    from .trial.record import Recording

    config = _browser_config(page, experiment, participant)
    if config is None:
        return []
    reported = response.metadata.get("background_recording") or {}
    if not isinstance(reported, dict):
        raise ValueError("Invalid background recording metadata.")
    sizes = reported.get("sizes", {})
    unavailable = reported.get("unavailable", {})
    if not isinstance(sizes, dict) or not isinstance(unavailable, dict):
        raise ValueError("Invalid background recording metadata.")
    allowed = {
        "permission_denied",
        "skipped",
        "source_ended",
        "unsupported",
        "capture_error",
        "missing_recording",
        "size_limit",
        "queue_full",
        "transport_unavailable",
    }
    hints = {}
    for source in config["sources"]:
        size = sizes.get(source, 0)
        if type(size) is not int or not 0 <= size <= 2**53 - 1:
            raise ValueError("Invalid background recording size.")
        hints[source] = size
    timeout = _upload_timeout(max(1, sum(hints.values())))
    receipts = []
    for source, size in hints.items():
        reason = unavailable.get(source)
        if reason is not None and (
            not isinstance(reason, str) or reason not in allowed
        ):
            raise ValueError("Invalid background recording outcome.")
        if size > config["max_bytes"]:
            reason = "size_limit"
        elif size == 0:
            reason = reason or "missing_recording"
        asset, receipt = _reserve_recording(
            response=response,
            parent=response._background_parent,
            page_uuid=page_uuid,
            source=source,
            local_key=f"background_{page_uuid}_{source}",
            storage=Recording.default_storage,
            upload_timeout=timeout,
            upload_size_bytes=min(size, config["max_bytes"]) or None,
            max_bytes=config["max_bytes"],
            role="background",
            required_for_trial=False,
        )
        asset.upload_context = {
            **asset.upload_context,
            "page_label": page.label,
            "captured_size_bytes": size,
            "unavailable_reason": reason,
        }
        if reason:
            asset.upload_token_hash = None
        else:
            receipts.append({**receipt, "source": source})
    return receipts
