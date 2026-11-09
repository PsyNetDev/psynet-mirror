import random

from psynet.page import InfoPage
from psynet.timeline import CreditEstimate, PageMaker, switch, while_loop


def test_estimate_single_page():
    page = InfoPage("Hello", time_estimate=5)
    est = CreditEstimate([page])
    assert est.get_max("time") == 5


def test_estimate_two_pages():
    page_1 = InfoPage("Hello", time_estimate=5)
    page_2 = InfoPage("Goodbye", time_estimate=5)
    est = CreditEstimate([page_1, page_2])
    assert est.get_max("time") == 10


def test_estimate_page_maker():
    page = InfoPage("Hello", time_estimate=5)
    page_maker = PageMaker(lambda participant: page, time_estimate=5)
    est = CreditEstimate([page_maker])
    assert est.get_max("time") == 5


def test_switch():
    logic = switch(
        lambda: random.choice(["a", "b"]),
        branches={
            "a": InfoPage("Branch A", time_estimate=1.0),
            "b": InfoPage("Branch B", time_estimate=2.0),
        },
    )
    assert CreditEstimate(logic).get_max("time") == 2.0


def test_while_loop():
    loop = while_loop(
        condition=lambda: True,  # noqa
        logic=InfoPage("Please click 'Next'", time_estimate=1.0),
        expected_repetitions=3,
    )
    assert CreditEstimate(loop).get_max("time") == 3.0
