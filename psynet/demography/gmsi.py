from typing import List, Optional

from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.timeline import CodeBlock, Module, Response, join


class GMSI(Module):
    """
    The `Goldsmiths Musical Sophistication Index` (GMSI) questionnaire.

    Parameters
    ----------

    label : str, default: "gmsi"
        A label used to distinguish the module from other modules in the timeline. In the case of multiple GMSI instances within a single timeline this label also allows to differentiate between the variable names used to store the participant's final scores; see :class:`~psynet.field.VarStore` for details.

    short_version : bool, optional, default: `False`
        Whether to use the reduced set of 29 questions.
        The citation for this short version is Lin, H. L., Frieler, K., & Müllensiefen, D. (2021).
        Development and Validation of Short Forms of the Goldsmiths Musical Sophistication Index in Three Languages.
        ICMPC/ESCOM 2021.
        See also https://shiny.gold-msi.org/gmsiconfigurator/ and https://www.youtube.com/watch?v=x_0DomCP8Rs.


    subscales: List, optional, default: `None`
        The subscales to be included in the questionnaire. Possible subscales are `Active Engagement`, `Emotions`, `General`, `Musical Training`, `Perceptual Abilities, `Singing Abilities`, `Absolute Pitch`, `Instrument`, and `Start Age`. If no subscales are provided all subscales are selected. Overrides the `short_version` parameter.

    info_page : InfoPage, optional, default: `None`
        An :class:`~psynet.page.InfoPage` object to be used as an introductionary first page.
        If none is supplied the default one is displayed (see source code).
    """

    def __init__(
        self,
        label: str = "gmsi",
        short_version: bool = False,
        subscales: Optional[List] = None,
        info_page: Optional[InfoPage] = None,
    ):
        self.label = label
        self.short_version = short_version
        self.subscales = subscales

        if info_page is None:
            info_page = InfoPage(
                "The following questions are designed to assess your musicality. Please answer as accurately as possible.",
                time_estimate=5,
            )

        questions = []
        if self.subscales is not None:
            questions = {
                label: question_data()[label]
                for label, data in question_data().items()
                if any(subscale in self.subscales for subscale in data["subscales"])
            }
        elif self.short_version:
            questions_labels = [
                f"q_{question_number:02d}"
                for question_number in [
                    1,
                    4,
                    19,
                    27,
                    30,
                    36,
                    3,
                    10,
                    20,
                    26,
                    39,
                    2,
                    12,
                    16,
                    22,
                    35,
                    6,
                    13,
                    14,
                    24,
                    28,
                    29,
                    32,
                    8,
                    11,
                    23,
                    33,
                    40,
                    41,
                ]
            ]
            questions = {
                label: question_data()[label]
                for label, data in question_data().items()
                if label in questions_labels
            }
        else:
            questions = question_data()

        self.elts = join(
            info_page,
            [
                GMSIPage(
                    label,
                    data["prompt"],
                    data["choices"],
                    labels=data.get("labels"),
                    arrange_vertically=data["arrange_vertically"],
                    module_label=self.label,
                )
                for label, data in questions.items()
            ],
            self.save_scores,
        )
        super().__init__(self.label, self.elts)

    @property
    def save_scores(self):
        return CodeBlock(
            lambda participant: participant.var.set(
                self.label, self.compile_results(participant)
            )
        )

    def compile_results(self, participant):
        # get all responses for the participant from the database
        responses = Response.query.filter_by(participant_id=participant.id)
        # filter to retain only gmsi responses for current module
        responses = [
            response
            for response in responses
            if response.question in question_data().keys()
            and response.metadata["gmsi_label"] == self.label
        ]
        # calculate score for each question
        response_scores = {
            response.question: self.calculate_score(response.question, response.answer)
            for response in responses
        }
        # group scores by subscale
        grouped_scores = {}
        for question, score in response_scores.items():
            subscales = question_data()[question]["subscales"]
            for subscale in subscales:
                if subscale in grouped_scores.keys():
                    grouped_scores[subscale].append(score)
                else:
                    grouped_scores[subscale] = [score]
        # calculate arithmetic mean for each subscale
        mean_scores_per_scale = {
            group[0]: (
                round(sum(group[1]) / len(group[1]), 6)
                if all(isinstance(item, int) for item in group[1])
                else group[1][0]
            )
            for group in grouped_scores.items()
        }

        if self.subscales:
            # remove subscales not asked for
            mean_scores_per_scale = {
                subscale: score
                for subscale, score in mean_scores_per_scale.items()
                if subscale in self.subscales
            }

        return {
            "response_scores": response_scores,
            "mean_scores_per_scale": mean_scores_per_scale,
        }

    @staticmethod
    def calculate_score(question, answer):
        if isinstance(answer, str):
            answer = answer.replace('"', "")
        if question == "q_40" and str(answer) == "19":
            return None
        if question in ["q_32", "q_41"]:
            return answer
        raw_value = int(answer)
        return (8 - raw_value) if question_data()[question]["inverted"] else raw_value


