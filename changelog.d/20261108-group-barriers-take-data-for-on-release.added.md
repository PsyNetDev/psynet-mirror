Added `on_release_data` to `GroupBarrier`, a dictionary of JSON-compatible values that `on_release` reads as `barrier.on_release_data`, so one callback can serve several barriers:

```python
def score_question(group, barrier):
    question = barrier.on_release_data["question"]

GroupBarrier(id_="question_1", group_type="team", on_release=score_question, on_release_data={"question": 1})
```
