from typing import List, Literal, Optional

from markupsafe import Markup
from psynet.consent import Consent
from psynet.modular_page import PushButtonControl
from psynet.page import RejectedConsentPage
from psynet.timeline import CodeBlock, Module, conditional, join
from psynet.utils import get_translator

from consents_cococo._utils import ConsentPageWrapper, _resolve_duration_payment

_ = get_translator()
_p = get_translator(context=True)

AddendumRegion = Literal["europe", "korea", "singapore_taiwan"]

IRB_PROTOCOL_NUMBER = "IRB0148995"
STUDY_TITLE = "Designing Smart Environments to Support Group Learning and Creativity"


def _h3(ctx_key: str, text: str) -> str:
    return (
        "<h3 style='font-size:1.05rem;font-weight:600;margin-top:1.5rem'>"
        f"{_p(ctx_key, text)}</h3>"
    )


def _section(ctx_key: str, title: str, body: str) -> str:
    return f"{_h3(ctx_key, title)}<div class='consent-section'>{body}</div>"


def _duration_payment_text(DURATION, PAYMENT, show_duration_payment: bool) -> str:
    if not show_duration_payment:
        return ""

    DURATION, PAYMENT = _resolve_duration_payment(DURATION, PAYMENT)
    return (
        f"The estimated duration of the experiment is <strong>{DURATION}</strong> "
        f"minutes, with an expected payment of <strong>{PAYMENT}</strong> USD."
    )


def _overview_content() -> str:
    return _section(
        "sl_overview_title",
        "Online consent",
        _p(
            "sl_overview_body",
            """
<p>Jacoby's lab is inviting you to take part in a research study called "Designing Smart Environments to Support Group Learning and Creativity." We'll explain the study to you and are happy to answer any questions you have. The study is led by Nori Jacoby from the Psychology Department at Cornell University, and it is supported by a grant from the National Science Foundation.</p>
""",
        ),
    )


def _purpose_content() -> str:
    return _section(
        "sl_purpose_title",
        "What the study is about",
        _p(
            "sl_purpose_body",
            """
<p>This study looks at what helps groups learn. We want to see how people decide things together, do tasks as a team, and come up with creative ideas collaboratively. You'll play an online game where what you do affects, and is affected by, other players. We'll watch how you work with them and how changing the game's rules changes the group's behavior.</p>
""",
        ),
    )


def _procedure_content() -> str:
    return _section(
        "sl_procedure_title",
        "What we will ask you to do",
        _p(
            "sl_procedure_body",
            """
<p>First, you'll sign an online consent form and answer a few simple questions about yourself. Next, you'll complete a brief survey, experiment, or small computer game. While playing, you may chat with other players or their avatars, share information, and help set the game's rules. Some sessions also include quick puzzles that test skills like language, perception, or math.</p>
""",
        ),
    )


def _risks_content() -> str:
    return _section(
        "sl_risks_title",
        "Risks and discomforts",
        _p(
            "sl_risks_body",
            """
<p>These experiments are behavioral and involve minimal risk, with no risks beyond those associated with normal computer use. We will not present any triggering, profane, or controversial content. The experiments are unlikely to cause emotional distress, such as sadness or anxiety; however, some participants may find them boring. We make every effort to ensure the experiments are as engaging as possible.</p>
""",
        ),
    )


def _benefits_content() -> str:
    return _section(
        "sl_benefits_title",
        "Benefits",
        _p(
            "sl_benefits_body",
            """
<p>There are no direct benefits to participating in the experiment, aside from contributing to scientific knowledge. The information gathered from this study may help others now or in the future by improving the design of learning and social systems. By participating, you also help advance the overall understanding of collective action and cognition.</p>
""",
        ),
    )


def _incentives_content(DURATION, PAYMENT, show_duration_payment: bool) -> str:
    duration_payment_text = _duration_payment_text(DURATION, PAYMENT, show_duration_payment)
    return _section(
        "sl_incentives_title",
        "Incentives for participation",
        _p(
            "sl_incentives_body",
            """
<p>We will compensate you at a rate of approximately $10 per hour. {DURATION_PAYMENT_TEXT} Compensation will be processed through the recruitment service (e.g., Prolific), and we will share your alphanumeric participant ID, completion status, session timing, and details of compensation and bonus payments with them. You may also be eligible for a performance-based bonus, which may depend on your accuracy or on how others perceive your responses. If bonus opportunities are available, you will be notified during the experiment. The bonus will never exceed ten times the regular payment for the experiment.</p>
""",
        ).replace("{DURATION_PAYMENT_TEXT}", duration_payment_text),
    )


