====
Data
====

.. automodule:: psynet.data
    :members:
    :show-inheritance:

.. py:class:: SQLBase
    :module: psynet.data

    SQLAlchemy declarative base for experiment tables, re-exported from
    ``dallinger.db.Base``. Combine it with :class:`~psynet.data.SQLMixin` and
    :func:`~psynet.data.register_table` to define a custom table::

        @register_table
        class Coin(SQLBase, SQLMixin):
            __tablename__ = "coin"
