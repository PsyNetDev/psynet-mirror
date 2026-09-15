========
Graphics
========

PsyNet contains sophisticated functionality for constructing and displaying
animated graphics to the participant. These graphics can be used to generate
engaging instruction pages, but they can also be used to construct highly visual
experiment trials.

Under the hood, PsyNet uses the Javascript library
`Raphaël <https://dmitrybaranovskiy.github.io/raphael/>`_
for displaying graphics.
You typically won't have to learn much about this library.
However, PsyNet does expose certain aspects of this library to the user,
for example when adding customized object attributes. In these cases,
we refer you to the `Raphaël documentation <https://dmitrybaranovskiy.github.io/raphael/reference.html>`_
for details about the available options.

Quick introduction
------------------

There are several ways of introducing a graphic into a PsyNet timeline.
Here we will focus on the simplest of these, the :class:`~psynet.graphics.GraphicPage`.
However, what you learn here will generalize naturally to the modular page
versions of the :class:`~psynet.graphics.GraphicPage`, namely the
:class:`~psynet.graphics.GraphicPrompt` and the
:class:`~psynet.graphics.GraphicControl`.

A :class:`~psynet.graphics.GraphicPage` presents a single graphic canvas to
the participant, which the participant can either watch passively or respond
to by clicking on the canvas.
Each graphic is defined by a collection of :class:`~psynet.graphics.Frame` objects.
These frames are shown in sequence to the participant.
Each frame contains a number of :class:`~psynet.graphics.GraphicObject` instances
which are drawn simultaneously and shown to the participant.

For example, we might write something like this:

::

    from psynet.graphics import (
        GraphicPage,
        Frame,
        Text
    )

    page = GraphicPage(
        "my_graphic_page",
        time_estimate=3,
        dimensions=[100, 100],
        auto_advance_after=3,
        frames=[
            Frame([
                Text("number", "3", x=50, y=50)
            ], duration=1),
            Frame([
                Text("number", "2", x=50, y=50)
            ], duration=1),
            Frame([
                Text("number", "1", x=50, y=50)
            ], duration=1)
        ]
    )

Here we have three frames. Each frame contains a text object, drawing a number.
These numbers are drawn in the centre of the canvas (the ``x`` and ``y`` locations
are expressed relative to the ``dimensions`` argument).
Each frame lasts 1 second, then once the final frame finishes, the page
automatically advances to the next page.

Alternatively, we might design a page such that the participant responds by clicking.
Here is an example:

::

    from psynet.graphics import (
        GraphicPage,
        Frame,
        Text
    )

    page = GraphicPage(
        "my_graphic_page",
        time_estimate=3,
        dimensions=[200, 200],
        frames=[
            Frame([
                Text("question", "Choose a number", x=100, y=100)
            ], duration=1),
            Frame([
                Text("n1", "1", x=50, y=100, click_to_answer=True),
                Text("n2", "2", x=100, y=100, click_to_answer=True),
                Text("n3", "3", x=150, y=100, click_to_answer=True)
            ])
        ]
    )

If ``click_to_answer=True``, this means that the participant can respond
by clicking on the object. In this case the page returns a dict containing
two variables: ``clicked_object``, corresponding to the object ID of the
clicked object, and ``click_coordinates``, corresponding to the exact location
of the mouse click.

Often we want to customize the objects that we display to the user.
A large amount of customization can be achieved by passing attributes
to the objects. For example, the following code adds colors to the text
displayed to the participant:

::

    from psynet.graphics import (
        GraphicPage,
        Frame,
        Text
    )

    page = GraphicPage(
        "my_graphic_page",
        time_estimate=3,
        dimensions=[100, 100],
        auto_advance_after=3,
        frames=[
            Frame([
                Text("number", "3", x=50, y=50, attributes={"fill": "blue"})
            ], duration=1),
            Frame([
                Text("number", "2", x=50, y=50, attributes={"fill": "green"})
            ], duration=1),
            Frame([
                Text("number", "1", x=50, y=50, attributes={"fill": "red"})
            ], duration=1)
        ]
    )

See https://dmitrybaranovskiy.github.io/raphael/reference.html#Element.attr
and https://www.w3.org/TR/SVG/ for details about valid attributes.

PsyNet also makes it easy to add animations to these objects.
An animation works by setting the object's initial attributes,
then setting the object's final attributes, then setting the duration
of the transition between the two. Complex animations can be constructed
by chaining multiple simple animations.
See below for an example:

::

    from psynet.graphics import (
        GraphicPage,
        Frame,
        Text,
        Image,
        Animation
    )

    page = GraphicPage(
        label="animation",
        dimensions=[100, 100],
        viewport_width=0.5,
        time_estimate=5,
        auto_advance_after=5,
        frames=[
            Frame(
                [
                    Image("logo", media_id="logo", x=45, y=25, width=75, loop_animations=True,
                          animations=[
                              Animation({"x": 55, "y": 75}, duration=1),
                              Animation({"width": 100}, duration=1),
                              Animation({"x": 45, "y": 25, "width": 75}, duration=1),
                          ])
                ], duration=1
            ),
        ],
        media=MediaSpec(image=dict(logo="/static/images/logo.svg"))
    )

Note that here we also introduced the ``Image`` object. To use an image in a graphic,
you must introduce it as part of the page's ``media`` argument. That way the image
is loaded once before the graphic is drawn, and can be reused multiple times.
A similar approach is used to play audio as part of the graphic.

You should now have a good high-level perspective on PsyNet's graphics functionality.
To gain more of an insight into how to use these features, we recommend
that you explore the ``graphic`` demo and its source code,
as well as looking through the resources below.

Further reading
---------------

- :doc:`Graphics exercises </learning/exercises/graphics>`
- :doc:`/api/graphics`
