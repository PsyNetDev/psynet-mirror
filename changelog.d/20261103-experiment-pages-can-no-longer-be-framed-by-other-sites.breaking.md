Experiment server responses now send `X-Frame-Options: SAMEORIGIN`, so other sites can no longer show the experiment in a frame. An experiment that must be framed by another site can remove the header in its own `after_request`. Dallinger calls this method on the experiment class, so define it as a class method:

```python
class Exp(psynet.experiment.Experiment):
    @classmethod
    def after_request(cls, request, response):
        response = super().after_request(request, response)
        response.headers.pop("X-Frame-Options", None)
        return response
```
