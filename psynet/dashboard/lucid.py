import json
from datetime import datetime
from math import ceil

import pandas as pd
from flask import render_template

from psynet.participant import Participant
from psynet.recruiters import BaseLucidRecruiter, LucidRID, LucidStatus
from psynet.timeline import Response
from psynet.utils import get_config

TEMPLATE_NAME = "dashboard_lucid.html"


def render_msg(title, msg, details, color):
    return f"<span style='color:{color}'><span style='font-weight:bold'>{title}</span>: {msg}</span> {details}"


def get_count_items(series):
    count = series.value_counts()
    items = []
    for label, count in zip(count.index, count.values):
        items.append(render_msg(label, count, "", "black"))
    return items


def get_entrant_psynet_status(entrant):
    if entrant.lucid_status == BaseLucidRecruiter.MARKETPLACE_CODE:
        return "Marketplace codes"
    elif not pd.isna(entrant.terminated_at):
        return "Terminated"
    elif not pd.isna(entrant.completed_at):
        return "Completed"
    else:
        return "Working"


def entrant_info_to_status_items(entrant_info):
    status_items = []
    for entrant in entrant_info:
        status_items.append(
            render_msg(entrant["status"], entrant["n"], "", entrant["color"])
        )
    return status_items


def compute_lucid_duration(row):
    if not pd.isna(row.lucid_entry_date):
        return row.lucid_last_date - row.lucid_entry_date
    else:
        return pd.NaT


def get_psynet_finished(row):
    if not pd.isna(row.terminated_at):
        return row.terminated_at
    elif not pd.isna(row.completed_at):
        return row.completed_at
    else:
        return None


