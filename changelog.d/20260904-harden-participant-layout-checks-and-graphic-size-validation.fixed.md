Participant layout checks now detect ordinary response controls hidden behind
a custom fixed footer and preserve the exact inline height declaration, including
`!important`, while probing percentage-height behavior. Graphic dimensions,
`viewport_width`, and `max_viewport_height` now reject strings and invalid real
numbers before generating CSS. The experiment scaffold no longer promises a
visible reward when its generic recruiter hides rewards by default.
