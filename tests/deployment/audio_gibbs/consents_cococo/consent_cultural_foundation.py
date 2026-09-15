"""
IRB0150361 Consent — "The cultural foundation of perception and cognition – online experiments"

consent_irb_cultural_foundation(consent="MAIN"|"CINT"|"DATABASE", audiovisual=bool, addendum_regions=list)
debrief_page()  # add at end of timeline

HTML structure mirrors PsyNet built-in consent templates:
  psynet/templates/consents/main_consent.html
  psynet/templates/consents/audiovisual_consent.html
  psynet/templates/macros/consent.html
"""

from markupsafe import Markup
from psynet.consent import Consent
from psynet.utils import null_translator, null_translator_with_context, get_translator
from psynet.timeline import Module, Page, join, conditional, CodeBlock
from psynet.page import InfoPage, RejectedConsentPage
from typing import Optional, List, Literal

from consents_cococo._utils import _resolve_duration_payment

# IRB0150361 approved English consent text only. We intentionally bypass the
# psynet translate pipeline for this namespace: the consent text is rendered
# in English regardless of the experiment's locale, which is the
# IRB-compliant behaviour. Using null_translator avoids psynet trying to
# load a consents_cococo.po file that does not (and should not) exist.
_ = get_translator()
_p = get_translator(context=True)

ConsentType = Literal["MAIN", "CINT", "DATABASE"]
AddendumRegion = Literal["europe", "korea", "singapore_taiwan"]

IRB_PROTOCOL_NUMBER = "IRB0150361"
STUDY_TITLE = "The cultural foundation of perception and cognition \u2013 online experiments"


# =============================================================================
# HTML helpers — match psynet/templates/macros/consent.html structure
# =============================================================================

def _h4(ctx_key: str, text: str) -> str:
    return f"<h4>{_p(ctx_key, text)}</h4>"


def _p_text(ctx_key: str, text: str) -> str:
    return f'<p class="consent-text">{_p(ctx_key, text)}</p>'


# =============================================================================
# Audiovisual consent content
# Mirrors audiovisual_consent.html: red bold intro <h4>, then sections
# =============================================================================

def _audiovisual_content(include_ai_consent: bool = False) -> str:
    content = str(Markup(f"""
<hr>
<p>
<h4 style="color: red; font-weight: bold;">
  {_p('cf_av_title1', 'In this study, you may be asked to make an audio, video, or audio-visual recording.')}
  {_p('cf_av_title2', 'For example, you may be asked to record your finger-tapping in response to a sound or video, or to record yourself speaking or singing.')}
</h4>
</p>
<div class="text-left" style="font-size:18px">

  <h4>{_p('cf_av_heading', 'Audio-Visual Consent (Additional Consent for Studies Involving Recording)')}</h4>

  <h4>{_p('cf_av_what_covers', 'What this consent covers')}</h4>
  <p class="consent-text">
    {_p('cf_av_what_body', 'In this study, you may be asked to make an audio, video, or audio-visual recording. This may include, for example, recordings of your voice, finger tapping in response to sounds or videos, or recordings of you speaking or singing. We may also record aspects of your body posture, facial movements, or gestures. These recordings help us better understand your engagement with the experiment. The term "recording" below refers to audio, video, or audio-visual data.')}
  </p>

  <h4>{_p('cf_av_confidentiality', 'Confidentiality')}</h4>
  <p class="consent-text">
    {_p('cf_av_conf1', 'All recordings will be treated as confidential research data. Only the research team will have access to the original audio or video files.')}
    {_p('cf_av_conf2', 'In some experiments, recordings may be shared with other participants so they can listen to, rate, or respond to them (for example, by reproducing a rhythm you created). In such cases, the recordings will never be linked to your name or any identifying information.')}
  </p>
  <p class="consent-text">
    {_p('cf_av_conf3', 'Your recordings will not be used to determine your identity and will never be made public. If data are shared with collaborators, we will share only processed or de-identified data — never the raw recordings themselves.')}
    {_p('cf_av_conf4', 'While we take strong precautions, please remember that sounds or images from your surroundings might reveal personal details. Before recording, make sure that no other people, private conversations, or identifiable objects appear in view or are audible. Please also avoid profanity in audio recordings and nudity or explicit content in video recordings.')}
  </p>
  <p class="consent-text">
    {_p('cf_av_ai', 'In some cases, your data may be sent for analysis or used to enable interactions with AI agents or multimodal (generative AI) models such as ChatGPT, Claude, or Gemini. Your personal identifiers (e.g., recruiter ID) will never be shared. However, please note that audio or video recordings could potentially reveal your identity. If such use is required, we will obtain your explicit consent before including you in the experiment.')}
  </p>
  <p class="consent-text">
    {_p('cf_av_jazkarta', 'Please note that the experiment is being conducted with the help of Jazkarta (https://jazkarta.com/), a company not affiliated with Cornell and with its own privacy and security policies. If technical issues arise, the Jazkarta employee working on the project may need temporary access to research data in order to debug the experiments.')}
  </p>

  <h4>{_p('cf_av_collab', 'Research collaborations')}</h4>
  <p class="consent-text">
    {_p('cf_av_collab_body', 'To support scientific progress and replication, we may share de-identified data with other researchers. If your recordings are included, they will only be shared together with anonymized or extracted data (for example, acoustic or motion features). Your name or contact information will never be linked to these recordings. However, people who know you personally might still recognize your voice or appearance.')}
  </p>

  <h4>{_p('cf_av_security', 'Data security')}</h4>
  <p class="consent-text">
    {_p('cf_av_security_body', 'All audio-visual materials will be stored securely on separate servers, protected by strong encryption, and linked only to a random participant code (e.g., "afa12314aasd"). Personal information, if collected, will be stored separately and securely from all recordings. Access to both datasets will be limited to authorized members of the research team.')}
  </p>

  <h4>{_p('cf_av_your_consent', 'Your consent')}</h4>
  <p class="consent-text">
    {_p('cf_av_consent_body', 'By agreeing below, you confirm that you are 18 years or older, have read and understood the information above, and agree to the collection and use of your audio-visual recordings for research purposes as described.')}
    {_p('cf_av_withdraw', 'You can withdraw your consent for recording at any time before data analysis by contacting the research team.')}
  </p>

</div>
"""))
    if include_ai_consent:
        content += str(Markup(f"""
<div class="text-left" style="font-size:18px;margin-top:1rem">
  <p class="consent-text">
    <strong>{_p('cf_av_ai_optional', 'Optional — AI model data sharing:')}</strong>
    {_p('cf_av_ai_agree', 'I agree to allow the experiment to send my data to, or let me interact with, AI model(s) including: ChatGPT, Claude, Gemini, Llama, Mistral, DeepSeek and other AI models which might be used in this study. I understand that the AI provider may process or further use my data according to their own terms of service.')}
  </p>
</div>
"""))
    return content


