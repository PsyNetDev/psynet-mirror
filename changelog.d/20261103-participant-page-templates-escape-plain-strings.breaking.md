Participant pages now escape HTML in plain strings, as Flask's own templates do. A plain `str` is shown as text wherever a template writes it with `{{ ... }}`: control labels (for example `labels` and `choices` of `PushButtonControl`, `KeyboardPushButtonControl`, `CheckboxControl` and `RadioButtonControl`), `Button` text, `KeyboardPage` prompts, `WaitPage` content, and values passed through `template_arg` or read by custom prompt and control macros. Prompt, `InfoPage`, `wait_while` and `render_exit_message` text already worked this way. To keep HTML that you wrote yourself, wrap it in `markupsafe.Markup` or build it with `dominate` tags; `render_exit_message` now accepts `Markup` too. Never wrap participant-provided text in `Markup`: write `Markup("<b>{}</b>").format(answer)`, which escapes `answer`, instead of `Markup(f"<b>{answer}</b>")`. Strings in `Experiment.css` and page `css` are still written as CSS, instructions given to `AttentionTest` and `AudioForcedChoiceTest` are still shown as HTML, and messages translated in templates with `gettext` or `pgettext` may still contain HTML. Inside `<script>`, write values with `{{ value | tojson }}`.

```python
# Before: the label was written as raw HTML
PushButtonControl(choices=["cat"], labels=['<img src="/static/cat.png">'])

# After
from markupsafe import Markup

PushButtonControl(choices=["cat"], labels=[Markup('<img src="/static/cat.png">')])
```