def _ai_content() -> str:
    return _section(
        "sl_ai_title",
        "AI in the experiment and analysis",
        _p(
            "sl_ai_body",
            """
<p>Please note that in some experiments, your data may be shared with industry-based large language models (LLMs) or artificial intelligence (AI) agents. In such cases, only the information you provide or receive during the interaction will be shared; your recruiter identity will not be disclosed.</p>
<p>The experiments may involve interacting with other participants or AI agents. Your real name and personal identifiers will never be shared. However, if you voluntarily provide personal details during the experiment, they may become visible to others. Please avoid sharing any private or identifying information. Data may also be shared with AI agents (e.g., ChatGPT, Claude, Gemini, Llama, Mistral, or Grok), but it will not reveal your identity unless you disclose personal information yourself.</p>
<p>Your response may also be analyzed after the experiment using AI systems. For example, we may reprocess the response you provided through AI models other than the one you originally interacted with.</p>
""",
        ),
    )


def _privacy_content() -> str:
    return _section(
        "sl_privacy_title",
        "Privacy/Confidentiality/Data Security",
        _p(
            "sl_privacy_body",
            """
<p>During the study, we will only know you by a participant ID made of alphanumeric code. We do not collect your personal details, just this code from the recruitment service (e.g., Prolific). If you choose to type something that reveals who you are, such as your real name, that text could be stored and seen by others, but providing such information is never required.</p>
<p>The experiments may include sharing your responses and interactions with other participants. Your real name or personal identifiers will never be shared. However, if you choose to provide personal details during the experiment, that information may be transmitted to other participants or AI agents. Please do not share private or identifying information that you do not want disclosed. We emphasize that you will never need to provide personal information during our experiments.</p>
<p>We may share the study data with other researchers or make it public to support open science, but we will keep it de-identified so no one can link the data back to you. We protect data with security measures including secure servers, encryption, and restricted access.</p>
<p>We will do our best to keep your participation confidential to the extent permitted by law; however, research records may be reviewed by the Office for Human Research Protections, the National Science Foundation, Cornell University's Institutional Review Board, and the Office for Research Integrity and Assurance.</p>
<p>We anticipate that your participation presents no greater risk than everyday use of the Internet. The experiment may be conducted with the help of a recruiter such as Prolific, Amazon Mechanical Turk, CINT, or Qualtrics, each with its own privacy and security policies. Email communication is neither private nor secure, and data may exist on backups and server logs beyond the timeframe of this research project. Confidentiality will be kept to the degree permitted by the technology being used, but we cannot guarantee against interception of data sent via the internet by third parties.</p>
""",
        ),
    )


def _sharing_content() -> str:
    return _section(
        "sl_sharing_title",
        "Sharing De-identified Data Collected in this Research",
        _p(
            "sl_sharing_body",
            """
<p>De-identified data from this study may be shared with the research community at large to advance science and health. We will remove or code any personal information that could identify you before files are shared with other researchers to ensure that, by current scientific standards and known methods, no one will be able to identify you from the information we share.</p>
""",
        ),
    )


def _voluntary_content() -> str:
    return _section(
        "sl_voluntary_title",
        "Taking part is voluntary",
        _p(
            "sl_voluntary_body",
            """
<p>Participation is completely voluntary. You can choose to stop participating at any time by simply closing the experiment window and ending the session. Before you participate, you must meet the following conditions:</p>
<ol>
  <li>You are over 18 years old.</li>
  <li>You speak the language specified in the advertisement.</li>
  <li>You meet the technical requirements, such as having a microphone and the correct browser version as specified in the advertisement.</li>
</ol>
<p>At the start of the session, we may check for compliance with these conditions. If you do not meet them, your session will be terminated; however, you will still be compensated at the same hourly rate for participating in this initial test. The length of each experiment may vary, but you will be compensated at the same hourly rate, proportional to the amount of work and/or session duration. If you choose to withdraw early, you may not receive compensation or may receive partial compensation. Please provide your consent only if you agree with these terms.</p>
""",
        ),
    )


def _followup_content() -> str:
    return _section(
        "sl_followup_title",
        "Follow up studies",
        _p(
            "sl_followup_body",
            """
<p>We may contact you again to request your participation in a follow up study. As always, your participation will be voluntary and we will ask for your explicit consent to participate in any follow up studies.</p>
""",
        ),
    )


def _questions_content() -> str:
    return _section(
        "sl_questions_title",
        "If you have questions",
        _p(
            "sl_questions_body",
            """
<p>The main researcher conducting this study is Nori Jacoby, an assistant professor in the Psychology department at Cornell University. Please ask any questions you have now. If you have questions later, you may contact Nori at {EMAIL} or at {PHONE}. If you have questions or concerns regarding your rights as a subject in this study, you may contact the Institutional Review Board (IRB) for Human Participants at {IRB_PHONE} or access their website at <a href="{IRB_URL}" target="_blank">{IRB_URL}</a>. You may also report concerns or complaints anonymously through Ethicspoint online at <a href="https://{ETHICS_URL}" target="_blank">{ETHICS_URL}</a> or by calling toll free at {ETHICS_PHONE}. Ethicspoint is an independent organization that serves as a liaison between the University and the person bringing the complaint so that anonymity can be ensured.</p>
""",
        ),
    )