# =============================================================================
# Regional addenda
# =============================================================================

def _database_addendum_content(region: AddendumRegion) -> str:
    titles = {
        "europe": _p("cf_database_addendum_gdpr_title", "Supplemental Privacy Notice — General Data Protection Regulation (GDPR)"),
        "korea": _p("cf_database_addendum_kpipa_title", "Supplemental Privacy Notice — Personal Information Protection Act (PIPA), South Korea"),
        "singapore_taiwan": _p("cf_database_addendum_sg_tw_title", "Supplemental Privacy Notice — Personal Data Protection Act (PDPA), Singapore/Taiwan"),
    }
    bodies = {
        "europe": _p("cf_database_addendum_gdpr_body", """
<p class="consent-text">This notice covers the Lab-Recruiter database used for the cultural foundation project. The database stores contact details such as name and email, basic demographic information entered during registration, email verification timestamps, study invitations, study acceptance and completion status, and payment amounts.</p>
<p class="consent-text">Cornell and the Principal Investigator are responsible for this processing. Data are used to determine eligibility, invite participation, carry out studies that you separately consent to, monitor compliance, make required reports, and support future studies. Jazkarta may need limited technical access when debugging the recruitment system.</p>
<p class="consent-text">Your information is encrypted in transit, stored on a secure internal server, and accessible only to authorized personnel. Your data may be retained for as long as needed to contact you about studies, but you may request deletion or delete your Lab-Recruiter account. Payment may require using your email with external payment systems such as Wise or PayPal.</p>
<p class="consent-text">You may request access, correction, transfer, or deletion of your identifiable information, though some requests may be delayed or limited when needed to protect research integrity. To exercise rights, contact Nori Jacoby at kj338@cornell.edu or Cornell's Data Protection Officer at privacy-requests@cornell.edu.</p>
"""),
        "korea": _p("cf_database_addendum_kpipa_body", """
<p class="consent-text">This notice covers personal information used for the Lab-Recruiter database, including name, email, demographic registration information, verification timestamps, study invitations, study participation status, and payment records.</p>
<p class="consent-text">Cornell must have a lawful basis for collecting and processing this information, and explicit consent is required before personal or sensitive information is transferred overseas. The database may use external payment services such as Wise or PayPal when needed to compensate participants.</p>
<p class="consent-text">You have rights to be informed, request access and correction, seek redress, and request that your information no longer be used, subject to restrictions that can apply in academic research. Information that must be retained beyond a retention period will be stored and managed separately.</p>
<p class="consent-text">To exercise rights, contact Nori Jacoby at kj338@cornell.edu or Cornell's Data Protection Officer at privacy-requests@cornell.edu.</p>
"""),
        "singapore_taiwan": _p("cf_database_addendum_sg_tw_body", """
<p class="consent-text">This notice covers the main study and database contexts. For database enrollment, Cornell may collect account and contact information such as name, email, registration details, study invitations, participation status, and payment-related records.</p>
<p class="consent-text">The information is used to manage eligibility, invitations, study participation, records, and payments. Cornell is located in the United States, so data may be processed outside your home country, where protections may differ.</p>
<p class="consent-text">You may request access, correction, transfer, or deletion of your information, subject to limits needed to complete or preserve research. Contact the Principal Investigator or Cornell's Data Protection Officer with questions or complaints.</p>
"""),
    }
    return f"""
<hr>
<div class="text-left" style="font-size:18px;border-left:4px solid #0066cc;padding-left:1rem;margin-top:1rem">
  <h4>{titles[region]}</h4>
  <p class="consent-text" style="font-size:smaller">IRB Protocol: &ldquo;{STUDY_TITLE}.&rdquo; {IRB_PROTOCOL_NUMBER}</p>
  {bodies[region]}
</div>
"""


