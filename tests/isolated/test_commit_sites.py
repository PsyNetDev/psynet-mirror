"""Every function in PsyNet that calls ``.commit()`` directly, with its reason.

Commits made indirectly, through ``transaction()``, ``with_transaction`` or
``sessions_scope(commit=True)``, are not listed.

Only the code that owns a transaction commits it (see the ``psynet.db`` module
docstring). When this test fails, either leave committing to the transaction's
owner (use ``db.session.flush()`` for generated values), or, if the function
owns its transaction or records an external call, add it here with a reason.
"""

import ast
from pathlib import Path

import psynet

_OWNS_REQUEST = "route or request phase that owns its transaction"
_OWNS_JOB = "scheduled task, poller or worker job that owns its transaction"
_OWNS_CLI = "CLI command or launch step that owns its transaction"
_OWNS_DEPLOY = "deploy-time setup step that owns its transaction"

COMMIT_SITES = {
    "asset.py::AssetRegistry.prepare_assets_for_deployment": _OWNS_DEPLOY,
    "bot.py::Bot.__init__": "Bot() is an entry point in tests and scripts",
    "chatroom.py::EnableChatrooms.handle_message": "websocket handler",
    "command_line.py::_prepare": _OWNS_CLI,
    "command_line.py::_debug_legacy": _OWNS_CLI,
    "command_line.py::_debug_docker": _OWNS_CLI,
    "command_line.py::_debug_auto_reload": _OWNS_CLI,
    "command_line.py::estimate": _OWNS_CLI,
    "data.py::_retry_on_transient_lock": _OWNS_CLI,
    "data.py::_drop_foreign_key_constraints._run": _OWNS_CLI,
    "data.py::populate_db_from_zip_file": _OWNS_CLI,
    "db.py::transaction": "the transaction() context manager",
    "db.py::_commit_external_call_state": "the one helper for external-call state",
    "experiment.py::Experiment.on_launch": _OWNS_REQUEST,
    "experiment.py::Experiment.after_request": _OWNS_REQUEST,
    "experiment.py::Experiment._nodes_on_deploy": _OWNS_DEPLOY,
    "experiment.py::Experiment.setup_experiment_config": _OWNS_DEPLOY,
    "experiment.py::Experiment.setup_experiment_variables": _OWNS_DEPLOY,
    "experiment.py::Experiment._ensure_worker_complete": _OWNS_REQUEST,
    "experiment.py::Experiment._route_timeline": _OWNS_REQUEST,
    "experiment.py::Experiment.isolate_batch_item_failure": _OWNS_JOB,
    "experiment.py::Experiment.log_to_db": "error records must survive a failing request",
    "experiment.py::Experiment._reapply_lock_timeout_and_prepare": _OWNS_REQUEST,
    "experiment.py::Experiment._skip_ready_hold_on_get": _OWNS_REQUEST,
    "experiment.py::Experiment._relock_arriver_after_barrier_check": _OWNS_REQUEST,
    "experiment.py::Experiment._attempt_queued_barrier_checks": _OWNS_REQUEST,
    "experiment.py::Experiment.route_response": _OWNS_REQUEST,
    "process.py::AsyncProcess.call_function": _OWNS_JOB,
    "process.py::LocalAsyncProcess.thread_function": _OWNS_JOB,
    "process.py::WorkerAsyncProcess.check_timeouts": _OWNS_JOB,
    "pytest_psynet.py::trial": "pytest fixture",
    "recruiters.py::BaseLucidRecruiter.normalize_entry_information": (
        "Dallinger's /participant and /load-participant routes do not commit"
    ),
    "recruiters.py::_abandon_overdue_participants": (
        "Dallinger's clock calls it in a sessions_scope() that does not commit"
    ),
    "sync.py::_advance_released_hold_waiters_after_commit": _OWNS_JOB,
    "sync.py::_evaluate_held_instance": _OWNS_JOB,
    "sync.py::check_sync_groups": _OWNS_JOB,
    "timeline.py::Module.prepare_assets_for_deployment": _OWNS_DEPLOY,
    "timeline.py::Module.nodes_register_in_db": _OWNS_DEPLOY,
    "timeline.py::Module.nodes_stage_assets": _OWNS_DEPLOY,
    "trial/chain.py::ChainTrialMaker._claim_node_capacity": "savepoint commit",
    "trial/main.py::Trial.call_async_post_trial": _OWNS_JOB,
    "trial/main.py::TrialNode.call_async_on_deploy": _OWNS_JOB,
}


def _commit_sites(package_dir):
    """Return ``path::qualified.function`` for every ``.commit()`` call."""
    sites = set()
    for path in package_dir.rglob("*.py"):
        if "resources" in path.relative_to(package_dir).parts:
            continue

        def visit(node, scope):
            for child in ast.iter_child_nodes(node):
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    visit(child, [*scope, child.name])
                    continue
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "commit"
                    and not child.args
                ):
                    relative = path.relative_to(package_dir).as_posix()
                    sites.add(f"{relative}::{'.'.join(scope) or '<module>'}")
                visit(child, scope)

        visit(ast.parse(path.read_text()), [])
    return sites


def test_every_commit_site_has_a_reason():
    sites = _commit_sites(Path(psynet.__file__).parent)
    assert sites - COMMIT_SITES.keys() == set(), "unlisted commits"
    assert COMMIT_SITES.keys() - sites == set(), "listed commits no longer exist"
