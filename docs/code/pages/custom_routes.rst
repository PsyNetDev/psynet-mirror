Exchanging data with the server
===============================

Pages normally send information to the server by submitting an answer and
moving to the next page. To exchange data with the server at other times
without leaving the page, define a custom HTTP route in ``experiment.py`` and
call it from the page's JavaScript.

Defining a route
----------------

Decorate a class method of the experiment with ``experiment_route``. This
route from ``demos/experiments/timeline`` returns a string:

.. literalinclude:: ../../../demos/experiments/timeline/experiment.py
   :pyobject: Exp.custom_route
   :dedent: 4

``experiment_route`` is imported from ``dallinger.experiment``. In debug mode,
this route is available at ``http://localhost:5000/custom_route``. A route
can return a string, a tuple, or a dictionary.

Routes are class methods (or static methods), so they have no experiment
instance. To read or write experiment variables, get one with
:func:`~psynet.experiment.get_experiment`.

Reading input and checking the participant
------------------------------------------

Routes are publicly accessible, so check the participant's ``unique_id``
before returning or changing their data. This route from
``demos/features/websocket_chatroom`` reads URL parameters with Flask's
``request.args`` and returns a chat room's history only to a participant in
that room:

.. literalinclude:: ../../../demos/features/websocket_chatroom/experiment.py
   :pyobject: Exp.chatroom_history
   :dedent: 4

URL parameters are always strings; convert them where needed.
``success_response``, from ``dallinger.experiment_server.utils``, returns a
JSON response with ``"status": "success"`` and the given keyword arguments.

Calling a route from JavaScript
-------------------------------

The demo's page module calls the route with ``fetch``, passing the
participant's identity from ``psynet.uniqueId``:

.. literalinclude:: ../../../demos/features/websocket_chatroom/static/chatroom.js
   :language: javascript
   :start-at: async function fetchHistory() {
   :end-before: const wsScheme
   :dedent: 4

The abort controller lets the page's cleanup function cancel a request that
is still running when the participant leaves the page.

``dallinger.get()`` and ``dallinger.post()`` are shorter alternatives. They
take the parameters as an object and return a jQuery deferred:

.. code-block:: javascript

    dallinger.get("/chatroom_history", {
        room_id: roomId,
        participant_id: psynet.participantId,
        unique_id: psynet.uniqueId,
    }).done((resp) => {
        console.log(resp.messages);
    });

Saving data with POST routes
----------------------------

By convention, GET routes only retrieve information and do not change the
server's state. Routes that save information use ``methods=["POST"]`` and are
called with ``dallinger.post()``. They must call ``db.session.commit()`` after
changing database objects:

.. literalinclude:: ../../../demos/experiments/timeline/experiment.py
   :pyobject: Exp.set_dollars

.. code-block:: javascript

    dallinger.post("/set_dollars", {
        participant_id: psynet.participantId,
        unique_id: psynet.uniqueId,
        dollars: 1.5,
    });

Nested dictionaries and lists, and blobs such as raw media files, can also be
sent to the server. PsyNet's own response submission does this:
``submitGenericResponse`` in ``psynet/resources/scripts/psynet.js`` sends a
JSON field plus blobs as ``FormData``, and ``route_response`` in
``psynet/experiment.py`` reads them on the server.
