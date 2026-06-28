"""
Mage Data Loader: SharePoint Capex/Opex Adjustment via DLT

Loads capex/opex adjustment data from SharePoint Excel file (capex_opex_adjustment.xlsx)
to the raw_sharepoint.capex_opex_adjustment table.

Target: raw_sharepoint.capex_opex_adjustment
Source: SharePoint Belgeler/capex_opex_adjustment.xlsx
"""

import sys
sys.path.insert(0, '/home/src/default_repo')

from utils.dlt_runner import run_dlt_script

if 'data_loader' not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def load_sharepoint_capex_opex_adjustment_via_dlt(*args, **kwargs):
    """Load SharePoint capex_opex Adjustment data via DLT."""
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
        script_path='/home/dlt/sharepoint/shrp_capex_opex_adjustment.py',
        target_table='raw_sharepoint.capex_opex_adjustment',
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
