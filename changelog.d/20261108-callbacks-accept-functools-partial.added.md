Added support for `functools.partial` in saved callbacks such as `GroupBarrier(on_release=...)`, so one callback can serve several barriers with its own keyword arguments:

```python
def score_question(group, question):
    ...

GroupBarrier(id_="question_1", group_type="team", on_release=partial(score_question, question=1))
```
