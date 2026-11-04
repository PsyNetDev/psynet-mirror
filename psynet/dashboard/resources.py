import datetime

import pandas as pd
from flask import render_template
from markupsafe import Markup


def report_resource_use():
    TEMPLATE_NAME = "dashboard_resources.html"
    title = "Resource usage"
    data = summarize_resource_use()
    if data is None:
        return render_template(
            TEMPLATE_NAME,
            title=title,
            html=Markup(
                """
            <div class="alert alert-danger" role="alert">
                Wait at least 1 minute to see the first data.
            </div>
            """
            ),
        )

    return render_template(
        TEMPLATE_NAME,
        title=title,
        html="",
        data=data,
    )


def summarize_resource_use():
    from psynet.experiment import ExperimentStatus

    window_length = datetime.timedelta(hours=48)
    data = (
        ExperimentStatus.query.filter(
            ExperimentStatus.creation_time > datetime.datetime.now() - window_length
        )
        .order_by(ExperimentStatus.id.desc())
        .all()
    )

    if len(data) == 0:
        return None

    df_raw = pd.DataFrame([row.to_dict() for row in data])
    df_raw.drop(columns=["extra_info", "id"], inplace=True)

    df_normalized = normalize_resource_use(df_raw)

    df_plot = df_normalized.melt(id_vars="timestamp", var_name="type", value_name="y")
    df_plot = add_raw_values(df_plot, df_raw)
    df_plot["label"] = df_plot.apply(format_label, axis=1)
    df_plot["timestamp"] = format_time_str(df_plot["timestamp"])
    df_plot["type"] = format_unit(df_plot["type"])

    return df_plot.to_dict(orient="records")


def format_label(row):
    match row.type:
        case "cpu_usage_pct":
            return f"{row.y_unit} % of total CPU usage"
        case "ram_usage_pct":
            return f"{row.y_unit} % of total RAM"
        case "disk_usage_pct":
            return f"{int(row.y_unit)} % of total disk space available"
        case "median_response_time":
            return f"{round(row.y_unit, 2)} s median response time"
        case "requests_per_minute":
            return f"{int(row.y_unit)} page loads per minute"
        case "n_working_participants":
            return f"{int(row.y_unit)} total working participants"
        case _:
            return row.y_unit


def max_100(x):
    return (x / x.max()) * 100


def normalize_resource_use(_resources_df):
    resources_df = _resources_df.copy()
    resources_df["timestamp"] = resources_df.index
    resources_df["median_response_time"] = max_100(resources_df["median_response_time"])
    resources_df["requests_per_minute"] = max_100(resources_df["requests_per_minute"])
    resources_df["n_working_participants"] = max_100(
        resources_df["n_working_participants"]
    )
    return resources_df


def add_raw_values(df_plot, df_raw):
    df_raw_long = df_raw.melt(id_vars="timestamp", var_name="type", value_name="y")
    df_plot["y_unit"] = df_raw_long["y"]
    df_plot["x"] = df_plot["timestamp"].astype(int)
    df_plot["timestamp"] = df_raw_long["timestamp"]
    df_plot.dropna(inplace=True)
    return df_plot


def format_time_str(timestamp_series):
    now = pd.to_datetime("now")
    earliest = timestamp_series.min()

    if now.day == earliest.day:
        date_format = "%H:%M"
    elif now.year == earliest.year:
        date_format = "%m-%d %H:%M"
    else:
        date_format = "%Y-%m-%d %H:%M"

    return [
        str(ts)
        for ts in pd.to_datetime(timestamp_series, unit="s").dt.strftime(date_format)
    ]


def format_unit(type_list: list):
    replacement_dict = {
        "cpu_usage_pct": "CPU usage (%)",
        "ram_usage_pct": "RAM usage (%)",
        "disk_usage_pct": "Disk space usage (%)",
        "median_response_time": "Median page loading time (%)",
        "requests_per_minute": "Number of page loads",
        "n_working_participants": "Total working participants",
    }
    return [replacement_dict.get(item, item) for item in type_list]
