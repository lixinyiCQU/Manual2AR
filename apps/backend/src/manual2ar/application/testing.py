"""Keep host-installed plugins (for example ROS) out of this project's tests."""
import os
import sys

def main():
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
    import pytest
    raise SystemExit(pytest.main(['tests','-q','-p','no:cacheprovider',*sys.argv[1:]]))

if __name__=='__main__':main()