def _statement_content() -> str:
    return _section(
        "sl_statement_title",
        "Statement of Consent",
        _p(
            "sl_statement_body",
            """
<p>I have read the above information, and have received answers to any questions I asked. I consent to take part in the study. By choosing to consent electronically I confirm my consent to this study.</p>
""",
        ),
    )


def _addendum_content(region: AddendumRegion) -> str:
    titles = {
        "europe": _p("sl_addendum_gdpr_title", "Supplemental Privacy Notice - General Data Protection Regulation (GDPR)"),
        "korea": _p("sl_addendum_kpipa_title", "Supplemental Privacy Notice - Personal Information Protection Act (PIPA), South Korea"),
        "singapore_taiwan": _p("sl_addendum_sg_tw_title", "Supplemental Privacy Notice - Personal Data Protection Act (PDPA), Singapore/Taiwan"),
    }
    bodies = {
        "europe": _p(
            "sl_addendum_gdpr_body",
            """
<p class="consent-text">Cornell University and the Principal Investigator are jointly responsible for this research study, and Cornell acts as the data controller. Cornell will keep identifiable information for 5 years after the study has finished, or longer if required by law or to protect legal rights.</p>
<p class="consent-text">During the study, we normally know you only by an alphanumeric participant ID from the recruitment service. If you type personal information, interact with other participants or AI agents, or participate in a study with audio/video recording, that information may be processed as described in the main consent. We will request additional explicit consent before collecting audio or video data.</p>
<p class="consent-text">Your data may be used to determine eligibility, invite participation, carry out and monitor the study, make required reports, and conduct future related or unrelated research. Cornell uses physical, technical, and administrative safeguards including secure servers, encryption, restricted access, hard-disk encryption, and strict access controls.</p>
<p class="consent-text">You may request access, correction, an electronic copy or transfer of your identifiable information, or request that your information no longer be used. These rights may be limited until completion of the research when needed to protect research integrity. Research is processed as a task in the public interest, and sensitive audiovisual information requires explicit consent that may be withdrawn by contacting the Principal Investigator or Cornell's Data Protection Officer.</p>
<p class="consent-text">Cornell is located in the United States, so data may be transmitted to Cornell researchers in the United States. To exercise rights, contact Nori Jacoby at kj338@cornell.edu or Cornell's Data Protection Officer at privacy-requests@cornell.edu.</p>
""",
        ),
        "korea": _p(
            "sl_addendum_kpipa_body",
            """
<p class="consent-text">Cornell University and the Principal Investigator are jointly responsible for this study, and Cornell acts as the data controller. Identifiable information is kept for the retention period and may be kept longer if required by law or to protect legal rights.</p>
<p class="consent-text">The study may process your participant ID, any personal information you choose to provide, interactions with other participants or AI agents, AI analysis of responses, and audio/video data if an experiment includes recordings. Additional explicit consent will be requested before collecting audio or video data.</p>
<p class="consent-text">Under South Korea's Personal Information Protection Act, Cornell must have a lawful and fair basis for processing personal information, and explicit affirmative consent is required before personal or sensitive information may be transmitted overseas. Your data may be stored on password-protected devices/servers, moved to Cornell servers, and processed with AI tools such as ChatGPT, Gemini, Claude, or Grok in ways that do not link responses to recruiter ID or name.</p>
<p class="consent-text">You have rights to be informed, request access and correction, seek appropriate redress, and request that your information no longer be used, though these rights may be limited in academic research. Information that must be retained will be stored and managed separately.</p>
<p class="consent-text">To exercise rights, contact Nori Jacoby at kj338@cornell.edu or Cornell's Data Protection Officer at privacy-requests@cornell.edu.</p>
""",
        ),
        "singapore_taiwan": _p(
            "sl_addendum_sg_tw_body",
            """
<p class="consent-text">Cornell University and the Principal Investigator are jointly responsible for the study, and Cornell acts as the data controller. Cornell will keep identifiable information until completion of the research project and longer if required by law or to protect legal rights.</p>
<p class="consent-text">The research may collect textual responses, mouse movement, mouse clicks, and interaction with the experiment/game environment. Some parts may require audio recordings such as speaking or singing, or video recordings such as images of your face or body movements; in those cases, specific additional consent will be requested.</p>
<p class="consent-text">Your data may be used to determine eligibility, invite participation, carry out and monitor the study, make required reports, and conduct future related or unrelated studies. Cornell uses safeguards such as encrypted storage and pseudoanonymization, and information is handled by authorized Cornell personnel, research offices, collaborators, funding agencies, or sponsors as needed.</p>
<p class="consent-text">You may request access, correction, an electronic copy or transfer of your identifiable information, or request that your information no longer be used. These rights may be limited until the research is complete when needed to protect research integrity. Cornell is located in the United States, so information may be transmitted to Cornell researchers there.</p>
<p class="consent-text">To exercise rights, contact Nori Jacoby at kj338@cornell.edu or Cornell's Data Protection Officer at privacy-requests@cornell.edu.</p>
""",
        ),
    }
    return f"""
<hr>
<div class="text-left" style="font-size:18px;border-left:4px solid #0066cc;padding-left:1rem;margin-top:1rem">
  <h4>{titles[region]}</h4>
  <p class="consent-text" style="font-size:smaller">IRB Protocol: "{STUDY_TITLE}." {IRB_PROTOCOL_NUMBER}</p>
  {bodies[region]}
</div>
"""


