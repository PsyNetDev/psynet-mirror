import os
import tempfile

import dominate.tags as tags

from ..asset import ExperimentAsset
from ..field import claim_var
from ..utils import get_logger
from .imitation_chain import (
    ImitationChainNetwork,
    ImitationChainNode,
    ImitationChainTrial,
    ImitationChainTrialMaker,
)

logger = get_logger()


class Recording(ExperimentAsset):
    pass


class RecordingAnalysisPlot(ExperimentAsset):
    pass


class RecordTrial:
    analysis = claim_var("analysis")

    run_async_post_trial = True

    @property
    def recording(self):
        recordings = [
            asset for asset in self.assets.values() if isinstance(asset, Recording)
        ]
        if len(recordings) == 0:
            return None
        elif len(recordings) == 1:
            return recordings[0]
        else:
            raise ValueError(
                "This trial contains multiple recordings and we don't know which to use."
            )

    @property
    def recording_analysis_plot(self):
        plots = [
            asset
            for asset in self.assets.values()
            if isinstance(asset, RecordingAnalysisPlot)
        ]
        if len(plots) == 0:
            return None
        elif len(plots) == 1:
            return plots[0]
        else:
            raise ValueError(
                "This trial contains multiple recording analyses and we don't know which to use."
            )

    @property
    def visualization_html(self):
        html = super().visualization_html
        if self.recording_analysis_plot is not None:
            html += tags.div(
                tags.img(
                    src=self.recording_analysis_plot.url, style="max-width: 100%;"
                ),
                style="border-style: solid; border-width: 1px;",
            ).render()
        return html

    def sanitize_recording(self, path):
        pass

    def async_post_trial(self):
        # This code shouldn't be necessary because async_post_trial is only called
        # once the asset has been deposited.
        #
        # from ..utils import wait_until
        # def is_recording_deposited():
        #     db.session.commit()
        #     return self.recording.deposited
        #
        # wait_until(
        #     condition=is_recording_deposited,
        #     max_wait=45,
        #     poll_interval=1.0,
        #     error_message="Waited too long for the asset deposit to complete.",
        # )
        # logger.info("Asset deposit is complete, ready to continue with the analysis.")
        logger.info("Analyzing recording for trial %i...", self.id)
        with tempfile.NamedTemporaryFile() as temp_recording:
            with tempfile.NamedTemporaryFile(delete=False) as temp_plot:
                self.recording.export(temp_recording.name)
                self.sanitize_recording(temp_recording.name)
                self.analysis = self.analyze_recording(
                    temp_recording.name, temp_plot.name
                )
                if not (
                    "no_plot_generated" in self.analysis
                    and self.analysis["no_plot_generated"]
                ):
                    self.upload_plot(temp_plot.name, async_=True)
                else:
                    os.remove(temp_plot.name)
                try:
                    if self.analysis["failed"]:
                        self.fail(reason="analysis")
                except KeyError:
                    raise KeyError(
                        "The recording analysis failed to contain a 'failed' attribute."
                    )

    def upload_plot(self, local_path, async_):
        asset = RecordingAnalysisPlot(
            local_key="recording_analysis_plot",
            input_path=local_path,
            extension=".png",
            parent=self.recording.trial,
        )
        asset.deposit(async_=async_, delete_input=True)

    def analyze_recording(self, audio_file: str, output_plot: str):
        """
        Analyzes the recording produced by the participant.

        Parameters
        ----------

        audio_file
            Path to the audio file to be analyzed.

        output_plot
            Path to the output plot to be created.

        Returns
        -------

        dict :
            A dictionary of analysis information to be saved in the trial's ``analysis`` slot.
            This dictionary must include the boolean attribute ``failed``, determining
            whether the trial is to be failed.
            The following optional terms are also recognized by PsyNet:

            - ``no_plot_generated``: Set this to ``True`` if the function did not generate any output plot,
              and this will tell PsyNet not to try uploading the output plot to S3.
              The default value (i.e. the assumed value if no value is provided) is ``False``.
        """
        raise NotImplementedError


class MediaImitationChainNetwork(ImitationChainNetwork):
    """
    A Network class for media imitation chains.
    """

    pass


class MediaImitationChainTrial(RecordTrial, ImitationChainTrial):
    """
    A Trial class for media imitation chains.
    The user must override
    :meth:`~psynet.trial.record.RecordTrial.analyze_recording`.
    """


class MediaImitationChainNode(ImitationChainNode):
    """
    A Node class for media imitation chains.
    Users must override the
    :meth:`~psynet.trial.record.MediaImitationChainNode.synthesize_target` method.
    """

    media_extension = None

    def synthesize_target(self, output_file):
        """
        Generates the target stimulus (i.e. the stimulus to be imitated by the participant).
        """
        raise NotImplementedError

    def async_on_deploy(self):
        logger.info("Synthesizing media for node %i...", self.id)

        with tempfile.NamedTemporaryFile() as temp_file:
            from ..asset import ExperimentAsset

            self.synthesize_target(temp_file.name)
            asset = ExperimentAsset(
                local_key="stimulus",
                input_path=temp_file.name,
                extension=self.media_extension,
                parent=self,
            )
            asset.deposit()


class MediaImitationChainTrialMaker(ImitationChainTrialMaker):
    """
    A TrialMaker class for media imitation chains;
    see the documentation for
    :class:`~psynet.trial.chain.ChainTrialMaker`
    for usage instructions.
    """

    @property
    def default_network_class(self):
        return MediaImitationChainNetwork
