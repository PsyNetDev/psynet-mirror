.. |br| raw:: html

   <br />

.. raw:: html

   <style> .red {color: red;} </style>

.. role:: red

Unity integration
=================

**See the associated** `unity_autoplay demo <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/unity_autoplay>`_
(``demos/experiments/unity_autoplay``).

PsyNet includes several GUI features that can accelerate the development of appealing experimental environments. In addition, standard HTML5 and WebGL features can be implemented with relative ease. The built-in network visualization panel of the dashboard, is a nice example of how such tools can be used. However, for experiments where a sophisticated and gamified user interface in either 2D or 3D is desired, it makes more sense to use a well developed 3rd party GUI RDE. Unity 3D is among the leading RDEs for games, and it has several advantages:

#. The same code base can be compiled and deployed with relative ease, as a native app,  across platforms including WebGL, Windows, macOS, iOS, Android, etc.
#. Both 2D and 3D virtual worlds physics are well developed
#. There are many 3rd party components in the Unity App store that can be easily integrated. These include both high and low level tools such as embedded graphs, a virtual playable 3D piano, animated coins, etc.

Learning Unity is outside the scope of this tutorial, but there are many great resources for learning Unity including `Unity Learn <https://learn.unity.com/>`_. We will start with a quick tutorial of a simple Unity game, which is provided in the `demo project <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/unity_autoplay>`_.

The figure below shows the simple Unity 3D world that we created. It includes a player (yellow cylinder) and several collectable objects (red and blue cubes):

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_player.png
  :width: 600
  :align: center

  A Unity 3D scene with a player (yellow cylinder) and collectable objects

In the game, the player collect objects to gain score:

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_score.png
  :width: 600
  :align: center

|br|
Once the goal of collecting 10 objects is achieved, the game ends:

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_game_over.png
  :width: 600
  :align: center

|br|
In this demo, PsyNet assigns participants into three groups. In group 1 players gain two points for each item they collect, in group 2 players gain three points per item, and in group 3 players gain four points per item. In addition, Psynet sets the number of points needed to end the game.

These variables are defined in the beginning of the Psynet experiment file:

.. code-block:: python

   rules = ['2', '3', '4'] # The score (gain) for collecting an item
   Goal = 10 # Once score reach this goal the game is finished

So now Psynet will automatically recruit participants, assign them to groups and once a participant begins playing, PsyNet and Unity need to start talking to each other: PsyNet needs to send game parameters to Unity, and Unity needs to report each coin collection event to Psynet. Note that whereas Psynet uses Python, Unity scripts are C# code. Note also that the Unity app is compiled as a WebGL app, which allows us to run the game online embedded in a web browser page, which Psynet creates. This means that once we compiled the game, Unity code cannot be accessed or modified. However, our API has a debug mode, which allows you to simultaneously debug PsyNet and Unity code inside the Unity IDE prior to compilation.

Embedding Unity in Psynet involves several challenges, which we alleviated by developing a PsyNet-Unity API. The role of the API is to allow a nearly real-time, two way communication between Unity and PsyNet: The communication form Unity to PsyNet is designed to be instantaneous, and can be functionally almost continuous. On the other hand, communication from PsyNet to Unity is typically intermittent. In the mechanisms we describe below, Psynet is "driving" Unity by setting variables and parameters via the content of the Unity page, within which Unity is embedded. Here is an overall illustration of how it works:

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_workflow.png
  :width: 800
  :align: center

|br|
In the example above, the participant is playing a coin collecting Unity game embedded in a web browser.  PsyNet recruits participants and assigns each participant with game parameters, which are embedded in the webpage window. When the game initiates, Unity reads these parameters and the game can then start.  As the game proceeds, Unity sends information to Psynet (e.g., that the participants collected a coin). If the game has several stages, Unity can drive these transitions by creating a new (invisible) page with different parameters. Finally, Unity decides when to end the game, and moves forward with the timeline.

Note that in the PsyNet timeline the Unity app is simply the trial maker, for example:

.. code-block:: python

   class Exp(psynet.experiment.Experiment):
      consent_audiovisual_recordings = False
      timeline = Timeline(
          MainConsent(),
          trial_maker, # The Unity game
          InfoPage("You finished the experiment!", time_estimate=0),
          SuccessfulEndPage(),
      )

In the demo experiment will see a Page type called UnityGamePage:

.. code-block:: python

   page = UnityGamePage(
      # Send this string to Unity
      contents=data,
      # We stay in the same session.
      session_id=SAME_SESSION_ID,
      time_estimate=1
   )
   return page  # list_of_pages

This page contains data that PsyNet will sent to Unity in real time (adaptively for each player) including the two game parameters:

.. code-block:: python

   data = {
      "goal": goal,
      "gain": the_rule,
   }

The rest is taken care of by the API.

Running the game
----------------

Running the game is easy, just go to the terminal, browse to the demo folder, activate your virtual environment, and type ``psynet debug``. The project should then run in your browser window, just like any other PsyNet project, after informed consent, Unity should run embedded in your page,  and once the game is over PsyNet timeline will continue.

