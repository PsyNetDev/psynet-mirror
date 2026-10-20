# This demo illustrates some advanced usage of custom SQLAlchemy classes in the context of a PsyNet experiment.
# We define a new table called 'pet', in which we store two types of animals: dogs and cats.
# We design an experiment whose timeline logic depends on the pet type that the user chooses,
# with different pages being defined as methods of the different pet classes.
# The resulting pets can be seen as rows in the database.
#
# Note: before working through this demo, you should be confident on object-oriented programming in Python,
# and understand the concept of class methods.

from dallinger import db
from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

import psynet.experiment
from psynet.data import SQLBase, SQLMixin, register_table
from psynet.modular_page import PushButtonControl, TextControl
from psynet.page import InfoPage, ModularPage
from psynet.participant import Participant
from psynet.timeline import CodeBlock, PageMaker, Timeline, join


@register_table
class Pet(SQLBase, SQLMixin):
    __tablename__ = "pet"

    base_price = None

    participant = relationship(Participant, backref="all_pets")
    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)

    price = Column(Float)
    name = Column(String)

    def __init__(self, participant):
        self.price = self.base_price
        self.participant = participant
        self.participant_id = participant.id

    @classmethod
    def choose_pet(cls):
        return join(
            ModularPage(
                "pet_kind",
                "What kind of pet would you like?",
                PushButtonControl(["Cat", "Dog"]),
                time_estimate=5,
                save_answer="temp__pet_kind",
            ),
            CodeBlock(cls.create_pet),
            PageMaker(
                cls._get_purchase_details,
                time_estimate=5,
            ),
            CodeBlock(cls._save_purchase_details),
        )

    @classmethod
    def create_pet(cls, participant):
        kind = participant.var.temp__pet_kind
        chosen_cls = {"Cat": Cat, "Dog": Dog}[kind]
        pet = chosen_cls(participant)
        db.session.add(pet)  # This queues the pet to be added to the database
        db.session.flush()  # Sends the pet to the database now, giving it an ID
        participant.var.temp__current_pet = pet.id

    @classmethod
    def get_current_pet(cls, participant):
        return cls.query.filter_by(id=participant.var.temp__current_pet).one()

    @classmethod
    def _get_purchase_details(cls, participant):
        return cls.get_current_pet(participant).get_purchase_details()

    @classmethod
    def get_purchase_details(cls):
        return [cls.ask_name()]

    @classmethod
    def ask_name(cls):
        return ModularPage(
            "pet_name",
            "What name would you like to give your new pet?",
            TextControl(),
            time_estimate=2.5,
            save_answer="temp__name",
        )

    @classmethod
    def _save_purchase_details(cls, participant):
        cls.get_current_pet(participant).save_purchase_details(participant)

    def save_purchase_details(self, participant):
        self.name = participant.var.temp__name


class Dog(Pet):
    base_price = 500
    comes_with_kennel = Column(Boolean)

    @classmethod
    def get_purchase_details(cls):
        return super().get_purchase_details() + [cls.ask_comes_with_kennel()]

    @classmethod
    def ask_comes_with_kennel(cls):
        return ModularPage(
            "pet_kennel",
            "Do you want to purchase a kennel as well?",
            PushButtonControl(choices=["Yes", "No"]),
            time_estimate=2.5,
            save_answer="temp__comes_with_kennel",
        )

    def save_purchase_details(self, participant):
        super().save_purchase_details(participant)

        comes_with_kennel = participant.var.temp__comes_with_kennel
        assert comes_with_kennel in ["Yes", "No"]
        self.comes_with_kennel = comes_with_kennel == "Yes"


class Cat(Pet):
    base_price = 400
    hunts_mice = Column(Boolean)

    @classmethod
    def get_purchase_details(cls):
        return super().get_purchase_details() + [cls.ask_hunts_mice()]

    @classmethod
    def ask_hunts_mice(cls):
        return ModularPage(
            "pet_hunts_mice",
            "Do you want a cat that hunts mice?",
            PushButtonControl(choices=["Yes", "No"]),
            time_estimate=2.5,
            save_answer="temp__hunts_mice",
        )

    def save_purchase_details(self, participant):
        super().save_purchase_details(participant)

        hunts_mice = participant.var.temp__hunts_mice
        assert hunts_mice in ["Yes", "No"]
        self.hunts_mice = hunts_mice == "Yes"


class Exp(psynet.experiment.Experiment):
    label = "Custom table (complex) demo"

    timeline = Timeline(
        Pet.choose_pet(),
        InfoPage(
            "Have a look at the dashboard to see the pet that you chose.",
            time_estimate=5,
        ),
    )
