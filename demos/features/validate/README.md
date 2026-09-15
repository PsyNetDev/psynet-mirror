# README

Pages and controls can reject answers before the timeline advances. Validation
may live on the page (`validate=...`) or on a custom control's `validate`
method; failed answers show an error and keep the participant on the same page.
The bot path here deliberately submits invalid choices to exercise both hooks.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