def _addendum_content(region: AddendumRegion, consent_type: str = "MAIN") -> str:
    if consent_type == "DATABASE":
        return _database_addendum_content(region)

    titles = {
        "europe": _p("cf_addendum_gdpr_title", "Supplemental Privacy Notice — General Data Protection Regulation (GDPR)"),
        "korea": _p("cf_addendum_kpipa_title", "Supplemental Privacy Notice — Personal Information Protection Act (PIPA), South Korea"),
        "singapore_taiwan": _p("cf_addendum_sg_tw_title", "Supplemental Privacy Notice — Personal Data Protection Act (PDPA), Singapore/Taiwan"),
    }
    bodies = {
        "europe": _p("cf_addendum_gdpr_body", """
<p class="consent-text">This research study will collect personally identifiable information about you. Cornell University and the Principal Investigator are jointly responsible for the conduct of this research study. Cornell University will act as the data controller. Cornell will keep identifiable information about you for 5 years after the study has finished.</p>
<p class="consent-text">Your participation is voluntary. By consenting, you also agree to allow Cornell to use your personal information as described in this notice.</p>
<h4>What Personal Information and How Will You Use It?</h4>
<p class="consent-text">When you participate, we obtain: a participant ID (alphanumeric code) from the recruitment service. We do not collect personal details. If you type something that reveals who you are, that text could be stored. Your real name and personal identifiers will never be shared. In some cases, your responses may be analyzed by AI systems (e.g., ChatGPT, Gemini, Claude). If an experiment includes audio or video recordings, these will be stored securely and handled as potentially identifiable data. We may share de-identified data to support open science.</p>
<p class="consent-text">Your data may be used for: determining eligibility, inviting participation, carrying out the study, confirming accuracy, monitoring compliance, making required reports to regulatory agencies, and conducting future studies.</p>
<h4>What Rights Do I Have?</h4>
<p class="consent-text">You have: the right to request access and correction; the right to request a copy in electronic format or direct transfer to third parties; the right to request that your information no longer be used. Note: requests may not occur until completion of the research to protect integrity.</p>
<h4>Will My Data Be Processed Outside Of My Home Country?</h4>
<p class="consent-text">Cornell University is located in the United States. Your information will be transmitted to Cornell researchers in the US. Data protection laws in the US may not be as strong as where you reside.</p>
<p class="consent-text">To exercise rights: contact the Principal Investigator at kj338@cornell.edu or Cornell Data Protection Officer at internationalprivacyrequests@cornell.edu. For complaints: Cornell Data Protection Officer c/o University Privacy, 395 Pine Tree Road, Suite 330, Ithaca, NY 14850, (607)255-2800, privacy-requests@cornell.edu. You may also complain to your local data protection authority.</p>
<p class="consent-text">By signing below, you consent to the collection of this information. Your consent may be freely withdrawn at any time.</p>
"""),
        "korea": _p("cf_addendum_kpipa_body", """
<p class="consent-text">This research study will collect personally identifiable information about you. Cornell University and the Principal Investigator are jointly responsible. Cornell will act as the data controller. Cornell will keep identifiable information about you for 5 years.</p>
<p class="consent-text">Pursuant to the Personal Information Protection Act (PIPA) of the Republic of Korea, Cornell must have a lawful basis for collecting your personal information. Your explicit, affirmative consent is required before your personal information (including sensitive information) may be transmitted overseas. The sensitive information collected is audiovisual interactions.</p>
<h4>What Rights Do I Have?</h4>
<p class="consent-text">You have: the right to be informed; the right to request access (including copies) and correction; the right to appropriate redress; the right to request that your information no longer be used. Note: requests may not occur until completion of the research.</p>
<h4>Will My Data Be Processed Outside Of My Home Country?</h4>
<p class="consent-text">Cornell University is located in the United States. Your information will be transmitted to Cornell researchers in the US. Data protection laws in the US may not be as strong as where you reside. Your data may be processed using AI tools. Any system used will be compliant with PIPA requirements.</p>
<p class="consent-text">To exercise rights: contact the Principal Investigator at kj338@cornell.edu or Cornell Data Protection Officer at internationalprivacyrequests@cornell.edu. For complaints: Cornell Data Protection Officer c/o University Privacy, 395 Pine Tree Road, Suite 330, Ithaca, NY 14850, (607)255-2800, privacy-requests@cornell.edu.</p>
<p class="consent-text">By signing below, you consent to the collection and transfer of your personal and sensitive information as described. You may withdraw consent at any time.</p>
"""),
        "singapore_taiwan": _p("cf_addendum_sg_tw_body", """
<p class="consent-text">This research study will collect personally identifiable information about you. Cornell University and the Principal Investigator are jointly responsible. Cornell will act as the data controller. Cornell will keep identifiable information until completion of this research project.</p>
<p class="consent-text">When you participate, we may obtain: your textual responses, mouse movement, mouse clicks, and interaction with the experiment. Some parts may require audio or video recordings; we will ask for specific additional consent in those cases. Your data may be used for: determining eligibility, inviting participation, carrying out the study, confirming accuracy, monitoring compliance, making required reports, and conducting future studies. Cornell uses encrypted storage and pseudoanonymization.</p>
<h4>What Rights Do I Have?</h4>
<p class="consent-text">You have: the right to request access and correction; the right to request a copy in electronic format or direct transfer; the right to request that your information no longer be used. Note: requests may not occur until completion of the research.</p>
<h4>Will My Data Be Processed Outside Of My Home Country?</h4>
<p class="consent-text">Cornell University is located in the United States. Your information will be transmitted to Cornell researchers in the US. Data protection laws in the US may not be as strong as where you reside.</p>
<p class="consent-text">To exercise rights: contact the Principal Investigator at kj338@cornell.edu. For complaints: Cornell Data Protection Officer c/o University Privacy, 395 Pine Tree Road, Suite 330, Ithaca, NY 14850, (607)255-2800, privacy-requests@cornell.edu.</p>
"""),
    }
    return f"""
<hr>
<div class="text-left" style="font-size:18px;border-left:4px solid #0066cc;padding-left:1rem;margin-top:1rem">
  <h4>{titles[region]}</h4>
  <p class="consent-text" style="font-size:smaller">IRB Protocol: &ldquo;{STUDY_TITLE}.&rdquo; {IRB_PROTOCOL_NUMBER}</p>
  {bodies[region]}
</div>
"""


# =============================================================================
# Incentives paragraphs (substituted per consent type)
# =============================================================================

_INCENTIVES_MAIN = _p("cf_incentives_main_body", """
<p class="consent-text">
  We will compensate you at a rate of approximately $10 per hour. {DURATION_PAYMENT_TEXT} Compensation will be processed through the recruitment service (e.g., Prolific), and we will share your alphanumeric participant ID, completion status, session timing, and details of compensation and bonus payments with them. You may also be eligible for a performance-based bonus. The maximal amount of bonus will be 200% of the overall payment and will only supplement, not replace, your hourly payment rate.
</p>
""")

_INCENTIVES_CINT = _p("cf_incentives_cint_body", """
<p class="consent-text">
  If you satisfactorily complete the study, you will be compensated by your panel provider. {DURATION_PAYMENT_TEXT} Compensation will be processed through the recruitment service (e.g., CINT), and we will share your alphanumeric participant ID, completion status, session timing, and details of compensation and bonus payments with them. You may also be eligible for a performance-based bonus. If bonus opportunities are available, you will be notified during the experiment.
</p>
""")

