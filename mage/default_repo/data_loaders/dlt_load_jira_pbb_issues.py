"""
Mage Data Loader: Jira PBB (Portfolio Backlog Board) Issues via DLT

Target: raw_jira.issues (merge/upsert into the same table)

Loads a filtered subset of Jira issues scoped to PBB/portfolio-level items.
Configure via env vars:
  JIRA_PBB_ISSUE_TYPE  — comma-separated issue types (e.g. "Epic,Initiative")
  JIRA_PBB_PROJECT_KEY — comma-separated project keys  (e.g. "PPBM,PORT")

If neither env var is set, block returns success without loading (no-op).
"""

import os
import sys
sys.path.insert(0, '/home/src/default_repo')

from utils.dlt_runner import run_dlt_script

if 'data_loader' not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def load_jira_pbb_issues(data, *args, **kwargs):
    pipeline_type = kwargs.get('pipeline_type')
    if not pipeline_type:
        config = kwargs.get('configuration', {})
        pipeline_type = config.get('pipeline_type', 'daily')

    issue_type = os.getenv('JIRA_PBB_ISSUE_TYPE', '').strip()
    project_key = os.getenv('JIRA_PBB_PROJECT_KEY', '').strip()

    if not issue_type and not project_key:
        print("[pbb_issues] No JIRA_PBB_ISSUE_TYPE or JIRA_PBB_PROJECT_KEY configured — skipping.")
        return {'status': 'success', 'rows_loaded': 0, 'skipped': True}

    pipeline_uuid = kwargs.get('pipeline_uuid', 'master_daily_jira')
    extra_args = [f'--mode={pipeline_type}']
    if issue_type:
        extra_args.append(f'--issue-type={issue_type.split(",")[0]}')  # first type; extend if needed
    print(f"[pbb_issues] pipeline_type={pipeline_type} issue_type={issue_type} project_key={project_key}")

    result = run_dlt_script(
        script_path='/home/dlt/jira/jira_issues.py',
        target_table='raw_jira.issues',
        fail_on_error=True,
        extra_args=extra_args,
        pipeline_name=pipeline_uuid,
    )
    result['pipeline_type'] = pipeline_type
    return result


@test
def test_output(output, *args) -> None:
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', f"Load failed: {output}"
