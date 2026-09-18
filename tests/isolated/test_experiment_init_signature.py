"""
Test that ExperimentMeta correctly validates __init__ method signatures.
"""

import pytest

from psynet.experiment import Experiment


def test_correct_init_signature():
    """Test that correct __init__ signatures work fine."""

    class CorrectExperiment(Experiment):
        def __init__(self, **kwargs):
            self.my_variable = "hello"
            super().__init__(**kwargs)

    # This should work without errors
    assert CorrectExperiment is not None


def test_incorrect_init_signature():
    """Test that incorrect __init__ signature raises an error."""

    with pytest.raises(RuntimeError) as exc_info:

        class IncorrectExperiment(Experiment):
            def __init__(self, session):  # This should trigger the error
                super().__init__(session)

    error_message = str(exc_info.value)
    assert "Your experiment class uses an outdated __init__ signature" in error_message


def test_no_init_method():
    """Test that classes without __init__ work fine."""

    class NoInitExperiment(Experiment):
        pass

    assert NoInitExperiment is not None


def test_init_with_additional_params():
    """Test that __init__ with additional parameters works."""

    class ExtraParamsExperiment(Experiment):
        def __init__(self, custom_param=None, **kwargs):
            super().__init__(**kwargs)
            self.custom_param = custom_param

    assert ExtraParamsExperiment is not None


def test_overriding_fail_participant_raises():
    with pytest.raises(RuntimeError, match="fail_participant"):

        class OverrideFailParticipant(Experiment):
            def fail_participant(self, participant):
                participant.fail()


def test_inheriting_fail_participant_is_allowed():
    class InheritFailParticipant(Experiment):
        pass

    assert InheritFailParticipant.fail_participant is Experiment.fail_participant


def test_mixin_fail_participant_override_raises():
    class FailParticipantMixin:
        def fail_participant(self, participant):
            participant.fail()

    with pytest.raises(RuntimeError, match="fail_participant"):

        class MixinOverride(FailParticipantMixin, Experiment):
            pass
