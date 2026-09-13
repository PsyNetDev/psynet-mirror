Fixed ``Column ... conflicts with existing column`` errors when an experiment
class adds a column to a table it shares with other classes, such as a ``Trial``
subclass on Dallinger's ``info`` table. PsyNet now reuses the existing column,
so plain ``Column`` declarations survive reimporting ``experiment.py`` from its
staging copy. When a different class redeclares the same column name, the two
declarations must agree on type, length, nullability, uniqueness, indexing,
primary key, foreign keys, defaults, update values, constraints, autoincrement
behavior, system-column status, and comments, or PsyNet raises a clear error
asking you to rename one of them. Callable defaults such as
``default=lambda: 0`` cannot be compared between two classes, so declare such a
shared column on a single class.
