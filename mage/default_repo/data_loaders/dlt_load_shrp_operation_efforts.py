"""
Mage Data Loader: SharePoint Operation Efforts via DLT

Loads operation efforts data from SharePoint Excel file (operation_efforts.xlsx)
to the raw_sharepoint.operation_efforts table.

Target: raw_sharepoint.operation_efforts
Source: SharePoint Belgeler/operation_efforts.xlsx
"""

import sys
sys.path.insert(0, '/home/src/default_repo')

from utils.dlt_runner import run_dlt_script

if 'data_loader' not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def load_sharepoint_operation_efforts_via_dlt(*args, **kwargs):
    """Load SharePoint Operation Efforts data via DLT."""
    pipeline_type = kwargs.get('pipeline_type')
    if not pipeline_type:
        config = kwargs.get('configuration', {})
        pipeline_type = config.get('pipeline_type')
    if not pipeline_type:
        pipeline_type = 'initial'

    print(f"Pipeline Type: {pipeline_type}")

    # Get pipeline name for notifications
    pipeline_uuid = kwargs.get('pipeline_uuid', 'master_sharepoint')

    result = run_dlt_script(
        script_path='/home/dlt/sharepoint/shrp_operation_efforts.py',
        target_table='raw_sharepoint.operation_efforts',
        fail_on_error=True,
        extra_args=[f'--mode={pipeline_type}'],
        pipeline_name=pipeline_uuid,
    )

    result['pipeline_type'] = pipeline_type
    return result


@test
def test_output(output, *args) -> None:
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', f"Load failed: {output}"