_CINT_CONTEXT_NOTE = _p("cf_cint_context", """
<div style="background:#f8f9fa;padding:1rem;margin-bottom:1rem;font-size:smaller;border-left:4px solid #999">
  <p class="consent-text"><strong>Note:</strong> For marketplace recruitment services (e.g., Cint), direct payment to participants may not be possible. In such cases, compensation is managed and distributed through the participant's original panel provider. We strive to ensure that payment remains proportional to the official hourly rate of the participant's country, although the exact amount and method of payment are determined by the panel provider. A separate consent form is provided for this use case.</p>
</div>
""")


# =============================================================================
# Consent template builders
# Returns full HTML string matching PsyNet consent template structure
# =============================================================================

def _duration_payment_text(
    consent_type: str,
    DURATION: Optional[int],
    PAYMENT: Optional[float],
    show_duration_payment: bool,
) -> str:
    if consent_type == "CINT":
        PAYMENT = 0
    if consent_type == "DATABASE" or not show_duration_payment:
        return ""
    DURATION, PAYMENT = _resolve_duration_payment(DURATION, PAYMENT)

    if consent_type == "MAIN":
        return _p(
            "cf_consent_main",
            "The estimated duration of the experiment is <strong>{DURATION}</strong> minutes, "
            "with an expected payment of <strong>{PAYMENT}</strong> USD."
        ).format(DURATION=DURATION, PAYMENT=PAYMENT)

    return _p(
        "cf_duration_payment_cint",
        "The estimated duration of the experiment is <strong>{DURATION}</strong> "
        "minutes, with an expected payment compliant with the minimum hourly wage "
        "in the country is expected."
    ).format(DURATION=DURATION)

def _build_database_consent_html(
    EMAIL: str,
    IRB: str,
    PHONE: str,
    IRB_PHONE: str,
    IRB_URL: str,
    ETHICS_URL: str,
    ETHICS_PHONE: str,
) -> str:
    html = f"""
  <h1>{_p('cf_database_heading', 'Database consent')}</h1>
  <hr>
  <div class="text-justify">
    <div class="text-left" style="font-size:18px">

      <p class="consent-text">
        {_p('cf_database_context', 'Lab-Recruiter is a Cornell server used to recruit participants for Jacoby Lab studies. The database lets people join a participant pool and then choose from available experiments, each with its own separate study consent. The database also helps administrators record completed payments so participants can review them. Payments are issued externally through services such as Wise; the database does not process payments itself.')}
      </p>

      <h4>{_p('cf_database_overview_title', 'Database consent')}</h4>
      <p class="consent-text">
        {_p('cf_database_overview_body', 'Jacoby’s Lab invites you to register in a participant database for studies associated with “The Cultural Foundation of Perception and Cognition – Online Experiments.” The project is led by Dr. Nori Jacoby in the Department of Psychology at Cornell University.')}
      </p>

      <h4>{_p('cf_database_purpose_title', 'What the database is about')}</h4>
      <p class="consent-text">
        {_p('cf_database_purpose_body', 'Human thinking and perception are shaped by biology and culture. By joining this database, you may gain access to a variety of studies related to this research area. Each study will provide its own separate consent before participation.')}
      </p>

      <h4>{_p('cf_database_procedure_title', 'What we will ask you to do')}</h4>
      <p class="consent-text">
        {_p('cf_database_procedure_body', 'If you agree, you will create an account, provide basic demographic information, access a list of available studies, and choose whether to participate in additional studies. The system will also track completed studies and support payment records for compensated work.')}
      </p>

      <h4>{_p('cf_database_risks_title', 'Risks and discomforts')}</h4>
      <p class="consent-text">
        {_p('cf_database_risks_body', 'Joining the database involves minimal risk similar to ordinary computer use. We store your name and email because they are needed for communication and compensation. As with any computer system, there is some risk of unauthorized access or a data breach.')}
      </p>

      <h4>{_p('cf_database_benefits_title', 'Benefits')}</h4>
      <p class="consent-text">
        {_p('cf_database_benefits_body', 'There are no direct personal benefits to joining the database. Your participation may contribute to scientific knowledge about human perception and cognition.')}
      </p>

      <h4>{_p('cf_database_incentives_title', 'Incentives for participation')}</h4>
      <p class="consent-text">
        {_p('cf_database_incentives_body', 'Joining the database is voluntary and not compensated. Some future studies may be compensated under their own separate consent forms. We do not store bank account or financial information. Payment records and amounts may be stored for completed tasks, and payments are issued through external services such as Wise. If you cannot or prefer not to use those services, you may still participate voluntarily, but we may not be able to provide compensation.')}
      </p>

      <h4>{_p('cf_database_privacy_title', 'Privacy / Confidentiality / Data Security')}</h4>
      <p class="consent-text">
        {_p('cf_database_privacy_body1', 'To communicate with you and support payments, we keep your name and email address in the database. We also store demographic registration information, registration and verification timestamps, study invitations, study acceptance and completion status, and payment amounts associated with completed participation.')}
        {_p('cf_database_privacy_body2', 'Your data are stored and processed for communicating with you, planning future research studies, and recording study participation and payments. Your information will not be shared with third parties for unrelated purposes. Jazkarta may have limited technical access if needed to debug the system.')}
        {_p('cf_database_privacy_body3', 'Data entered into the system are encrypted in transit and stored in a secure, non-public environment. You may request deletion of your data or delete your account through Lab-Recruiter; deleting your account permanently removes your stored data, including participation and payment history.')}
      </p>

      <h4>{_p('cf_database_voluntary_title', 'Taking part is voluntary')}</h4>
      <p class="consent-text">
        {_p('cf_database_voluntary_body', 'Participation is entirely voluntary. You may withdraw at any time by deleting your account through the Lab-Recruiter interface.')}
      </p>

      <h4>{_p('cf_database_followup_title', 'Follow up studies')}</h4>
      <p class="consent-text">
        {_p('cf_database_followup_body', 'We may contact you in the future to invite you to participate in follow-up studies. Participation in any such study will always be voluntary and will require separate consent.')}
      </p>

      <h4>{_p('cf_database_contact_title', 'If you have questions')}</h4>
      <p class="consent-text">
        {_p('cf_database_contact_body', 'The main researcher conducting this study is Nori Jacoby, an assistant professor in the Psychology department at Cornell University. If you have questions later, you may contact Nori at {EMAIL} or at {PHONE}. If you have questions or concerns regarding your rights as a subject, you may contact the {IRB} for Human Participants at {IRB_PHONE} or visit <a href="{IRB_URL}" target="_blank">{IRB_URL}</a>. You may also report concerns or complaints anonymously through Ethicspoint online at <a href="https://{ETHICS_URL}" target="_blank">{ETHICS_URL}</a> or by calling toll-free at {ETHICS_PHONE}.')}
      </p>

      <h4>{_p('cf_database_statement_title', 'Statement of Consent')}</h4>
      <p class="consent-text">
        {_p('cf_database_statement_body', 'I have read the above information, and have received answers to any questions I asked. I consent to join the database. By choosing to consent electronically I confirm my consent to join the database.')}
      </p>

    </div>
  </div>
"""
    return html.format(
        EMAIL=EMAIL,
        IRB=IRB,
        PHONE=PHONE,
        IRB_PHONE=IRB_PHONE,
        IRB_URL=IRB_URL,
        ETHICS_URL=ETHICS_URL,
        ETHICS_PHONE=ETHICS_PHONE,
    )


