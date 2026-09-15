Create and Rate
===============

Create and Rate is an experimental template supported by PsyNet. It
allows matching any creation (microphone recording, GSP, text input)
with ratings in the same experiment. For example, it can be used to
validate stimuli during the experiment or it can be used in a chain, in
which creations are passed to the next iteration if they are rated
highest by the majority (selection) or obtain the highest average score
(rating).

To write your own Create and Rate experiment, you need to implement
three classes:

- The creator class,
- the rater class,
- and the trial maker

Let’s present an image of an animal to the creators and ask them to come
up with a description of that animal:

::

   from markupsafe import Markup
   from psynet.modular_page import ImagePrompt, ModularPage, TextControl, PushButtonControl
   from psynet.trial.create_and_rate import (
       CreateAndRateNode,
       CreateAndRateTrialMakerMixin,
       CreateTrialMixin,
       RateTrialMixin,
   )
   from psynet.trial.imitation_chain import ImitationChainTrial


   def animal_prompt(text, img_url):
       return ImagePrompt(
           url=img_url,
           text=Markup(text),
           width="300px",
           height="300px",
       )

   class CreateTrial(CreateTrialMixin, ImitationChainTrial):
       time_estimate = 5

       def show_trial(self, experiment, participant):
           return ModularPage(
               "create_trial",
               animal_prompt(text="Describe the animal", img_url=self.context["img_url"]),
               TextControl(),
               time_estimate=self.time_estimate,
           )

We can now specify a rater which will see the description and the image
of the animal and has to rate how well the description matches the
image:

::

   class SingleRateTrial(RateTrialMixin, ImitationChainTrial):
       time_estimate = 5

       def show_trial(self, experiment, participant):
           assert self.trial_maker.target_selection_method == "load_balanced"
           assert len(self.targets) == 1
           target = self.targets[0]
           creation = self.get_target_answer(target)
           return ModularPage(
               "rate_trial",
               animal_prompt(
                   text=f"How well does this description match the animal?<br><strong>{creation}</strong>",
                   img_url=self.context["img_url"],
               ),
               PushButtonControl(
                   choices=[1, 2, 3, 4, 5],
                   labels=["not at all", "a little", "somewhat", "very", "perfectly"],
                   arrange_vertically=False,
               ),
           )

The last thing we need to implement is the trial maker. You need to
decide how the ratings are made, whether the raters select or rate (here
they do the latter). If they rate, do they validate one stimulus or all
at once? Should they rate the creations at the current iteration or also
the creation which was passed on from the previous iteration?

The trial maker needs the following parameters:

- ``num_creators``, which sets the number of creators e.g. two creators,
- ``num_raters``, number of raters; if people only rate 1 stimulus, the number of raters needs to be an integer multiple of the number of rated stimuli, i.e. ``num_creators`` (and optionally the previous iteration),
- ``node_class``, the class of the Node; in most use-cases ``CreateAndRateNode`` is fine,
- ``creator_class=CreateTrial``, set this to your creator class
- ``rater_class=RateClass``, set this to your rater class

Optionally, you can set

- ``include_previous_iteration`` (default ``False``) which indicates if the previous iteration is rated. If this is the case you need to specify a seed in the ``start_nodes``, e.g.:

::

   start_nodes = [
       CreateAndRateNode(context={"img_url": "static/dog.jpg"}, seed=seed_definition)
   ]

-  ``rate_mode`` which can be set to ``"rate"`` if people can give
   integer ratings to the stimuli or ``"select"`` if raters are faced
   with all creations at once and have to pick one
-  ``target_selection_method``, can be set to ``"all"`` (required if
   ``rate_mode=="rate"``) indicating that raters rate all creations or
   set to ``"one"`` which randomly selects one target (internally it
   prioritizes creations that obtained least ratings)
- ``randomize_target_order`` (default ``True``) which indicates if the presentation order of the targets is randomized. In most cases this should be set to ``True``.
-  ``verbose`` can be set to ``True`` to print the Create and Rate
   decisions to the experiment log

The TrialMaker class just needs to inherit from `CreateAndRateTrialMakerMixin` and some TrialMaker class, e.g. `ImitationChainTrialMaker`:

::

   class CreateAndRateTrialMaker(CreateAndRateTrialMakerMixin, ImitationChainTrialMaker):
       pass

It is also possible to customize the behaviour. For example, say we want to separate raters and creators into two
different groups which is set in ``participant.var.is_rater``. Return that role
once and let the mixin use it for both chain eligibility and final trial-class
validation:

::

    class CreateAndRateTrialMaker(CreateAndRateTrialMakerMixin, ImitationChainTrialMaker):
        def get_participant_role(self, participant, experiment):
            if participant.var.is_rater:
                return self.RATER_ROLE
            return self.CREATOR_ROLE

