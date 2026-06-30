"""Scheduled Ops IQ check — runs outside the ADK agent (no session overhead).

Invoked by Cloud Scheduler → Cloud Run Job on a cron schedule.
Can also be run locally for testing:

    cd new_folder_structure/agents/ops-iq/OpsIQ
    PYTHONPATH="$(pwd):$(pwd)/../../.." python scheduler/run_scheduled_check.py
    PYTHONPATH="$(pwd):$(pwd)/../../.." python scheduler/run_scheduled_check.py --report
    PYTHONPATH="$(pwd):$(pwd)/../../.." python scheduler/run_scheduled_check.py --user-report
    PYTHONPATH="$(pwd):$(pwd)/../../.." python scheduler/run_scheduled_check.py --agent-report
    PYTHONPATH="$(pwd):$(pwd)/../../.." python scheduler/run_scheduled_check.py --eod-summary
    PYTHONPATH="$(pwd):$(pwd)/../../.." python scheduler/run_scheduled_check.py --hours 48

Exit codes:
    0 — healthy (or report sent without errors)
    1 — threshold violations found (useful for CI / pager integration)
    2 — execution error
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("ops_iq_scheduler")

# OpsIQ/ = agent root (agent core files: config.py, prompts.py, etc.)
_agent_root = Path(__file__).parent.parent.resolve()
# new_folder_structure/ = tools root (from tools.google.metrics_tool etc.)
_tools_root = _agent_root.parents[2].resolve()

sys.path.insert(0, str(_agent_root))
sys.path.insert(0, str(_tools_root))

from dotenv import load_dotenv
load_dotenv(_agent_root / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(description="Ops IQ scheduled check")
    parser.add_argument("--report", action="store_true",
                        help="Always send a full status report (ignores thresholds)")
    parser.add_argument("--check-only", action="store_true",
                        help="Run threshold check but do not send any email")
    parser.add_argument("--user-report", action="store_true",
                        help="Send daily user-wise token usage report with pie chart")
    parser.add_argument("--agent-report", action="store_true",
                        help="Send daily per-agent token usage report with bar chart")
    parser.add_argument("--eod-summary", action="store_true",
                        help="Send combined EOD digest: health status + metrics + agent + user usage (recommended daily job)")
    parser.add_argument("--hours", type=int, default=24,
                        help="Lookback window in hours (default: 24)")
    args = parser.parse_args()

    try:
        from tools.alerting.alerting_tool import get_tools as get_alerting_tools
        fns = {fn.__name__: fn for fn in get_alerting_tools()}

        if args.check_only:
            logger.info("Running threshold check only (no email)")
            result = fns["check_thresholds"](hours=args.hours)
            print(json.dumps(result, indent=2, default=str))
            return 1 if result.get("violation_count", 0) > 0 else 0

        if args.eod_summary:
            logger.info("Sending combined EOD summary (hours=%d)", args.hours)
            result = fns["send_eod_summary"](hours=args.hours)
        elif args.agent_report:
            logger.info("Sending daily agent usage report with bar chart")
            from tools.firestore.usage_tracker_tool import get_tools as get_usage_tools
            usage_fns = {fn.__name__: fn for fn in get_usage_tools()}
            days = max(1, args.hours // 24) if args.hours >= 24 else 1
            agg_result = usage_fns["aggregate_daily_agent_usage"]()
            logger.info("Agent snapshot: %s", agg_result.get("status"))
            result = fns["send_agent_usage_report"](days=days)
        elif args.user_report:
            logger.info("Sending daily user usage report with pie chart")
            from tools.firestore.usage_tracker_tool import get_tools as get_usage_tools
            usage_fns = {fn.__name__: fn for fn in get_usage_tools()}
            days = max(1, args.hours // 24) if args.hours >= 24 else 1
            # Step 1: aggregate and write daily snapshot to Firestore
            agg_result = usage_fns["aggregate_daily_user_usage"]()
            logger.info("Daily snapshot: %s", agg_result.get("status"))
            # Step 2: send email with pie chart
            result = fns["send_user_usage_report"](days=days)
        elif args.report:
            logger.info("Sending full status report (hours=%d)", args.hours)
            result = fns["send_status_report"](hours=args.hours)
        else:
            logger.info("Running alert check (hours=%d)", args.hours)
            result = fns["send_alert_email"](hours=args.hours)

        print(json.dumps(result, indent=2, default=str))

        if result.get("status") == "error":
            logger.error("Check completed with errors")
            return 2

        violations = result.get("violation_count", 0)
        if violations:
            logger.warning("Check complete: %d violation(s) found — alert sent", violations)
            return 1

        logger.info("Check complete: all metrics healthy")
        return 0

    except Exception as exc:
        logger.exception("Scheduled check failed: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
