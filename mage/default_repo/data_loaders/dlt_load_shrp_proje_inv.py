"""
Mage Data Loader: SharePoint Proje Inv via DLT

This loader triggers the DLT script for SharePoint Proje Inv list extraction.
The actual extraction logic is maintained in the DLT script.

Usage: Used in master_initial_sharepoint and master_daily_sharepoint pipelines
Target: raw_sharepoint.proje_inv

Pipeline Types:
    - initial: Full table replace (drops existing data)
    - daily: Merge mode (upserts records, handles schema evolution)
"""

import sys
sys.path.insert(0, '/home/src/default_repo')

from utils.dlt_runner import run_dlt_script

if 'data_loader' not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def load_sp_proje_inv_via_dlt(*args, **kwargs):
    """Load SharePoint Proje Inv list via DLT."""
    pipeline_type = kwargs.get('pipeline_type')
    if not pipeline_type:
        config = kwargs.get('configuration', {})
        pipeline_type = config.get('pipeline_type')
    if not pipeline_type:
        pipeline_type = 'initial'

    print(f"Pipeline Type: {pipeline_type}")

    result = run_dlt_script(
        script_path='/home/dlt/sharepoint/shrp_proje_inv.py',
        target_table='raw_sharepoint.proje_inv',
        fail_on_error=True,
        extra_args=[f'--mode={pipeline_type}']
    )

    result['pipeline_type'] = pipeline_type
    return result


@test
def test_output(output, *args) -> None:
    """Test that the load completed successfully."""
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', f"Load failed: {output}"
