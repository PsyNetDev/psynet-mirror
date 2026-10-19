from psynet.modular_page import ModularPage, MonitorControl
from psynet.utils import get_translator


class MonitorInformation(ModularPage):
    """
    This ModularPage records information about the participant's computer screen configuration. The participant just
    needs to press 'Next', and respond positively to a permissions request, then the information will be recorded
    automatically.

    Parameters
    ----------
    label : str
        Page label; the answer is also saved as ``participant.var.<label>``.
    time_estimate : float
        Time estimate for the page, in seconds.
    """

    def __init__(
        self,
        label="monitor_information",
        time_estimate=5,
    ):
        super().__init__(
            label,
            prompt=self.get_prompt(),
            control=MonitorControl(),
            time_estimate=time_estimate,
            save_answer=label,
        )

    def get_prompt(self):
        _ = get_translator()
        return _(
            "When continuing to the next page you may see a permissions request; please grant it."
        )