def _build_consent_html(
    DURATION=None,
    PAYMENT=None,
    show_duration_payment: bool = True,
    addendum_regions: Optional[List[AddendumRegion]] = None,
) -> str:
    html = "".join(
        [
            f"<h2 style='margin-bottom:0.3rem;font-weight:600;font-size:2.15rem'>{_p('sl_page_heading', 'We need your consent to proceed')}</h2>",
            "<hr style='border:none;border-top:2px solid #000;margin:0.8rem 0 1.3rem'/>",
            _overview_content(),
            _purpose_content(),
            _procedure_content(),
            _risks_content(),
            _benefits_content(),
            _incentives_content(DURATION, PAYMENT, show_duration_payment),
            _ai_content(),
            _privacy_content(),
            _sharing_content(),
            _voluntary_content(),
            _followup_content(),
            _questions_content(),
            _statement_content(),
        ]
    )
    if addendum_regions:
        for region in addendum_regions:
            html += _addendum_content(region)
    return html


class consent_cococo_science_of_learning(Module, Consent):
    """
    Cornell IRB0148995 consent for "Designing Smart Environments to Support
    Group Learning and Creativity."

    Parameters
    ----------
    DURATION : int, optional
        Estimated duration in minutes. If omitted and show_duration_payment=True,
        read from prolific_estimated_completion_minutes in config.txt.
    PAYMENT : float, optional
        Expected payment in USD. If omitted and show_duration_payment=True, read
        from base_payment in config.txt.
    show_duration_payment : bool
        Show or hide the participant-facing duration/payment sentence.
    addendum_regions : list or None
        Any of ["europe", "korea", "singapore_taiwan"].
    """

    time_estimate = 60

    def __init__(
        self,
        DURATION=None,
        PAYMENT=None,
        show_duration_payment: bool = True,
        addendum_regions: Optional[List[AddendumRegion]] = None,
        EMAIL: str = "kj338@cornell.edu",
        PHONE: str = "+1-607-255-3834",
        IRB_PHONE: str = "607-255-6182",
        IRB_URL: str = "https://researchservices.cornell.edu/offices/IRB",
        ETHICS_URL: str = "www.hotline.cornell.edu",
        ETHICS_PHONE: str = "1-866-293-3077",
        **kwargs,
    ):
        consent_text = _build_consent_html(
            DURATION=DURATION,
            PAYMENT=PAYMENT,
            show_duration_payment=show_duration_payment,
            addendum_regions=addendum_regions,
        )
        consent_text = consent_text.format(
            EMAIL=EMAIL,
            PHONE=PHONE,
            IRB_PHONE=IRB_PHONE,
            IRB_URL=IRB_URL,
            ETHICS_URL=ETHICS_URL,
            ETHICS_PHONE=ETHICS_PHONE,
        )
        consent_text = Markup(consent_text)

        consent_page = ConsentPageWrapper(
            "consent_choice",
            consent_text,
            PushButtonControl(
                choices=["I consent", "I do not consent"],
                labels=[_p("sl_consent_answer_yes", "I consent"), _p("sl_consent_answer_no", "I do not consent")],
                arrange_vertically=False,
                bot_response="I consent",
            ),
            time_estimate=self.time_estimate,
        )

        elts = join(
            consent_page,
            conditional(
                "science_of_learning_consent_conditional",
                lambda experiment, participant: participant.answer == "I do not consent",
                RejectedConsentPage(failure_tags=["science_of_learning_consent_rejected"]),
            ),
            CodeBlock(lambda participant: participant.var.set("science_of_learning_consent", participant.answer)),
        )

        super().__init__(
            "consent_cococo_science_of_learning",
            elts,
            **kwargs,
        )
