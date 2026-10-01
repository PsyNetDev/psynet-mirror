"""Researcher recording outcomes, including assets with no downloadable bytes.

Use the same outcome fields as the asset manifest. The dashboard is read-only
and paginated by asset ID; viewing it must never enqueue work or extend upload
deadlines. Authentication is supplied by the dashboard route registration.
"""

from flask import abort, render_template, request

from ..trial.record import Recording


def report_recordings():
    """Render up to 200 recordings and a link to older rows."""
    query = Recording.query.order_by(Recording.id.desc())
    before = request.args.get("before")
    if before is not None:
        try:
            before = int(before)
        except ValueError:
            abort(400)
        if not 0 < before <= 2**63 - 1:
            abort(400)
        query = query.filter(Recording.id < before)
    assets = query.limit(201).all()
    rows = [
        {
            **asset.recording_summary,
            "id": asset.id,
            "participant_id": asset.participant_id,
            "trial_id": asset.trial_id,
            "url": asset.url if asset.deposited else None,
        }
        for asset in assets[:200]
    ]
    return render_template(
        "dashboard_recordings.html",
        title="Recordings",
        rows=rows,
        next_before=rows[-1]["id"] if len(assets) > 200 else None,
    )