def report_lucid():
    from psynet.experiment import get_experiment

    experiment = get_experiment()
    title = "Lucid"
    body = ""
    params = {
        "display_cards": False,
        "display_status_cards": False,
    }
    if not issubclass(experiment.recruiter.__class__, BaseLucidRecruiter):
        return render_template(
            TEMPLATE_NAME,
            title=title,
            html="""
                <div class="alert alert-danger" role="alert">
                    This experiment is not using Lucid as a recruiter.
                </div>
            """,
            params=params,
        )
    all_entrants = LucidRID.query.all()

    params["survey_number"] = experiment.recruiter.current_survey_number()
    params["survey_sid"] = experiment.recruiter.current_survey_sid()
    title += f" (Survey {params['survey_number']})"

    query = LucidStatus.query.order_by(LucidStatus.id.desc())
    earnings_per_click = 0
    completion_loi = 0
    termination_loi = 0
    conversion_rate = 0
    dropoff_rate = 0
    incidence_rate = 0
    if query.count() > 0:
        last_status = query.first()

        # Set params
        earnings_per_click = last_status.earnings_per_click
        completion_loi = last_status.completion_loi
        termination_loi = last_status.termination_loi
        conversion_rate = last_status.conversion_rate
        dropoff_rate = last_status.drop_off_rate
        incidence_rate = last_status.incidence_rate

        status_list = BaseLucidRecruiter.survey_codes
        if last_status.status not in status_list:
            status_list.append(last_status.status)

        last_status = last_status.to_dict()

        last_status["status_list"] = status_list

        last_status["api_call"] = (
            datetime.now() - pd.to_datetime(last_status["timestamp"])
        ).seconds
        params["last_status"] = last_status

    if len(all_entrants) == 0:
        return render_template(
            TEMPLATE_NAME,
            title=title,
            html="""
                <div class="alert alert-primary" role="alert">
                    No participants entered the experiment.
                </div>
            """,
            params=params,
        )
    else:
        params["display_cards"] = True

    entry_df = pd.DataFrame([entrant.to_dict() for entrant in all_entrants])
    # Display-only join: do not persist LucidRID.participant_id on page load.
    if "participant_id" in entry_df.columns:
        entry_df = entry_df.drop(columns=["participant_id"])
    participants = pd.DataFrame(
        [
            {"participant_id": participant.id, "rid": participant.worker_id}
            for participant in Participant.query.all()
        ]
    )
    entry_df = entry_df.merge(participants, on="rid", how="left")
    entry_df.lucid_entry_date = pd.to_datetime(
        entry_df.lucid_entry_date, format="mixed"
    )
    entry_df["psynet_status"] = entry_df.apply(get_entrant_psynet_status, axis=1)
    entry_df["entry_timestamp"] = entry_df.apply(
        lambda x: (
            x["lucid_entry_date"]
            if not pd.isna(x["lucid_entry_date"])
            else x["registered_at"]
        ),
        axis=1,
    )
    # to unix timestamp
    entry_df["entry_timestamp"] = (
        entry_df["entry_timestamp"] - pd.Timestamp("1970-01-01")
    ) // pd.Timedelta("1s")
    x_dict = {
        i: pd.to_datetime(i, unit="s").strftime("%H:%M:%S")
        for i in range(
            entry_df["entry_timestamp"].min(), entry_df["entry_timestamp"].max() + 1
        )
    }

    data = pd.DataFrame(
        {
            "value": entry_df.entry_timestamp,
            "type": entry_df.psynet_status,
        }
    ).to_dict(orient="records")

    params["respondents"] = {
        "data": data,
        "type2color": {
            "Marketplace codes": "black",
            "Terminated": "red",
            "Completed": "green",
            "Working": "blue",
        },
        "n_bins": 100,
        "x_dict": x_dict,
    }
    entry_df.lucid_last_date = pd.to_datetime(entry_df.lucid_last_date, format="mixed")
    if len(entry_df) > 0:
        entry_df["lucid_duration"] = entry_df.apply(compute_lucid_duration, axis=1)
        entry_df["lucid_duration"] = entry_df.lucid_duration.apply(
            lambda t: t.total_seconds() / 60 if not pd.isna(t) else t
        )

    entry_df["psynet_finished"] = entry_df.apply(get_psynet_finished, axis=1)
    if len(entry_df) > 0:
        durations = []
        for _, row in entry_df.iterrows():
            try:
                durations.append(
                    (row.psynet_finished - row.registered_at).total_seconds() / 60
                )
            except Exception:
                durations.append(pd.NaT)
        entry_df["psynet_duration"] = durations
    # Status; used in pandas query, linter does not recognize it
    completed_status = BaseLucidRecruiter.COMPLETED  # noqa: F841
    terminated_status = BaseLucidRecruiter.TERMINATED  # noqa: F841
    prescreened_status = BaseLucidRecruiter.MARKETPLACE_CODE  # noqa: F841
    in_survey_status = BaseLucidRecruiter.IN_SURVEY  # noqa: F841

    entrant_info = [
        {
            "status": "Working",
            "n": entry_df.query("psynet_status == 'Working'").shape[0],
            "color": "black",
        },
        {
            "status": "Terminated",
            "n": entry_df.query("psynet_status == 'Terminated'").shape[0],
            "color": "black",
        },
        {
            "status": "Completed",
            "n": entry_df.query("psynet_status == 'Completed'").shape[0],
            "color": "green",
        },
    ]

    items = entrant_info_to_status_items(entrant_info)

    items[0] += (
        "<br>The total number of working participants or participants who dropped out (e.g., close window)."
    )
    items[1] += "<br>The total number of respondents send to termination by PsyNet."
    items[2] += "<br>The total number of complete participants."

    params["psynet_status"] = {
        "title": "Status",
        "body": "Inferred status from Participant RID table.",
        "item_list": items,
    }
    psynet_terminated_df = entry_df.query("psynet_status == 'Terminated'")

    n_psynet_terminated = len(psynet_terminated_df)
    params["psynet_termination_reason"] = {
        "title": "Termination reasons",
        "body": f"Reasons why participants were terminated from PsyNet (n = {n_psynet_terminated}):",
        "item_list": get_count_items(entry_df.termination_reason),
    }

    lucid_entry_df = entry_df.loc[~pd.isna(entry_df.lucid_status)]
    total_entrants = len(lucid_entry_df)
    total_after_qualifications = len(
        lucid_entry_df.query("lucid_status != @prescreened_status")
    )
    total_completes = len(lucid_entry_df.query("lucid_status == @completed_status"))

    # Entrant breakdown
    entrant_info = [
        {
            "status": "Total entrants",
            "n": total_entrants,
            "color": "black",
        },
        {
            "status": "After qualifications",
            "n": total_after_qualifications,
            "color": "black",
        },
        {
            "status": "Completed",
            "n": total_completes,
            "color": "green",
        },
    ]
    items = entrant_info_to_status_items(entrant_info)

    items[0] += "<br>The total number of respondents clicking on the survey link."
    items[1] += "<br>The total number of respondents who passed the qualifications."
    items[2] += (
        "<br>The total number of respondents who are marked as complete by Lucid."
    )

    params["lucid_responent_activity"] = {
        "title": "Respondent activity",
        "body": "Tells us how many people started the qualification, passed them and completed the experiment.",
        "item_list": items,
    }

    # Client code breakdown (after prescreen):
    terminated_df = entry_df.query("lucid_status == @terminated_status")
    n_lucid_terminated = len(terminated_df)

    code_color_dict = {
        BaseLucidRecruiter.MARKETPLACE_CODE: "black",
        BaseLucidRecruiter.IN_SURVEY: "black",
        BaseLucidRecruiter.TERMINATED: "black",
        BaseLucidRecruiter.COMPLETED: "green",
    }
    entrant_info = [
        {
            "status": code,
            "n": len(lucid_entry_df.query("lucid_status == @code")),
            "color": color,
        }
        for code, color in code_color_dict.items()
    ]
    items = entrant_info_to_status_items(entrant_info)

    items[0] += (
        "<br>The total number of respondents who did not enter the experiment (e.g., not passsing the qualifications, "
        "marketplace error, rejection based on respondent quality score; see next card for breakdown)."
    )
    items[1] += (
        "<br>The total number of respondents who are doing the experiment or were not returned to the marketplace "
        "(e.g., closing the window)."
    )
    items[2] += (
        "<br>The total number of respondents who are marked as terminated in Lucid."
    )
    items[3] += (
        "<br>The total number of respondents who are marked as complete in Lucid."
    )
    n_psynet_working = len(entry_df.query("psynet_status == 'Working'"))
    n_lucid_working = len(lucid_entry_df.query("lucid_status == @in_survey_status"))
    if n_lucid_working != n_psynet_working:
        items[1] += (
            "<br><span class='text-danger'>Detected a mismatch in working participants in Psynet (n = "
            f"{n_psynet_working}) and Lucid (n = {n_lucid_working}).</span>"
        )

    if n_lucid_terminated != n_psynet_terminated:
        items[2] += (
            "<br><span class='text-danger'>Detected a mismatch in terminated participants in Psynet (n = "
            f"{n_psynet_terminated}) and Lucid (n = {n_lucid_terminated}).</span>"
        )

    completes_df = entry_df.query("lucid_status == @completed_status")
    n_lucid_completed = len(completes_df)
    psynet_completes_df = entry_df.query("psynet_status == 'Completed'")
    n_psynet_completed = len(psynet_completes_df)
    if n_lucid_completed != n_psynet_completed:
        lucid_complete_rids = psynet_completes_df.rid.to_list()
        cmd = f"psynet lucid compensate {params['survey_number']} {' '.join(lucid_complete_rids)}"
        button = f"""
        <a class="btn btn-primary mt-2" onclick="copyToClipboard('{cmd}')">Copy compensation command</a>
        """
        items[3] += (
            "<br><span class='text-danger'>Detected a mismatch in completed participants in Psynet (n = "
            + f"{n_psynet_completed}) and Lucid (n = {n_lucid_completed}).</span><br>"
            + button
        )

    params["lucid_client_codes"] = {
        "title": "Client codes",
        "body": "A more detailed breakdown us about the status of respondents.",
        "item_list": items,
    }

    params["lucid_market_place_codes"] = {
        "title": "Marketplace codes",
        "body": "Lucid market place codes for respondents.",
        "item_list": get_count_items(entry_df.lucid_market_place_code),
    }

    params["display_status_cards"] = entry_df.shape[0] > 0
    if params["display_status_cards"]:
        params["lucid_conversion_rate"] = {
            "title": f"Conversion rate: {int(conversion_rate * 100)}%",
            "body": "Percentage of completes of total people who passed the qualifications. Should be more than 10%.",
            "status": "success" if conversion_rate > 0.1 else "danger",
            "col": "col-4",
        }

        params["lucid_dropoff_rate"] = {
            "title": f"Dropoff rate: {int(dropoff_rate * 100)}%",
            "body": "Percentage of participants not returned to the market place who passed the qualifications. Should be less than 20%.",
            "status": "success" if dropoff_rate < 0.2 else "danger",
            "col": "col-4",
        }

        config = get_config()
        lucid_recruitment_config = json.loads(config.get("lucid_recruitment_config"))
        bid_incidence = lucid_recruitment_config["survey"]["BidIncidence"]
        ir_title = f"Incidence rate: {int(incidence_rate * 100)}%"
        if incidence_rate >= bid_incidence / 100:
            params["lucid_incidence_rate"] = {
                "title": ir_title,
                "body": f"Percentage of screened out based on (custom) qualifications divided by total completes + screened out participants. Currently set to: {bid_incidence} %; consider reducing it to increase reach.",
                "status": "success",
                "col": "col-4",
            }
        else:
            params["lucid_incidence_rate"] = {
                "title": ir_title,
                "body": f"Percentage of screened out based on (custom) qualifications divided by total completes + screened out participants. Currently set to: {bid_incidence} %, increase incidence rate.",
                "status": "danger",
                "col": "col-4",
            }

        wage_per_hour = config.get("wage_per_hour")
        set_completion_loi = ceil(
            experiment.estimated_completion_time(wage_per_hour) / 60
        )

        if len(completes_df) > 0:
            completion_title = f"Completion LOI: {completion_loi} minutes"
            text = f"Expected: {set_completion_loi} minutes."

            data = []
            for _, row in completes_df.iterrows():
                data.append(
                    {
                        "rid": row.rid,
                        "pid": (
                            row.participant_id
                            if not pd.isna(row.participant_id)
                            else "Not registered"
                        ),
                        "reason": (
                            row.termination_reason
                            if not pd.isna(row.termination_reason)
                            else "n/a"
                        ),
                        "lucid_duration": (
                            row.lucid_duration
                            if not pd.isna(row.lucid_duration)
                            else "n/a"
                        ),
                        "psynet_duration": (
                            row.psynet_duration
                            if not pd.isna(row.psynet_duration)
                            else "n/a"
                        ),
                        "code": (
                            row.lucid_status if not pd.isna(row.lucid_status) else "n/a"
                        ),
                        "type": "Lucid",
                        "value": (
                            row.psynet_duration
                            if not pd.isna(row.lucid_status)
                            else "n/a"
                        ),
                    }
                )
            if completion_loi < set_completion_loi:
                text += " Consider reducing the expected completion time."
                status = "warning"
            elif completion_loi > set_completion_loi:
                text += " Consider increasing the expected completion time."
                status = "danger"
            else:
                status = "success"
            params["lucid_completion_loi"] = {
                "title": completion_title,
                "body": text,
                "status": status,
                "border": True,
                "col": "col-4",
                "data": data,
            }

        if len(terminated_df) > 0 and len(psynet_terminated_df) > 0:
            psynet_termination_loi = int(
                psynet_terminated_df.psynet_duration.median().round()
            )
            data = []
            for _, row in terminated_df.iterrows():
                if not pd.isna(row.lucid_duration):
                    data.append(
                        {
                            "rid": row.rid,
                            "pid": (
                                row.participant_id
                                if not pd.isna(row.participant_id)
                                else "Not registered"
                            ),
                            "reason": (
                                row.termination_reason
                                if not pd.isna(row.termination_reason)
                                else "n/a"
                            ),
                            "lucid_duration": (
                                row.lucid_duration
                                if not pd.isna(row.lucid_duration)
                                else "n/a"
                            ),
                            "psynet_duration": (
                                row.psynet_duration
                                if not pd.isna(row.psynet_duration)
                                else "n/a"
                            ),
                            "code": (
                                row.lucid_status
                                if not pd.isna(row.lucid_status)
                                else "n/a"
                            ),
                            "type": "Lucid",
                            "value": (
                                row.lucid_duration
                                if not pd.isna(row.lucid_status)
                                else "n/a"
                            ),
                        }
                    )

            status = "danger" if termination_loi > 1 else "success"
            params["lucid_termination_loi"] = {
                "title": f"Termination LOI: {termination_loi} minutes",
                "body": (
                    "Median time from entry to termination. "
                    + "Should be a minute or less. "
                    + "Expected: "
                    + str(psynet_termination_loi)
                    + " minutes."
                ),
                "status": status,
                "border": True,
                "col": "col-4",
                "data": data,
            }

            data = [
                {**d, "x": d["lucid_duration"], "y": d["psynet_duration"]} for d in data
            ]

            params["termination_loi_scatter"] = {
                "title": "Termination LOI: PsyNet vs Lucid",
                "body": "Comparison of termination LOI between  PsyNet vs Lucid.",
                "status": status,
                "border": True,
                "col": "col-4",
                "data": data,
            }

        responses = Response.query.filter_by(failed=False).all()
        if len(responses) > 0:
            response_df = pd.DataFrame(
                [
                    {
                        "question": response.question,
                        "participant_id": response.participant_id,
                        "answer": response.answer,
                    }
                    for response in responses
                ]
            )
            answer_counts = (
                response_df.groupby("participant_id").answer.count().reset_index()
            )
            answer_counts = answer_counts.merge(
                entry_df, on="participant_id", how="left"
            )
            answer_counts["reason"] = answer_counts.termination_reason.apply(
                lambda r: r if not pd.isna(r) else "n/a"
            )
            answer_counts["value"] = answer_counts.answer
            answer_counts["type"] = answer_counts.psynet_status
            relevant_cols = ["value", "type", "participant_id", "rid", "reason"]
            answer_counts = answer_counts[relevant_cols]
            rids = answer_counts.rid.to_list()  # noqa: F841

            missing = terminated_df.query("rid not in @rids")[
                ["rid", "termination_reason"]
            ]
            missing = missing.merge(
                entry_df[["rid", "participant_id"]], on="rid", how="left"
            )
            missing["participant_id"] = missing.participant_id.apply(
                lambda x: x if not pd.isna(x) else "Not registered"
            )
            missing["reason"] = missing.termination_reason.apply(
                lambda r: r if not pd.isna(r) else "n/a"
            )
            missing["value"] = 0
            missing["type"] = "Terminated"

            missing = missing[relevant_cols]
            answer_counts = pd.concat([answer_counts, missing])
            type2color = {"Completed": "green", "Terminated": "red", "Working": "blue"}

            n_bins = answer_counts.value.max()
            params["response_per_participant"] = {
                "data": answer_counts.to_dict(orient="records"),
                "type2color": type2color,
                "n_bins": n_bins,
            }

        params["epc"] = {
            "title": f"EPC: {earnings_per_click}",
            "body": "Earnings per click = (CPI * completes) / system entrants. Make sure the value is high enough.",
            "status": "info",
            "col": "col-4",
        }

    return render_template(
        TEMPLATE_NAME,
        title=title,
        html=body,
        params=params,
    )
