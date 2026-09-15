# README

Custom tables can carry polymorphic domain logic, not just rows. Here a `Pet`
base class and `Dog`/`Cat` subclasses live in one SQLAlchemy table; choosing a
pet type creates the right subclass and runs type-specific purchase pages
defined as class methods. Prefer this pattern when timeline branches and
persisted fields naturally belong on your domain objects.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
