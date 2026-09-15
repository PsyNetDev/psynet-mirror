# consents_cococo — IRB Consent Modules

PsyNet-compatible consent modules for IRB protocols at Cornell University.

Each module maps to one IRB protocol, renders the approved consent text as HTML,
and integrates with PsyNet's `Consent` / `Module` system (conditional rejection,
`participant.var` storage, bot-response support).

---

## IRB Protocols and Modules

| IRB # | Study Title | Module File | Main Class |
|-------|-------------|-------------|------------|
| IRB0150599 | Predicting Algorithmic Trust at Scale (DARPA) | `consent_algorithmic_trust.py` | `consent_irb_algorithmic_trust` |
| IRB0150361 | The cultural foundation of perception and cognition — online experiments | `consent_cultural_foundation.py` | `consent_irb_cultural_foundation` |
| IRB0149930 | Building Infrastructure to Study Human-AI Hybrid Societies (HNDS-I) | `consent_human_ai.py` | `consent_irb_nj6` |
| IRB0148995 | Designing Smart Environments to Augment Collective Learning & Creativity | `consent_science_of_learning.py` | `consent_cococo_science_of_learning` |

---

## Module Reference

### 1. `consent_irb_algorithmic_trust` — IRB0150599
**"Predicting Algorithmic Trust at Scale"** (DARPA/DoD-funded; multi-university)

```python
from consents_cococo.consent_algorithmic_trust import (
    consent_irb_algorithmic_trust,
    debrief_page,
)

consent_irb_algorithmic_trust(consent="MAIN")
consent_irb_algorithmic_trust(consent="CINT",
                               addendum_regions=["europe", "korea", "singapore_taiwan"])
consent_irb_algorithmic_trust(show_duration_payment=False)
debrief_page()  # add at end of timeline
```

**Parameters:**
- `consent`: `"MAIN"` (Prolific/direct) | `"CINT"` (marketplace panel)
- `addendum_regions`: list from `["europe", "korea", "singapore_taiwan"]`
- `DURATION`: estimated experiment duration in minutes; if omitted, reads `prolific_estimated_completion_minutes` from `config.txt`
- `PAYMENT`: expected payment in USD; if omitted, reads `base_payment` from `config.txt`
- `show_duration_payment`: `bool` — show or hide the participant-facing duration/payment sentence

**Stored variable:** `irb_algorithmic_trust_consent`
**Key difference from other modules:** DoD/DARPA funding and oversight language; study covers AI trust judgments.

---

### 2. `consent_irb_cultural_foundation` — IRB0150361
**"The cultural foundation of perception and cognition — online experiments"**

```python
from consents_cococo.consent_cultural_foundation import (
    consent_irb_cultural_foundation,
    debrief_page,
)

consent_irb_cultural_foundation(consent="MAIN")
consent_irb_cultural_foundation(consent="CINT", audiovisual=True,
                                 addendum_regions=["europe", "korea"])
consent_irb_cultural_foundation(consent="DATABASE",
                                addendum_regions=["europe", "korea", "singapore_taiwan"])
consent_irb_cultural_foundation(show_duration_payment=False)
debrief_page()
```

**Parameters:**
- `consent`: `"MAIN"` | `"CINT"` | `"DATABASE"`
- `audiovisual`: `bool` — adds a *second page* with AV consent (own "I agree" bar)
- `addendum_regions`: list from `["europe", "korea", "singapore_taiwan"]`
- `DURATION`: estimated experiment duration in minutes for `"MAIN"`/`"CINT"`; if omitted, reads `prolific_estimated_completion_minutes` from `config.txt`
- `PAYMENT`: expected payment in USD for `"MAIN"`/`"CINT"`; if omitted, reads `base_payment` from `config.txt`
- `show_duration_payment`: `bool` — show or hide the participant-facing duration/payment sentence
- `include_ai_consent`: `bool` — AI data-sharing paragraph (AV page only)

**Stored variables:** `irb_cultural_foundation_main_consent`, `irb_cultural_foundation_database_consent`, `irb_cultural_foundation_av_consent`
**Key difference:** Supports main study consent, CINT indirect-payment consent, Lab-Recruiter database enrollment consent, regional privacy addenda, and a separate AV consent page.

---

### 3. `consent_irb_nj6` — IRB0149930
**"Building Infrastructure to Study Human-AI Hybrid Societies in Experimental Social Networks"** (HNDS-I / NSF)

```python
from consents_cococo.consent_human_ai import consent_irb_nj6, debrief_page

consent_irb_nj6(consent="MAIN")
consent_irb_nj6(consent="CINT",
                 audiovisual=True, addendum_regions=["europe", "korea", "singapore_taiwan"])
consent_irb_nj6(show_duration_payment=False)
debrief_page()
```

**Parameters:**
- `consent`: `"MAIN"` | `"CINT"`
- `audiovisual`: `bool`
- `addendum_regions`: list from `["europe", "korea", "singapore_taiwan"]`
- `DURATION`: estimated experiment duration in minutes; if omitted, reads `prolific_estimated_completion_minutes` from `config.txt`
- `PAYMENT`: expected payment in USD; if omitted, reads `base_payment` from `config.txt`
- `show_duration_payment`: `bool` — show or hide the participant-facing duration/payment sentence
- `include_ai_consent`: `bool` (AV only)

**Stored variable:** `irb_nj6_consent`

---

### 4. `consent_cococo_science_of_learning` — IRB0148995
**"Designing Smart Environments to Augment Collective Learning & Creativity"** (NSF)

```python
from consents_cococo.consent_science_of_learning import consent_cococo_science_of_learning

consent_cococo_science_of_learning(DURATION=10, PAYMENT=3)
consent_cococo_science_of_learning(show_duration_payment=False)
consent_cococo_science_of_learning(addendum_regions=["europe", "korea", "singapore_taiwan"])
```

**Parameters:**
- `DURATION`: estimated experiment duration in minutes; if omitted, reads `prolific_estimated_completion_minutes` from `config.txt`
- `PAYMENT`: expected payment in USD; if omitted, reads `base_payment` from `config.txt`
- `show_duration_payment`: `bool` — show or hide the participant-facing duration/payment sentence
- `addendum_regions`: list from `["europe", "korea", "singapore_taiwan"]`

**Stored variable:** `science_of_learning_consent`

---

## Common Pattern

All modules except `consent_cococo_science_of_learning` expose:

```python
debrief_page(include_deception=False, deception_text=None)
```

Add this at the **end** of the timeline to display a debrief letter.

