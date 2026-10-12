"""
Internal utilities for consents_cococo modules.
"""
from markupsafe import Markup
from psynet.consent import Consent
from psynet.modular_page import ModularPage


class ConsentPageWrapper(ModularPage, Consent):
    """Minimal mix-in used by all consent modules to mark a ModularPage as a Consent."""
    pass


def _resolve_duration_payment(DURATION, PAYMENT):
    """
    Return (DURATION, PAYMENT), reading from config.txt if not explicitly provided.

    Reads config.txt directly with configparser to avoid a circular import:
    Dallinger's get_config() triggers experiment loading, which would call this
    function again before config is fully initialised.

    Config keys read:
      DURATION <- prolific_estimated_completion_minutes
      PAYMENT  <- base_payment
    """
    if DURATION is not None and PAYMENT is not None:
        return int(DURATION), float(PAYMENT)

    try:
        import configparser, os
        parser = configparser.ConfigParser()
        # config.txt lives in the experiment directory (cwd during psynet debug/deploy)
        parser.read(os.path.join(os.getcwd(), "config.txt"))
        # Keys may appear in any section ([Config], [Prolific], etc.)
        # configparser's DEFAULT section merges all keys when accessed via parser.defaults(),
        # but iterating sections is safer for ini files with multiple named sections.
        all_keys = {}
        for section in parser.sections():
            all_keys.update(parser[section])

        if DURATION is None:
            raw = all_keys.get("prolific_estimated_completion_minutes")
            if raw is not None:
                DURATION = int(raw)

        if PAYMENT is None:
            raw = all_keys.get("base_payment")
            if raw is not None:
                PAYMENT = float(raw)

    except Exception:
        pass

    if DURATION is None or PAYMENT is None:
        raise ValueError(
            "Could not determine DURATION or PAYMENT. "
            "Either set prolific_estimated_completion_minutes and base_payment in config.txt, "
            "or pass them explicitly, e.g. consent_irb_nj6(DURATION=20, PAYMENT=3.33)."
        )

    return DURATION, PAYMENT
