Identifier separation now inspects column types before copying tables and
fails if a recruiter-identifier column cannot store a text or JSON
placeholder. Integer, UUID, enum, short ``VARCHAR``, and ``NOT NULL``
identifier columns on tables without ``id`` are rejected instead of
producing an archive that cannot be reloaded.
