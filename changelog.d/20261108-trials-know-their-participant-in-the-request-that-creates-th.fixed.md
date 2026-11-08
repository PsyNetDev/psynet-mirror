Fixed `trial.participant` being `None` in the request that created the trial, so a trial with no pages, which ends in that request, crashed when it scored the answer or paid its performance reward.
