"""Export history: one row per export that a deployment builds from its database.

Experimenters export repeatedly while a study runs, and later need to see when
each export was made and how much data it held, for example to check that the
final export came after the last participant finished. The dashboard's Export
tab lists these rows. Because ``export_record`` is an ordinary table, every
export also contains the history of the exports made before it.

Design constraints
------------------
* :func:`psynet.export.service.build_export_tree` writes the rows, so the
  dashboard download, ``psynet export`` (remote or local) and the trigger link
  are all recorded in one place. Callers say where the export was requested.
* Scheduled backups pass no source and are not recorded: with automatic
  backups they run every minute and would bury the exports people asked for.
* Participant counts come from the export's own database snapshot, so they
  match the exported ``participant.csv`` even while participants keep arriving.
* A row is written only after the snapshot, so an export never contains its
  own row, and a failed export leaves no row.
"""

from dallinger import db
from sqlalchemy import Column, Integer, String
from sqlalchemy.exc import SQLAlchemyError

from psynet.data import SQLBase, SQLMixin, register_table
from psynet.db import transaction
from psynet.utils import get_logger

logger = get_logger()

#: Where an export can be requested from.
EXPORT_SOURCES = ("dashboard", "command_line", "trigger")


@register_table
class ExportRecord(SQLBase, SQLMixin):
    """One export built from the database; ``creation_time`` is when it was built."""

    __tablename__ = "export_record"

    failed = None
    failed_reason = None
    time_of_death = None
    vars = None

    #: One of :data:`EXPORT_SOURCES`.
    source = Column(String)
    #: The asset selection, ``none`` or ``collected``.
    assets = Column(String)
    n_participants = Column(Integer)
    n_completed_participants = Column(Integer)


def record_export(*, source: str, assets: str, participant_counts: dict) -> None:
    """Add a completed export to the export history.

    Database errors are logged rather than raised, so that the export still
    succeeds on a database without the ``export_record`` table, such as a local
    database created by an earlier PsyNet version.
    """
    if source not in EXPORT_SOURCES:
        raise ValueError(
            f"Export source must be one of {', '.join(EXPORT_SOURCES)}; got {source!r}."
        )
    try:
        with transaction():
            db.session.add(
                ExportRecord(source=source, assets=assets, **participant_counts)
            )
    except SQLAlchemyError:
        db.session.rollback()
        logger.warning(
            "Could not record this export in the export history.", exc_info=True
        )