Developing and debugging the Unity game
---------------------------------------

We will first describe the 'Installation' process. Then we will explain how the Unity-Psynet API works. Finally, we will go line by line through the demo, which will allow you to independently build a project from scratch. example.

Installing a Unity-Psynet project
#################################

You should install the free (Personal) version of Unity. Currently, we use Unity 2020.3

https://unity.com/products/unity-personal

Once Unity is installed in your system, it might be useful to begin by opening the very simple testing project that we included in the demo. It should look more or less like this:

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_project.png
  :width: 800
  :align: center

|br|
In the center, you see the scene including a plane, several 3D objects (cubes) and a yellow cylinder representing the player. Note, however, the we designed this project for PsyNet, and it will not run independently. If you see these errors:

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_errors.png
  :width: 800
  :align: center

|br|
This is because you tried running it before setting up the PsyNet experiment.

The API allows you to debug the Unity project inside the Unity IDE. That is, before you even created the WebGL app. For this, all you need to do is to set the debug variable in the Psynet experiment file to ``True``:

.. code-block:: python

   # Stimuli ---------------------------------------------------------------------
   Debug = True

Now, open your terminal, navigate to the demo folder, and run ``psynet debug --verbose``. If everything is working as intended, you should see and informed consent form, and then you will see this page:

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_debug_page.png
  :width: 800
  :align: center

|br|
Note that the page content includes the two game parameters: the goal (score needed to finish the game) and the gain (number of points per item collection).

Only now you may go to Unity, run and debug your game. Unity has an excellent debugger. We strongly recommend installing the JetBrain Rider as the editor (do not use the default Visual Studio). Rider (https://www.jetbrains.com/rider/) is very similar to PyCharm, and it is free for academic usage. Once Rider is installed, go to Unity, and in Preferences, select Rider:

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_rider.png
  :width: 800
  :align: center

|br|
Now you can access the Unity scripts like this: in the Hierarchy, click the 'world' item. Then in the Inspector, click the three vertical dots on the right of the GameManager script and select 'Edit Script'.

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_edit_script.png
  :width: 800
  :align: center

|br|
This will open Rider and will show you the editor and debugger windows:

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_rider_editor.png
  :width: 800
  :align: center

|br|
Make sure you are attached to the Unity editor and that the debug button is on:

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_debug_button.png
  :width: 800
  :align: center

|br|
You can now create breakpoints, and run the game from the IDE until everything works.

Next you will want to compile your WebGL app.

Go back to Unity, and in the menu select file -> Build Settings...

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_build_settings.png
  :width: 800
  :align: center

|br|
Make sure that WebGL is selected. Before clicking Build And Run, click on Player Settings...

There, in publishing settings, disable the Compression Format (see bottom):

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_build_settings_disable_compression.png
  :width: 800
  :align: center

|br|
:red:`Important: you must name your app WebGL.`

Only then go back to build settings and click Build And Run. Compiling the WebGL may take several minutes. Unity will then open a browser window and will attempt to run your WebGL app -- but you will get an error -- ignore it. This is just telling you that your project cannot run without PsyNet.

Now navigate to your WebGL folder (inside your Unity project), and make sure the files in the Build folder are exactly like this:

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_build_folder.png
  :width: 340
  :align: center

|br|
Next, all you need to do is to copy the Build and TemplateData folders from WebGL  into your Unity project. They should go under Static/Scripts/

Finally, go to your PsyNet experiment code, set the debug variable to False, and run your project.

Understanding the Psynet Unity API
##################################

In Unity, the PsyNet API is implemented in two files. At the lowest level there is a JaveScriptUnity file in the Unity project Plugins folder. This library allows information to be communicated between Unity and PsyNet in the form of JSON data structures. This file also connects between the client WebGL app and PsyNet to set the participant and page identity. You should never edit this file, but make sure it is in place:

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_JaveScriptUnity.jslib.png
  :width: 340
  :align: center

|br|
The API communication logic is implemented in a Unity script called  WebRequestManage.cs. It  should give you all utilities needed to take advantage of the Psynet API functionality, enabling back and forth communication between Unity and Psynet. We will discuss this unit usage below. In most cases, you will use it but not edit it.

How to use PsyNet to "drive" a Unity game
#########################################

Next, we explain how the Unity scripts interact with Psynet.

First, you need to link the WebRequestManager script to your game. This is done simply by creating an empty game object in unity, and adding the script to the object hierarchy:

.. figure:: ../_static/images/experimenter/unity_integration/unity_3d_WebRequestManager.png
  :width: 800
  :align: center

|br|
Next, we need to create a pipeline of event handlers, which we do in OnEnable:

.. code-block:: csharp

    void OnEnable()
    {
        WebRequestManager.onPsynetSyncResponse +=  HandlePsynetSyncResult;
    }

You can easily create event handlers, although the ones we provide might suffice:

.. code-block:: csharp

   private void HandlePsynetSyncResult(PsynetSyncResponse res)
   {
        int opcode = res.opCode; // code tells WebrequestManager what is the context of the call
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
                // Finish the game
                terminateGame.SetActive(true);
                break;
        }
    }

