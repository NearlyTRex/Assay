# Tests for promptc/__init__.py -- package metadata.

# Local imports
import promptc

def test_version_is_exposed():
    assert promptc.__version__

def test_version_matches_the_cli():
    from promptc import cli
    assert cli.VERSION == promptc.__version__
