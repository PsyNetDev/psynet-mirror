from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from psynet.data import SQLBase, SQLMixin, register_table


@register_table
class ErrorRecord(SQLBase, SQLMixin):
    __tablename__ = "error"

    # Remove default SQL columns
    failed = None
    failed_reason = None
    time_of_death = None

    token = Column(String)
    kind = Column(String)
    message = Column(String)
    traceback = Column(String)

    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)
    participant = relationship(
        "psynet.participant.Participant", back_populates="errors"
    )

    network_id = Column(Integer, ForeignKey("network.id"), index=True)
    network = relationship("TrialNetwork", back_populates="errors")

    node_id = Column(Integer, ForeignKey("node.id"), index=True)
    node = relationship("TrialNode", back_populates="errors")

    response_id = Column(Integer, ForeignKey("response.id"), index=True)
    response = relationship("psynet.timeline.Response", back_populates="errors")

    trial_id = Column(Integer, ForeignKey("trial.id"), index=True)
    trial = relationship("psynet.trial.main.Trial", back_populates="errors")

    asset_id = Column(Integer, ForeignKey("asset.id"), index=True)
    asset = relationship("Asset", back_populates="errors")

    process_id = Column(Integer, ForeignKey("process.id"), index=True)
    process = relationship("AsyncProcess", back_populates="errors")

    log_line_number = Column(Integer, nullable=True)

    def __init__(self, error, **kwargs):
        super().__init__(message=str(error), kind=type(error).__name__, **kwargs)

    @property
    def ids(self):
        """
        Returns a dictionary of IDs for the error record.

        This includes the IDs of the participant, network, node, response, trial, asset, and process.
        """
        return {k: v for k, v in self.__dict__.items() if "_id" in k}