def _build_consent_html(
    consent_type: str,
    DURATION: Optional[int],
    PAYMENT: Optional[float],
    show_duration_payment: bool,
    EMAIL: str,
    IRB: str,
    PHONE: str,
    IRB_PHONE: str,
    IRB_URL: str,
    ETHICS_URL: str,
    ETHICS_PHONE: str,
) -> str:
    if consent_type == "DATABASE":
        return _build_database_consent_html(
            EMAIL=EMAIL,
            IRB=IRB,
            PHONE=PHONE,
            IRB_PHONE=IRB_PHONE,
            IRB_URL=IRB_URL,
            ETHICS_URL=ETHICS_URL,
            ETHICS_PHONE=ETHICS_PHONE,
        )

    duration_payment_text = _duration_payment_text(
        consent_type,
        DURATION,
        PAYMENT,
        show_duration_payment,
    )
    if consent_type == "MAIN":
        heading = _p('cf_page_heading', 'We need your consent to proceed')
        incentives = str(_INCENTIVES_MAIN).replace("{DURATION_PAYMENT_TEXT}", duration_payment_text)
        cint_note = ""
        overview_body = _p('cf_overview_body', 'Jacoby\'s lab is inviting you to take part in a research study called \u201cThe cultural foundation of perception and cognition \u2013 online experiments.\u201d We\u2019ll explain the study to you and are happy to answer any questions you have. The study is led by Nori Jacoby from the Psychology Department at Cornell University.')
        purpose_body1 = _p('cf_purpose_body1', 'Human thinking and perception are influenced by both our biology and the cultures we grow up in. To understand how these two factors work together, we need to study people from many different backgrounds \u2014 not just from Western, educated, industrialized, rich, and democratic (WEIRD) societies, where most psychology and neuroscience research has been done.')
        purpose_body2 = _p('cf_purpose_body2', 'In this experiment, you will complete simple tasks and answer a few questions. Sometimes you will interact only with the computer, and other times you may interact with other people. We will use your responses to compare how people from different cultures, countries, and languages perceive and think.')
        procedure_body1 = _p('cf_procedure_body1', 'First, you\u2019ll sign an online consent form and answer a few simple questions about yourself. Next, you\u2019ll complete a brief survey, experiment, or small computer game. While playing, you may share information with other players. Some sessions also include quick puzzles that test skills like language, perception, or math.')
        procedure_body2 = _p('cf_procedure_body2', 'In some experiments, we may use mild deception, meaning that we might not fully describe the purpose of a task until after it is completed. Such mild deception will only be used when necessary to prevent biasing participants and will be fully explained to you during debriefing at the end of the experiment.')
        procedure_body3 = _p('cf_procedure_body3', 'In certain studies, we may also ask participants to make audio or video recordings (for example, recording your voice, facial expressions, or finger-tapping movements). If your session includes audio or video recording, we will ask for additional, explicit consent before you proceed. You will always have the right to refuse these recordings and still participate in parts of the study that do not require them.')
    else:
        heading = _p('cf_page_heading_cint', 'Online consent [indirect payment]')
        incentives = str(_INCENTIVES_CINT).replace("{DURATION_PAYMENT_TEXT}", duration_payment_text)
        cint_note = str(_CINT_CONTEXT_NOTE)
        overview_body = _p('cf_overview_body_cint', 'This online study is run by the Department of Psychology at Cornell University in collaboration with researchers from Princeton University, New York University, and Boston University, with support from the Defense Advanced Research Projects Agency.')
        purpose_body1 = _p('cf_purpose_body1_cint', 'This study aims to understand the conditions under which people trust artificial intelligence (AI).')
        purpose_body2 = _p('cf_purpose_body2_cint', 'During the experiment, you will make judgments and answer a small number of questions. Sometimes you will interact only with a computer; at other times you may observe or interact with AI agents or other human participants. You may also be asked to explain or justify your responses.')
        procedure_body1 = _p('cf_procedure_body1_cint', 'First, you will review and sign an online consent form and answer a few basic questions about yourself. Next, you will complete a short survey, experiment, or computer-based task or game.')
        procedure_body2 = _p('cf_procedure_body2_cint', 'During the experiment, you may be asked to make judgments or observe others, including humans or AI agents, making decisions. We may ask you to explain or justify some of your choices.')
        procedure_body3 = _p('cf_procedure_body3_cint', 'Some sessions may include mild deception or audio/video recording. If a session includes recordings, we will ask for additional explicit consent before collecting those data.')

    html = f"""
  <h1>{heading}</h1>
  <hr>
  {cint_note}
  <div class="text-justify">
    <div class="text-left" style="font-size:18px">

      <h4>{_p('cf_overview_title', 'Online consent')}</h4>
      <p class="consent-text">
        {overview_body}
      </p>

      <h4>{_p('cf_purpose_title', 'What the study is about')}</h4>
      <p class="consent-text">
        {purpose_body1}
        {purpose_body2}
      </p>

      <h4>{_p('cf_procedure_title', 'What we will ask you to do')}</h4>
      <p class="consent-text">
        {procedure_body1}
        {procedure_body2}
        {procedure_body3}
      </p>

      <h4>{_p('cf_risks_title', 'Risks and discomforts')}</h4>
      <p class="consent-text">
        {_p('cf_risks_body', 'These experiments are behavioral and involve minimal risk, with no risks beyond those associated with normal computer use. We will not present any triggering, profane, or controversial content. The experiments are unlikely to cause any emotional distress, such as sadness or anxiety; however, some participants may find them boring. We make every effort to ensure the experiments are as engaging as possible.')}
      </p>

      <h4>{_p('cf_benefits_title', 'Benefits')}</h4>
      <p class="consent-text">
        {_p('cf_benefits_body', 'There are no direct benefits to participating in the experiment, aside from contributing to scientific knowledge. The information gathered from this study may help others now or in the future by helping us understand the human mind. By participating, you also help advance the overall understanding of perception and cognition.')}
      </p>

      <h4>{_p('cf_incentives_title', 'Incentives for participation')}</h4>
      {incentives}

      <h4>{_p('cf_ai_title', 'AI in the experiment and analysis')}</h4>
      <p class="consent-text">
        {_p('cf_ai_body1', 'Please note that in some experiments, your data may be shared with industry-based large language models (LLMs) or artificial intelligence (AI) agents. In such cases, only the information you provide or receive during the interaction will be shared \u2014 your recruiter identity will not be disclosed.')}
        {_p('cf_ai_body2', 'Data may also be shared with AI agents (e.g., ChatGPT, Claude, Gemini, Llama, Mistral, or Grok), but it will not reveal your identity unless you disclose personal information yourself. Your response may also be analyzed after the experiment using AI systems, including models other than the one you originally interacted with.')}
      </p>

      <h4>{_p('cf_privacy_title', 'Privacy / Confidentiality / Data Security')}</h4>
      <p class="consent-text">
        {_p('cf_privacy_body1', 'During the study, we will only know you by a participant ID made of alphanumeric code. We do not collect your personal details \u2014 just this code from the recruitment service (e.g., Prolific). If you choose to type something that reveals who you are, such as your real name, that text could be stored and seen by others, but providing such information is never required and is strongly discouraged.')}
        {_p('cf_privacy_body2', 'If an experiment includes audio or video recordings, these files will be stored securely and will only be used for research purposes described in this consent form. Any such recordings will be handled as potentially identifiable data, kept separate from your anonymous responses, and will never be shared publicly without being fully de-identified.')}
        {_p('cf_privacy_body3', 'We may share the study data with other researchers or make it public to support open science, but we will keep it de-identified so no one can link the data back to you. We also protect all data with strong security measures, including secure servers, encryption, and restricted access. Data are temporarily stored on password-protected devices/servers and will be moved to Cornell servers for permanent storage.')}
        {_p('cf_privacy_body4', 'We will do our best to keep your participation in this research study confidential to the extent permitted by law. Please note that the experiment is being conducted with the help of Jazkarta (https://jazkarta.com/), a company not affiliated with Cornell and with its own privacy and security policies. If technical issues arise, the Jazkarta employee working on the project may need temporary access to research data. In addition, the following people/groups may check and copy records about this research: the Office for Human Research Protections; the National Science Foundation; and Cornell University\u2019s Institutional Review Board and Office for Research Integrity and Assurance.')}
        {_p('cf_privacy_body5', 'Please note that the experiment is conducted with the help of a recruiter such as Prolific, Amazon Mechanical Turk, CINT or Qualtrics \u2014 a company not affiliated with Cornell and with its own privacy and security policies. Please note that email communication is neither private nor secure. We cannot guarantee against interception of data sent via the internet by third parties.')}
      </p>

      <h4>{_p('cf_sharing_title', 'Sharing De-identified Data Collected in this Research')}</h4>
      <p class="consent-text">
        {_p('cf_sharing_body', 'De-identified data from this study may be shared with the research community at large to advance science and health. We will remove or code any personal information that could identify you before files are shared with other researchers to ensure that, by current scientific standards and known methods, no one will be able to identify you from the information we share.')}
      </p>

      <h4>{_p('cf_voluntary_title', 'Taking part is voluntary')}</h4>
      <p class="consent-text">
        {_p('cf_voluntary_body1', 'Participation is completely voluntary. You can choose to stop participating at any time by simply closing the experiment window and ending the session. Before you participate, you must meet the following conditions:')}
      </p>
      <p class="consent-text">
        {_p('cf_voluntary_conditions', 'a) You are over 18 years old. &nbsp; b) You speak the language specified in the advertisement. &nbsp; c) You meet the technical requirements, such as having a microphone and the correct browser version as specified in the advertisement.')}
      </p>
      <p class="consent-text">
        {_p('cf_voluntary_body2', 'At the start of the session, we may check for compliance with these conditions. If you do not meet them, your session will be terminated; however, you will still be compensated at the same hourly rate for participating in this initial test. The length of each experiment may vary, but compensation will remain proportional to the amount of work and/or session duration. If you choose to withdraw early, you may not receive compensation or receive partial compensation. The research team reserves the right to withdraw your participation or terminate your session if circumstances arise that justify doing so. Please provide your consent only if you agree with these terms.')}
      </p>

      <h4>{_p('cf_followup_title', 'Follow up studies')}</h4>
      <p class="consent-text">
        {_p('cf_followup_body', 'We may contact you again to request your participation in a follow up study. As always, your participation will be voluntary and we will ask for your explicit consent to participate in any of the follow up studies.')}
      </p>

      <h4>{_p('cf_contact_title', 'Contact information')}</h4>
      <p class="consent-text">
        {_p('cf_contact_body', 'The main researcher conducting this study is Nori Jacoby, an assistant professor in the Psychology department at Cornell University. Please ask any questions you have now. If you have questions later, you may contact Nori at {EMAIL} or at {PHONE}. If you have any questions or concerns regarding your rights as a subject in this study, you may contact the {IRB} for Human Participants at {IRB_PHONE} or access their website at <a href="{IRB_URL}" target="_blank">{IRB_URL}</a>. You may also report your concerns or complaints anonymously through <strong>Ethicspoint</strong> online at <a href="https://{ETHICS_URL}" target="_blank">{ETHICS_URL}</a> or by calling toll-free at {ETHICS_PHONE}. Ethicspoint is an independent organization that serves as a liaison between the University and the person bringing the complaint so that anonymity can be ensured.')}
      </p>

      <h4>{_p('cf_statement_title', 'Statement of Consent')}</h4>
      <p class="consent-text">
        {_p('cf_statement_body', 'I have read the above information, and have received answers to any questions I asked. I consent to take part in the study. By choosing to consent electronically I confirm my consent to this study.')}
      </p>

    </div>
  </div>
"""
    return html.format(
        EMAIL=EMAIL,
        IRB=IRB,
        PHONE=PHONE,
        IRB_PHONE=IRB_PHONE,
        IRB_URL=IRB_URL,
        ETHICS_URL=ETHICS_URL,
        ETHICS_PHONE=ETHICS_PHONE,
    )


