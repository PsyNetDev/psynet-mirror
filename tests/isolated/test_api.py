from psynet.api import EXPOSED_FUNCTIONS, expose_to_api


def test_exposed_static_method_stays_static():
    class Page:
        @expose_to_api("test_double")
        @staticmethod
        def double(x):
            return 2 * x

    try:
        assert Page().double(3) == 6
        assert EXPOSED_FUNCTIONS["test_double"](x=3) == 6
    finally:
        EXPOSED_FUNCTIONS.pop("test_double", None)
