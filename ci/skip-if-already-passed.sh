# Source this at the start of a job's before_script. If this job passed on
# identical files in an earlier pipeline (see ci/already_tested.py), it ends
# the job successfully before any setup runs.
[ "${CI_MERGE_REQUEST_EVENT_TYPE:-}" = merge_train ] || return 0
_already_passed_job="${CI_JOB_NAME% [0-9]*/[0-9]*}"
_already_passed_job="${_already_passed_job%%: \[*}"
case "${ALREADY_PASSED_JOBS:-}" in
  *",$_already_passed_job,"*)
    echo "Skipping $_already_passed_job: it passed on identical files in $ALREADY_TESTED_PIPELINE_URL"
    exit 0
    ;;
esac
unset _already_passed_job
