Unity integration
=================

:class:`~psynet.page.UnityPage` embeds a game built with
`Unity <https://unity.com/>`_ as a WebGL app in a PsyNet page. Unity suits
experiments that need a game-like 2D or 3D environment, physics, or
components from the Unity Asset Store. PsyNet sends parameters to the game,
and the game reports events such as collected objects back to PsyNet as page
answers.

The ``demos/experiments/unity_autoplay`` demo embeds a simple game. The
player (yellow cylinder) collects objects (red and blue cubes) to gain points:

.. figure:: ../../_static/images/experimenter/unity_integration/unity_3d_player.png
  :width: 600
  :align: center

  A Unity 3D scene with a player and collectable objects

.. figure:: ../../_static/images/experimenter/unity_integration/unity_3d_score.png
  :width: 600
  :align: center

  The score increases with each collected object

.. figure:: ../../_static/images/experimenter/unity_integration/unity_3d_game_over.png
  :width: 600
  :align: center

  The game ends when the score reaches the goal

How PsyNet and Unity communicate
--------------------------------

.. figure:: ../../_static/images/experimenter/unity_integration/unity_3d_workflow.png
  :width: 800
  :align: center

PsyNet puts the game parameters in the page's ``contents``. When the game
starts, Unity reads them. As the game proceeds, Unity submits answers to
PsyNet, for example each time the participant collects an object. PsyNet can
then send a new page with different parameters. Consecutive pages with the
same ``session_id`` update the running game instead of reloading it: PsyNet
updates ``psynet.page`` and triggers the ``pageUpdated`` event. The game
decides when it has finished and moves the timeline forward.

The PsyNet side
---------------

In the demo, each participant is assigned one gain at random: the number of
points per collected object. The goal is the score that ends the game. Both
are set at the top of ``experiment.py``:

.. literalinclude:: ../../../demos/experiments/unity_autoplay/experiment.py
   :start-at: DEBUG = False
   :end-at: GOAL =

The page class sets the location of the Unity build and the size of the game
container:

.. literalinclude:: ../../../demos/experiments/unity_autoplay/experiment.py
   :pyobject: UnityGamePage

``resources`` is the URL of the directory that contains the build, under the
experiment's ``static`` directory. PsyNet loads the build from
``<resources>/scripts/Build/WebGL.*``. ``debug`` selects the debug page
described under `Debugging the game`_.

The game runs as a :doc:`static trial maker </code/writing_a_trial_maker>`.
Each trial shows one Unity page, which passes the goal and gain to Unity as
``contents``:

.. literalinclude:: ../../../demos/experiments/unity_autoplay/experiment.py
   :pyobject: GameTrial.show_trial
   :dedent: 4

When an answer contains ``"expire": true``, the trial maker's
``finalize_trial`` records this in a participant variable, and
``prepare_trial`` then ends the game:

.. literalinclude:: ../../../demos/experiments/unity_autoplay/experiment.py
   :pyobject: GameTrialMaker.prepare_trial
   :dedent: 4

The trial maker is an ordinary element of the timeline:

.. literalinclude:: ../../../demos/experiments/unity_autoplay/experiment.py
   :pyobject: Exp

The Unity side
--------------

The PsyNet API for Unity consists of two files, which the demo provides in
``UnityFiles/``:

``JaveScriptUnity.jslib``
    A plugin that reads the participant and page identity from the PsyNet
    page and exchanges JSON data with it. Place it in the Unity project's
    ``Plugins`` folder and leave it unchanged:

    .. figure:: ../../_static/images/experimenter/unity_integration/unity_3d_JaveScriptUnity.jslib.png
      :width: 340
      :align: center

``WebRequestManager.cs``
    A script that sends requests to PsyNet and reports the results through
    the ``onPsynetSyncResponse`` event. Attach it to an empty game object in
    the scene:

    .. figure:: ../../_static/images/experimenter/unity_integration/unity_3d_WebRequestManager.png
      :width: 800
      :align: center

The C# snippets below come from the ``GameManager`` script of the Unity
project used to build the demo. The Unity project itself is not included in
the PsyNet repository.

Handling responses from PsyNet
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Subscribe to ``WebRequestManager.onPsynetSyncResponse`` in ``OnEnable``:

.. code-block:: csharp

    void OnEnable()
    {
        WebRequestManager.onPsynetSyncResponse += HandlePsynetSyncResult;
    }

The handler receives a ``PsynetSyncResponse``, whose ``opCode`` identifies
the request that it answers:

.. code-block:: csharp

    private void HandlePsynetSyncResult(PsynetSyncResponse res)
    {
        int opcode = res.opCode;
        string data = res.data;
        switch (opcode)
        {
            case Constants.PAGE_SUBMITTTED:
                AfterPageSubmitted();
                break;
            case Constants.PAGE_UPDATED:
                AfterPageUpdate(data);
                break;
            case Constants.PAGE_INIT:
                StartCoroutine(WebRequestManager.instance.GetPage(Constants.PAGE_UPDATED));
                break;
            case Constants.PAGE_ERROR:
                terminateGame.SetActive(true);
                break;
        }
    }

