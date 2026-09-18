# README

This demo shows how to define custom database tables in a PsyNet experiment.
Custom SQLAlchemy models are useful when you need to persist experiment-specific
objects beyond the built-in participant/trial tables — for example inventory
items, messages, or other stateful records. Here we define a simple `coin` table
and add a new coin each time the participant chooses to collect one. Similar
logic could be used for any domain object you want to create, query, and display
over the course of a session.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
