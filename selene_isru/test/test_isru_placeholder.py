# Renamed from test_placeholder.py: selene_sim/test/ has a file of that
# name too, and because the test directories have no __init__.py pytest
# derives the module name from the basename alone. Collecting both packages
# in one process therefore aborted with "import file mismatch". Test module
# basenames must stay unique across the workspace.
def test_placeholder():
    assert True