class GMSIPage(ModularPage):
    def __init__(
        self,
        label,
        prompt,
        choices,
        labels=None,
        arrange_vertically=False,
        module_label="gmsi",
    ):
        self.label = label
        self.prompt = prompt
        self.choices = choices
        self.labels = labels
        self.arrange_vertically = arrange_vertically
        self.time_estimate = 5
        self.module_label = module_label

        control = PushButtonControl(
            choices=self.choices,
            labels=self.labels,
            arrange_vertically=self.arrange_vertically,
        )
        super().__init__(
            self.label,
            self.prompt,
            control=control,
            time_estimate=self.time_estimate,
        )

    def metadata(self, **kwargs):
        return {"gmsi_label": self.module_label}


def agreement_scale():
    return {
        "choices": list(range(1, 8)),
        "labels": [
            "Completely disagree",
            "Strongly disagree",
            "Disagree",
            "Neither agree nor disagree",
            "Agree",
            "Strongly agree",
            "Completely agree",
        ],
    }


def question_data():
    return {
        "q_01": {
            "prompt": "I spend a lot of my free time doing music-related activities.",
            "inverted": False,
            "subscales": ["Active Engagement", "General"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_02": {
            "prompt": "I engaged in regular, daily practice of a musical instrument (including voice) for the following number of years:",
            "inverted": False,
            "subscales": ["Musical Training", "General"],
            "choices": agreement_scale()["choices"],
            "labels": ["0", "1", "2", "3", "4-5", "6-9", "10 or more"],
            "arrange_vertically": True,
        },
        "q_03": {
            "prompt": "I sometimes choose music that can trigger shivers down my spine.",
            "inverted": False,
            "subscales": ["Emotions"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_04": {
            "prompt": "I enjoy writing about music, for example on blogs and forums.",
            "inverted": False,
            "subscales": ["Active Engagement", "General"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_05": {
            "prompt": "If somebody starts singing a song I don't know, I can usually join in.",
            "inverted": False,
            "subscales": ["Singing Abilities", "General"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_06": {
            "prompt": "I am able to judge whether someone is a good singer or not.",
            "inverted": False,
            "subscales": ["Perceptual Abilities"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_07": {
            "prompt": "I usually know when I'm hearing a song for the first time.",
            "inverted": False,
            "subscales": ["Perceptual Abilities"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_08": {
            "prompt": "I can sing or play music from memory.",
            "inverted": False,
            "subscales": ["Singing Abilities", "General"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_09": {
            "prompt": "I'm intrigued by musical styles I'm not familiar with and want to find out more.",
            "inverted": False,
            "subscales": ["Active Engagement"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_10": {
            "prompt": "Pieces of music rarely evoke emotions for me.",
            "inverted": True,
            "subscales": ["Emotions"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_11": {
            "prompt": "I am able to hit the right notes when I sing along with a recording.",
            "inverted": False,
            "subscales": ["Singing Abilities", "General"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_12": {
            "prompt": "At the peak of my interest, I practised my primary instrument (including voice) for the following number of hours per day:",
            "inverted": False,
            "subscales": ["Musical Training", "General"],
            "choices": agreement_scale()["choices"],
            "labels": ["0", "0.5", "1", "1.5", "2", "3-4", "5 or more"],
            "arrange_vertically": True,
        },
        "q_13": {
            "prompt": "I find it difficult to spot mistakes in a performance of a song even if I know the tune.",
            "inverted": True,
            "subscales": ["Perceptual Abilities"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_14": {
            "prompt": "I can compare and discuss differences between two performances or versions of the same piece of music.",
            "inverted": False,
            "subscales": ["Perceptual Abilities", "General"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_15": {
            "prompt": "I have trouble recognizing a familiar song when played in a different way or by a different performer.",
            "inverted": True,
            "subscales": ["Perceptual Abilities"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_16": {
            "prompt": "I have never been complimented for my talents as a musical performer.",
            "inverted": True,
            "subscales": ["Musical Training", "General"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_17": {
            "prompt": "I have attended the following number of live music events as an audience member in the past twelve months:",
            "inverted": False,
            "subscales": ["Active Engagement"],
            "choices": agreement_scale()["choices"],
            "labels": ["0", "1", "2", "3", "4-6", "7-10", "11 or more"],
            "arrange_vertically": True,
        },
        "q_18": {
            "prompt": "I have had formal training in music theory for the following number of years",
            "inverted": False,
            "subscales": ["Musical Training"],
            "choices": agreement_scale()["choices"],
            "labels": ["0", "0.5", "1", "2", "3", "4-6", "7 or more"],
            "arrange_vertically": True,
        },
        "q_19": {
            "prompt": "I often read or search the internet for things related to music.",
            "inverted": False,
            "subscales": ["Active Engagement", "General"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_20": {
            "prompt": "I often pick certain music to motivate or excite me.",
            "inverted": False,
            "subscales": ["Emotions"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_21": {
            "prompt": "I have had formal training on a musical instrument (including voice) during my lifetime for the following number of years:",
            "inverted": False,
            "subscales": ["Musical Training"],
            "choices": agreement_scale()["choices"],
            "labels": ["0", "0.5", "1", "2", "3-5", "6-9", "10 or more"],
            "arrange_vertically": True,
        },
        "q_22": {
            "prompt": "I can play the following number of musical instruments (including voice):",
            "inverted": False,
            "subscales": ["Musical Training", "General"],
            "choices": agreement_scale()["choices"],
            "labels": ["0", "1", "2", "3", "4", "5", "6 or more"],
            "arrange_vertically": True,
        },
        "q_23": {
            "prompt": "I am able to sing in harmony when somebody is singing a familiar tune.",
            "inverted": False,
            "subscales": ["Singing Abilities", "General"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_24": {
            "prompt": "I can tell when people sing or play out of time with the beat.",
            "inverted": False,
            "subscales": ["Perceptual Abilities"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_25": {
            "prompt": "I am able to identify what is special about a given musical piece.",
            "inverted": False,
            "subscales": ["Emotions", "General"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_26": {
            "prompt": "I am able to talk about the emotions that a piece of music evokes for me.",
            "inverted": False,
            "subscales": ["Emotions"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_27": {
            "prompt": "I don't spend much of my disposable income on music.",
            "inverted": True,
            "subscales": ["Active Engagement"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_28": {
            "prompt": "I can tell when people sing or play out of tune.",
            "inverted": False,
            "subscales": ["Perceptual Abilities"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_29": {
            "prompt": "When I sing, I have no idea whether I'm in tune or not.",
            "inverted": True,
            "subscales": ["Perceptual Abilities", "General"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_30": {
            "prompt": "Music is kind of an addiction for me – I couldn't live without it.",
            "inverted": False,
            "subscales": ["Active Engagement", "General"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_31": {
            "prompt": "I listen attentively to music for the following amount of time per day:",
            "inverted": False,
            "subscales": ["Active Engagement"],
            "choices": agreement_scale()["choices"],
            "labels": [
                "0-15 min",
                "15-30 min",
                "30-60 min",
                "60-90 min",
                "2 hrs",
                "2-3 hrs",
                "4 hrs or more",
            ],
            "arrange_vertically": True,
        },
        "q_32": {
            "prompt": "The instrument I play best (including voice) is:",
            "inverted": False,
            "subscales": ["Instrument"],
            "choices": [
                "I don't play any instrument.",
                "voice",
                "piano",
                "guitar",
                "drums",
                "xylophone",
                "flute",
                "oboe",
                "clarinet",
                "bassoon",
                "trumpet",
                "trombone",
                "tuba",
                "saxophone",
                "horn",
                "violin",
                "cello",
                "viola",
                "double bass",
                "harp",
                "other",
            ],
            "arrange_vertically": False,
        },
        "q_33": {
            "prompt": "I don't like singing in public because I'm afraid that I would sing wrong notes.",
            "inverted": True,
            "subscales": ["Singing Abilities", "General"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_34": {
            "prompt": "When I hear a piece of music I can usually identify its genre.",
            "inverted": False,
            "subscales": ["Perceptual Abilities"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_35": {
            "prompt": "I would not consider myself a musician.",
            "inverted": True,
            "subscales": ["Musical Training", "General"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_36": {
            "prompt": "I keep track of new music that I come across (e.g. new artists or recordings).",
            "inverted": False,
            "subscales": ["Active Engagement"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_37": {
            "prompt": "After hearing a new song two or three times, I can usually sing it by myself.",
            "inverted": False,
            "subscales": ["Singing Abilities", "General"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_38": {
            "prompt": "I only need to hear a new tune once and I can sing it back hours later.",
            "inverted": False,
            "subscales": ["Singing Abilities"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_39": {
            "prompt": "Music can evoke my memories of past people and places.",
            "inverted": False,
            "subscales": ["Emotions"],
            "choices": agreement_scale()["choices"],
            "labels": agreement_scale()["labels"],
            "arrange_vertically": True,
        },
        "q_40": {
            "prompt": "What age did you start to play an instrument?",
            "inverted": False,
            "subscales": ["Start Age"],
            "choices": list(range(2, 20)),
            "labels": list(range(2, 19)) + ["I don't play any instrument."],
            "arrange_vertically": False,
        },
        "q_41": {
            "prompt": "Do you have absolute pitch? Absolute or perfect pitch is the ability to recognise and name an isolated musical tone without a reference tone, e.g. being able to say 'F#' if someone plays that note on the piano.",
            "inverted": False,
            "subscales": ["Absolute Pitch"],
            "choices": ["Yes", "No"],
            "arrange_vertically": False,
        },
    }