Creators then only receive heads that still need creators. Raters receive
heads that are ready for raters, and they wait or exit on heads whose creator
slots are filled but not yet finalized. Heads that still need creators are
not rater-eligible.

Also, you can easily modify the number of trials for creators and raters, e.g.:

::

    MAX_CREATIONS_PER_PARTICIPANT = 2
    MAX_RATINGS_PER_PARTICIPANT = 1

    class CreateAndRateTrialMaker(CreateAndRateTrialMakerMixin, ImitationChainTrialMaker):
            @classmethod
            def has_enough_trials(cls, participant):
                if participant.var.is_rater:
                    n_ratings = len(
                        cls.rater_class.query.filter_by(participant=participant).all()
                    )
                    if n_ratings >= MAX_RATINGS_PER_PARTICIPANT:
                        return True
                else:
                    n_creations = len(
                        cls.creator_class.query.filter_by(participant=participant).all()
                    )
                    if n_creations >= MAX_CREATIONS_PER_PARTICIPANT:
                        return True
                return False

            def custom_chain_filter(self, chains, participant, experiment):
                if self.has_enough_trials(participant):
                    return []
                return chains

            def get_participant_role(self, participant, experiment):
                if participant.var.is_rater:
                    return self.RATER_ROLE
                return self.CREATOR_ROLE


See the GAP demo for the full example.

Let’s now put all pieces together:

::

   from markupsafe import Markup
   import psynet.experiment
   from psynet.consent import NoConsent
   from psynet.modular_page import ImagePrompt, ModularPage, PushButtonControl, TextControl
   from psynet.page import SuccessfulEndPage
   from psynet.timeline import Timeline
   from psynet.trial.create_and_rate import (
       CreateAndRateNode,
       CreateAndRateTrialMakerMixin,
       CreateTrialMixin,
       RateTrialMixin,
   )
   from psynet.trial.imitation_chain import ImitationChainTrial, ImitationChainTrialMaker

    MAX_CREATIONS_PER_PARTICIPANT = 2
    MAX_RATINGS_PER_PARTICIPANT = 1
    EXPECTED_TRIALS_PER_PARTICIPANT = max(MAX_CREATIONS_PER_PARTICIPANT, MAX_RATINGS_PER_PARTICIPANT)


   def animal_prompt(text, img_url):
       return ImagePrompt(
           url=img_url,
           text=Markup(text),
           width="300px",
           height="300px",
       )


   class CreateTrial(CreateTrialMixin, ImitationChainTrial):
       time_estimate = 5

       def show_trial(self, experiment, participant):
           return ModularPage(
               "create_trial",
               animal_prompt(text="Describe the animal", img_url=self.context["img_url"]),
               TextControl(),
               time_estimate=self.time_estimate,
           )


   class SingleRateTrial(RateTrialMixin, ImitationChainTrial):
       time_estimate = 5

       def show_trial(self, experiment, participant):
           assert len(self.targets) == 1
           target = self.targets[0]
           creation = self.get_target_answer(target)
           return ModularPage(
               "rate_trial",
               animal_prompt(
                   text=f"How well does this description match the animal?<br><strong>{creation}</strong>",
                   img_url=self.context["img_url"],
               ),
               PushButtonControl(
                   choices=[1, 2, 3, 4, 5],
                   labels=["not at all", "a little", "somewhat", "very", "perfectly"],
                   arrange_vertically=False,
               ),
           )


    class CreateAndRateTrialMaker(CreateAndRateTrialMakerMixin, ImitationChainTrialMaker):
        pass


   start_nodes = [
       CreateAndRateNode(context={"img_url": "static/dog.jpg"})
   ]


   class Exp(psynet.experiment.Experiment):
       label = "Basic Create and Rate Experiment"

       timeline = Timeline(
           NoConsent(),
           CreateAndRateTrialMaker(
               num_creators=2,
               num_raters=2,
               node_class=CreateAndRateNode,
               creator_class=CreateTrial,
               rater_class=SingleRateTrial,
               include_previous_iteration=False,
               rate_mode="rate",
               target_selection_method="one",
               verbose=True,
               # trial_maker params
               id_="create_and_rate_trial_maker",
               chain_type="across",
               expected_trials_per_participant=EXPECTED_TRIALS_PER_PARTICIPANT,
               max_trials_per_participant=EXPECTED_TRIALS_PER_PARTICIPANT,
               start_nodes=start_nodes,
               chains_per_experiment=len(start_nodes),
               balance_across_chains=False,
               check_performance_at_end=True,
               check_performance_every_trial=False,
               propagate_failure=False,
               recruit_mode="n_trials",
               target_n_participants=None,
               wait_for_networks=False,
               max_nodes_per_chain=10,
           ),
           SuccessfulEndPage(),
       )

This gives you a simple Create and Rate experiment in just 104 lines 😉