Starting the game
~~~~~~~~~~~~~~~~~

``Start()`` calls ``WebRequestManager.Init()``, which fetches the participant
and page identity. Requests to PsyNet are asynchronous, so they run as
coroutines and report back through the handler:

.. code-block:: csharp

    void Start()
    {
        StartCoroutine(WebRequestManager.instance.Init(Constants.PAGE_INIT));
    }

When ``Init()`` completes, the handler calls ``GetPage()`` to fetch the page
contents. Game logic that depends on the parameters should start only in
``AfterPageUpdate(data)``, once the contents have arrived.

Reading parameters from PsyNet
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``AfterPageUpdate`` parses the page as JSON. The ``Ucontents`` class in the
``Settings`` script must match the ``contents`` dictionary in
``experiment.py`` by name and type:

.. code-block:: csharp

    public class Ucontents
    {
        public int goal = 0;
        public int gain = 0;
    }

``Ucontents`` is part of ``DashboardJson``, which does not need changing:

.. code-block:: csharp

    [Serializable]
    public class DashboardJson
    {
        public Uattributes attributes;
        public Ucontents contents;
    }

``GameManager`` parses the page into a ``DashboardJson`` object and reads the
parameters:

.. code-block:: csharp

    public DashboardJson dashboardJson = new DashboardJson();

    // In AfterPageUpdate
    dashboardJson = JsonUtility.FromJson<DashboardJson>(jsonData);
    m_Gain = dashboardJson.contents.gain;
    m_Goal = dashboardJson.contents.goal;

Sending answers to PsyNet
~~~~~~~~~~~~~~~~~~~~~~~~~

The ``Answer`` class in the ``Settings`` script defines the answer that Unity
submits. ``expire`` tells PsyNet that the game has finished:

.. code-block:: csharp

    public class Answer
    {
        public int score, reward;
        public double timeElapsed = 0;
        public bool expire = false;
        public string answer = "This is place holder for comments";
    }

In the demo, ``ScoreUp()`` runs each time the player collects an object and
submits the answer with ``SubmitPage()``:

.. code-block:: csharp

    public void ScoreUp()
    {
        m_Score += m_Gain;
        score.text = "Score: " + m_Score;
        if (m_Score > m_Goal)
        {
            answer.expire = true;
            terminateGame.SetActive(true);
        }
        answer.score = m_Score;
        answer.reward = m_Gain;
        StartCoroutine(WebRequestManager.instance.SubmitPage(answer, metadata, Constants.PAGE_SUBMITTTED));
    }

After a submission, PsyNet may send a new page, for example to change the
game's parameters. ``AfterPageSubmitted()`` fetches it:

.. code-block:: csharp

    public void AfterPageSubmitted()
    {
        StartCoroutine(WebRequestManager.instance.GetPage(Constants.PAGE_UPDATED));
    }

Building and running the game
-----------------------------

The demo was built with Unity 2020.3, using the free
`Unity Personal <https://unity.com/products/unity-personal>`_ license.

Debugging the game
~~~~~~~~~~~~~~~~~~

The game can run inside the Unity editor while it communicates with a local
PsyNet experiment. Set ``DEBUG = True`` in ``experiment.py`` and run
``psynet debug local``. After the consent page, PsyNet shows a debug page
with the game parameters instead of the game:

.. figure:: ../../_static/images/experimenter/unity_integration/unity_3d_debug_page.png
  :width: 800
  :align: center

Then run the game in the Unity editor, where ``WebRequestManager`` connects
to ``http://localhost:5000``. Running the game in Unity without a PsyNet
experiment produces errors such as these:

.. figure:: ../../_static/images/experimenter/unity_integration/unity_3d_errors.png
  :width: 800
  :align: center

Building for WebGL
~~~~~~~~~~~~~~~~~~

1. In Unity, open **File > Build Settings** and select **WebGL**:

   .. figure:: ../../_static/images/experimenter/unity_integration/unity_3d_build_settings.png
     :width: 800
     :align: center

2. Open **Player Settings**, and under **Publishing Settings** set
   **Compression Format** to **Disabled**:

   .. figure:: ../../_static/images/experimenter/unity_integration/unity_3d_build_settings_disable_compression.png
     :width: 800
     :align: center

3. Name the app ``WebGL``, because PsyNet loads files named ``WebGL.*``.
4. Click **Build And Run**. Unity opens the build in a browser, where it
   reports an error because PsyNet is not running.
5. Check that the ``Build`` folder in the WebGL output contains these files:

   .. figure:: ../../_static/images/experimenter/unity_integration/unity_3d_build_folder.png
     :width: 340
     :align: center

6. Copy the ``Build`` and ``TemplateData`` folders into the PsyNet
   experiment's ``static/scripts/`` directory.
7. Set ``DEBUG = False`` in ``experiment.py``.

Run ``psynet debug local`` from the experiment directory. After the consent
page, the game runs embedded in the page, and the timeline continues when the
game ends.
