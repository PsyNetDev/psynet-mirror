Removed duplicated participant identifiers from ``ErrorRecord`` and ``Response``.
``Response`` no longer stores an IP address; Flask still updates
``Participant.client_ip_address`` on ``/timeline`` and ``/response``, and
custom page ``process_response`` methods continue to receive the client IP.
``LucidRID`` is linked to participants via nullable ``participant_id`` instead of
a foreign key on ``worker_id`` without committing the enclosing request
transaction. Export remaps recruiter identifier columns on copied tables (for
example ``notification.assignment_id``) to participant pseudonyms, and blanks
unmatched values plus ``request.params``.
``SQLMixin.scrub_pii`` is removed; shareable archives use identifier
separation rather than in-place JSON scrubbing.