Note that each of these events trigger a custom GameManager function such as ``AfterPageSubmitted()``. This is where you will implement much of your game logic. In other cases, the event will trigger another WebRequestManager coroutine, which will, in turn, fire another event, e.g., :

.. code-block:: csharp

    case Constants.PAGE_INIT:
        StartCoroutine(WebRequestManager.instance.GetPage(Constants.PAGE_UPDATED));

Here, we call ``GetPage()`` after game initiation, because we want to get instructions from Psynet on how to run the game. We are going to call ``GetPage()`` during the game as well, as we will show below.

Game Initiation logic
#####################

When the game starts, Unity will need to know the PyNet user id and the procedure for communication via JSON, this is done in the ``Start()`` function of the game, by calling the WebRequestManager ``Init()`` function. Note that we use a coroutine and events because these functions are not synchronous and we cannot predict it would take them to return. This means that we may not want to allow the game to really start before this function returns:

.. code-block:: csharp

    // Start is called before the first frame update
    void Start()
    {
        StartCoroutine(WebRequestManager.instance.Init(Constants.PAGE_INIT));
    }

This is why you want to implement game logic and allow users to do things only after information is in place, that is, in ``AfterPageUpdate(data)``, which is only called once all information from Psynet has arrived.

As noted, Unity may need, at least once, and sometimes much more than once, to get instructions from PsyNet on how to run the game. This logic is achieved by PsyNet creating 'silent' embedded pages, without requiring Unity to restart (which would be painful).

Communication from PsyNet to Unity
##################################

The central function in unity here is ``AfterPageUpdate(data)``, which is called in the beginning of the game and also (optionally) after communication from Unity to PsyNet was established. It reads a JSON string from the content of the ``UnityGamePage`` and parses them. In the demo these are:

.. code-block:: js

    data = {
        "goal": goal,
        "gain": the_rule,
    }

For this to happen, we need to have a structure in the Unity code that matches that of the PsyNet content, and then we use the standard Unity JSON library to parse, and retrieve the content into the Unity script variable.

In the Settings file you will find the Ucontents serializable class:

.. code-block:: csharp

    public class Ucontents//DashboardJson
    {
        public int goal = 0;
        public int gain = 0;
    }

This is where you can add variables and structures that must be matched, by both name and type, to those in the PsyNet ``experiment.py`` content structure we described above. ``Ucontents`` is contained inside the ``DashboardJson`` class, which you will not need to change directly:

.. code-block:: csharp

    [Serializable]
    public class DashboardJson
    {
        public Uattributes attributes;
        public Ucontents contents;
    }

Now, in GameManager we declare a ``DashboardJson`` object called ``dashboardJson``:

.. code-block:: csharp

    public DashboardJson dashboardJson = new DashboardJson();

And all we need to do in ``AfterPageUpdate`` is a single line:

.. code-block:: csharp

    dashboardJson = JsonUtility.FromJson<DashboardJson>(jsonData);

This line will retrieve all your variables into ``dashboardJson``.

You can then call these variables like this:

.. code-block:: csharp

    m_Gain = dashboardJson.contents.gain;
    m_Goal = dashboardJson.contents.goal;


Communication from Unity to PsyNet
##################################

Unity can initiate communication with Psynet at any time by sending a JSON string of variables. Here the important structure is Answer, which is located in the Settings script:

.. code-block:: csharp

    public class Answer // change name to MetaData
    {
        public int score, reward;
        public double timeElapsed = 0;
        public bool expire = false;
        public string answer = "This is place holder for comments";
    }

The ``Answer`` class can be used to report any set of game states. In the example above score indicates the current game score and reward indicates the reward rate. In addition we might want to report the time elapsed since the game started and a text answer that can include any free text information. These variables are often used to elicit a response from PsyNet. An example of this is the ``expire`` boolean variable, which tells Psynet it is time to end the game.

In our demo project all this communication takes place within the function ``ScoreUp()``, which is called once the player collected an object:

.. code-block:: csharp

    public void ScoreUp()
    {
        m_Score+=m_Gain;
        score.text = "Score: " + m_Score;
        if (m_Score > m_Goal)
        {
            answer.expire = true;
            terminateGame.SetActive(true);
        }
        answer.score=m_Score;
        answer.reward = m_Gain;
        StartCoroutine(WebRequestManager.instance.SubmitPage(answer, metadata, Constants.PAGE_SUBMITTTED));
    }

Note that once PsyNet had received the answer, Psynet might want to talk back, perhaps in order to change game stage or a game rule. At the PsyNet side, this is done by creating a new embedding page (Psynet can do it without interrupting Unity). To test for this, Unity calls the ``GetPage()`` method after submitting the answer:

.. code-block:: csharp

    public void AfterPageSubmitted()
    {
        StartCoroutine(WebRequestManager.instance.GetPage(Constants.PAGE_UPDATED)); // we now get the information from the new page
    }

Now Unity can act upon any changes that Psynet has evoked.
