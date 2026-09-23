.. _demos_introduction:

============
Introduction
============

The best way to start exploring PsyNet is by playing with some demos.
This gives you a quick feel for how to implement various experiment features
in PsyNet. When it comes to implementing your own experiment, you can then take
one of the PsyNet demos as a starting point and modify it to your own ends.

The `PsyNet repository <https://gitlab.com/PsyNetDev/PsyNet>`_ contains a large number
of demos in its `demos directory <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos>`_.
These demos are not particularly polished (yet), but they cover a range of PsyNet features,
and they are used by PsyNet's automated tests to make sure that new releases don't break
pre-existing features.

This section of the documentation highlights a few demos that we think are particularly
useful for understanding PsyNet. You are encouraged to look through the source code of these demos
and relate it to what you read here. If you're particularly interested in certain functionality,
you can download the demo and run it yourself. If you want to use a demo as a basis for your
own experiment, the best thing is to copy that demo into a separate directory (outside the PsyNet
repository) and make your changes there.

.. note::
    This section is still work-in-progress and we will be adding more demo overviews over time.
    In the meantime, feel free also to explore the
    `demos directory <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos>`_
    directly yourself.


If you see a particular PsyNet function or class that you want to learn more about,
there are a couple of ways to do this. One good way is to search the object's name in this website's
search box. Most objects should have a documentation entry that tells you more about the object's
API, for example the arguments that a function accepts and the kind of values that it returns.
The same documentation entry will also normally contain a link to the relevant source code.

An alternative way to learn more about PsyNet functions or classes is via your IDE.
Open the demo directory in your IDE
(assuming you've already downloaded PsyNet from its
`GitLab repository <https://gitlab.com/PsyNetDev/PsyNet>`_),
and then look around for an object you want to learn more about
(e.g. ``InfoPage``).
Ctrl-Click (Windows, Linux) or Cmd-Click (macOS) that object, and you should be taken to the
part of the PsyNet source code that defines the object. The source code should often
contain some useful documentation, which you can complement by examining the source code directly.
It's useful to be able to do this so that you can work effectively with undocumented or bleeding-edge
PsyNet features.