# =============================================================================
# consent_irb_cultural_foundation — Module + Consent
# =============================================================================

_CONSENT_TEMPLATE = (
    '{% extends "timeline-page.html" %}'
    '\n{% block stylesheets %}'
    '\n    <link rel="stylesheet" href="/static/css/consent.css"/>'
    '\n{% endblock %}'
    '\n{% block reward %}{% endblock %}'
    '\n{% block main_body %}'
    '\n<div class="main-div" style="padding-bottom:200px">'
    '\n{{ consent_html | safe }}'
    '\n</div>'
    '\n{{ consent.fixed_buttons(config) }}'
    '\n{% endblock %}'
)


def _make_consent_page(label: str, html: str, time_estimate: int):
    """Return a single ConsentPage (Page + Consent) for the given HTML block."""
    class ConsentPage(Page, Consent):
        def format_answer(self, raw_answer, **kwargs):
            return {label: raw_answer}

        def get_bot_response(self, experiment, bot):
            return {label: True}

    return ConsentPage(
        label=label,
        template_str=_CONSENT_TEMPLATE,
        template_arg={"consent_html": html},
        time_estimate=time_estimate,
        # Extends timeline-page.html and injects consent.css; not SPA-safe.
        requires_full_page_reload=True,
    )


class consent_irb_cultural_foundation(Module, Consent):
    """
    Cornell IRB0150361 consent form, "The cultural foundation of perception and
    cognition – online experiments" (Jacoby lab).

    Produces separate consent pages (each with a fixed "I agree" bar at the
    bottom) when audiovisual=True, mirroring the old MainConsent + AudiovisualConsent
    two-step flow:

      Page 1 — main, CINT, or database IRB consent text
      Page 2 — audio-visual recording consent  (only when audiovisual=True)

    Parameters
    ----------
    consent : "MAIN" | "CINT" | "DATABASE"
        MAIN for direct recruitment (Prolific, Lab Recruiter, etc.);
        CINT for CINT panel where payment is indirect;
        DATABASE for Lab-Recruiter database enrollment.
    audiovisual : bool
        Show a second page with the Audio-Visual consent.
    addendum_regions : list or None
        Any of ["europe"], ["korea"], ["singapore_taiwan"] (or combinations)
        to append the relevant regional privacy addendum to the main page.
    DURATION : int, optional
        Estimated duration in minutes for MAIN/CINT. If omitted, read from
        ``prolific_estimated_completion_minutes`` in config.txt.
    PAYMENT : float, optional
        Expected payment in USD for MAIN/CINT. If omitted, read from
        ``base_payment`` in config.txt.
    show_duration_payment : bool
        Show or hide the participant-facing duration/payment sentence.
    include_ai_consent : bool
        When audiovisual=True, also render the optional AI-model data-sharing
        paragraph on the AV page.
    """
    time_estimate = 60

    def __init__(
        self,
        consent: ConsentType = "MAIN",
        audiovisual: bool = False,
        addendum_regions: Optional[List[AddendumRegion]] = None,
        DURATION: Optional[int] = None,
        PAYMENT: Optional[float] = None,
        show_duration_payment: bool = True,
        include_ai_consent: bool = False,
        EMAIL: str = "kj338@cornell.edu",
        PHONE: str = "+1-607-255-3834",
        IRB_PHONE: str = "607-255-6182",
        IRB_URL: str = "https://researchservices.cornell.edu/offices/IRB",
        ETHICS_URL: str = "www.hotline.cornell.edu",
        ETHICS_PHONE: str = "1-866-293-3077",
        **kwargs,
    ):
        consent = consent.upper() if isinstance(consent, str) else consent
        if consent not in ("MAIN", "CINT", "DATABASE"):
            raise ValueError("consent must be 'MAIN', 'CINT', or 'DATABASE'")
        if consent == "DATABASE" and audiovisual:
            raise ValueError("audiovisual consent is not available for consent='DATABASE'")

        # ── Page 1: main consent ──────────────────────────────────────────────
        main_html = _build_consent_html(
            consent_type=consent,
            DURATION=DURATION,
            PAYMENT=PAYMENT,
            show_duration_payment=show_duration_payment,
            EMAIL=EMAIL,
            IRB="Institutional Review Board (IRB)",
            PHONE=PHONE,
            IRB_PHONE=IRB_PHONE,
            IRB_URL=IRB_URL,
            ETHICS_URL=ETHICS_URL,
            ETHICS_PHONE=ETHICS_PHONE,
        )
        if addendum_regions:
            for r in addendum_regions:
                main_html += _addendum_content(r, consent_type=consent)

        main_label = "cf_database_consent" if consent == "DATABASE" else "cf_main_consent"
        main_page = _make_consent_page(main_label, main_html, self.time_estimate)

        failure_tag = "irb_cultural_foundation_consent_rejected"

        elts = [
            main_page,
            conditional(
                "cf_main_consent_conditional",
                lambda experiment, participant: (
                    not participant.answer.get(main_label, True)
                ),
                RejectedConsentPage(failure_tags=[failure_tag]),
            ),
            CodeBlock(lambda participant: participant.var.set(
                (
                    "irb_cultural_foundation_database_consent"
                    if consent == "DATABASE"
                    else "irb_cultural_foundation_main_consent"
                ),
                participant.answer
            )),
        ]

        # ── Page 2: audio-visual consent (separate page, own "I agree") ──────
        if audiovisual:
            av_html = _audiovisual_content(include_ai_consent=include_ai_consent)
            av_page = _make_consent_page("cf_av_consent", av_html, self.time_estimate)

            elts += [
                av_page,
                conditional(
                    "cf_av_consent_conditional",
                    lambda experiment, participant: (
                        not participant.answer.get("cf_av_consent", True)
                    ),
                    RejectedConsentPage(failure_tags=[failure_tag]),
                ),
                CodeBlock(lambda participant: participant.var.set(
                    "irb_cultural_foundation_av_consent", participant.answer
                )),
            ]

        super().__init__("consent_irb_cultural_foundation", join(*elts), **kwargs)


