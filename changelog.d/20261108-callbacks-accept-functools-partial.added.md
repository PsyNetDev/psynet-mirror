Added support for `functools.partial` in saved callbacks such as `GroupBarrier(on_release=...)`, so one callback can serve several barriers with its own keyword arguments. PsyNet refuses arguments that would be lost: positional ones, names the function doesn't take, and names PsyNet passes itself, such as `group`:

```python
def score_question(group, question):
    ...

GroupBarrier(id_="question_1", group_type="team", on_release=partial(score_question, question=1))
```
