"""Central definitions for participant and Lucid entrant identifier fields.

These fields identify a person to a recruiter or marketplace. The live
``Participant`` table (and ``LucidRID`` for Lucid ghost entrants) remain the
sole owners while an experiment runs. Export separates them into sidecar files
and writes pseudonyms into table CSVs under ``database/``.

``entry_information`` is included in the participant sidecar because it often
carries recruiter-specific signup metadata; it is blanked in the pseudonymous
database archive.
"""

PARTICIPANT_IDENTIFIER_FIELDS = (
    "participant_id",
    "worker_id",
    "assignment_id",
    "hit_id",
    "unique_id",
    "client_ip_address",
    "entry_information",
)

LUCID_ENTRANT_IDENTIFIER_FIELDS = (
    "lucid_rid_id",
    "rid",
    "lucid_panelist_id",
    "lucid_respondent_id",
)
