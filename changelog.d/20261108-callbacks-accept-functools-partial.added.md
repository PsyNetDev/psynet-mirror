Added support for `functools.partial` in saved callbacks such as `GroupBarrier(on_release=...)`, so one callback can serve several barriers with its own keyword arguments, which take precedence over the arguments PsyNet passes. PsyNet refuses arguments that would be lost, namely positional ones and names the function doesn't take. Saved class methods and trial maker methods now receive every argument the callback is given, such as `leader`:

```python
def score_question(group, question):
    ...

GroupBarrier(id_="question_1", group_type="team", on_release=partial(score_question, question=1))
```
