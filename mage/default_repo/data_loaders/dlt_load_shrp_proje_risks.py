"""
Mage Data Loader: SharePoint Proje Risks via DLT

Target: raw_sharepoint.proje_risks
"""

import sys
sys.path.insert(0, '/home/src/default_repo')

from utils.dlt_runner import run_dlt_script

if 'data_loader' not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def load_sp_proje_risks_via_dlt(*args, **kwargs):
    """Load SharePoint Proje Risks list via DLT."""
    pipeline_type = kwargs.get('pipeline_type')
    if not pipeline_type:
        config = kwargs.get('configuration', {})
        pipeline_type = config.get('pipeline_type')
    if not pipeline_type:
        pipeline_type = 'initial'

    print(f"Pipeline Type: {pipeline_type}")

    result = run_dlt_script(
        script_path='/home/dlt/sharepoint/shrp_proje_risks.py',
        target_table='raw_sharepoint.proje_risks',
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