# =============================================================================
# Debrief page
# =============================================================================

def _debrief_content(
    EMAIL: str = "kj338@cornell.edu",
    PHONE: str = "+1-607-255-3834",
    IRB_PHONE: str = "607-255-6182",
    IRB_URL: str = "https://researchservices.cornell.edu/offices/IRB",
    ETHICS_URL: str = "www.hotline.cornell.edu",
    ETHICS_PHONE: str = "1-866-293-3077",
) -> Markup:
    contact_body = _p(
        "cf_debrief_contact_body",
        "The main researcher conducting this study is Nori Jacoby. Please ask any questions you have now. "
        "If you have questions later, you may contact Nori at {EMAIL} or at {PHONE}. "
        "If you have any questions or concerns regarding your rights as a subject in this study, you may "
        "contact the IRB for Human Participants at {IRB_PHONE} or access their website at {IRB_URL}. "
        "You may also report your concerns anonymously through Ethicspoint online at {ETHICS_URL} or "
        "by calling toll free at {ETHICS_PHONE}.",
    ).format(
        EMAIL=EMAIL,
        PHONE=PHONE,
        IRB_PHONE=IRB_PHONE,
        IRB_URL=f'<a href="{IRB_URL}" target="_blank">{IRB_URL}</a>',
        ETHICS_URL=f'<a href="https://{ETHICS_URL}" target="_blank">{ETHICS_URL}</a>',
        ETHICS_PHONE=ETHICS_PHONE,
    )
    return Markup(f"""
<div class="main-div">
  <h1>{_p('cf_debrief_heading', 'Thank you for participating!')}</h1>
  <hr>
  <div class="text-justify">
    <div class="text-left" style="font-size:18px">

      <p class="consent-text">
        {_p('cf_debrief_intro', 'Dear Participant, Thank you so much for helping us with our experiment! Your responses will help us compare how people from different cultures, countries, and languages perceive and think. Studies like this one are essential to moving psychology and cognitive science beyond the narrow WEIRD sample in which most research has historically been conducted.')}
      </p>

      <h4>{_p('cf_debrief_voluntary', 'Taking part is voluntary')}</h4>
      <p class="consent-text">
        {_p('cf_debrief_voluntary_body', 'Although you have already completed the experiment, your involvement is still voluntary, and you may choose to withdraw the data you provided prior to debriefing, without penalty or loss of compensation. If you want to do so, please contact us at the contact information below.')}
      </p>

      <h4>{_p('cf_debrief_privacy', 'Privacy / Confidentiality')}</h4>
      <p class="consent-text">
        {_p('cf_debrief_privacy_body', 'Your data will be stored securely and coded by a recruitment-based code. Any audio or video recordings will be treated as potentially identifiable data, stored separately, and never shared publicly unless fully de-identified.')}
      </p>

      <h4>{_p('cf_debrief_contact', 'Further questions and contact information')}</h4>
      <p class="consent-text">{contact_body}</p>

      <p class="consent-text">{_p('cf_debrief_closing', 'All the best,')}</p>
      <p class="consent-text">{_p('cf_debrief_signature', 'Nori Jacoby and the Research Team')}</p>

    </div>
  </div>
</div>
""")


def debrief_page(
    include_deception: bool = False,
    deception_text: Optional[str] = None,
    **kwargs,
) -> InfoPage:
    """Returns InfoPage with debrief content. Add at end of experiment timeline."""
    content = _debrief_content(**kwargs)
    if include_deception and deception_text:
        content += Markup(f"""
<div class="text-left" style="font-size:18px;margin-top:1rem">
  <h4 style="color:#c00">{_p('cf_debrief_deception', 'This study included mild deception')}</h4>
  <p class="consent-text">
    {_p('cf_debrief_deception_intro', 'To obtain the information we were seeking, we withheld certain details. Now that the experiment is complete, we would like to explain and give you the opportunity to decide whether you would like your data to be included.')}
  </p>
  <p class="consent-text">{deception_text}</p>
</div>
""")
    return InfoPage(content, time_estimate=30)


# Backward compatibility aliases
audiovisual_consent_module = _audiovisual_content
addendum_gdpr_module = lambda: Markup(_addendum_content("europe"))
addendum_kpipa_module = lambda: Markup(_addendum_content("korea"))
addendum_singapore_taiwan_module = lambda: Markup(_addendum_content("singapore_taiwan"))
debrief_module = _debrief_content
