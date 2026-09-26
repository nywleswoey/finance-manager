"""Load a build/ statement script as a module, the way it runs as a script.

    from tests.buildscript import load_build_script
    parse_cash = load_build_script("parse_cash")

The build/ scripts run as `python3 build/x.py` and import their siblings by bare name
(`from _pdf import raw_text`), so build/ goes on sys.path for the import and comes off
after it. The module is registered under `<name>_under_test`, so it never collides with a
test that imports the script by its bare name. `main()` is not executed.
"""
import importlib.util
import os
import sys

BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build")


def load_build_script(name):
    sys.path.insert(0, BUILD)
    try:
        spec = importlib.util.spec_from_file_location(
            f"{name}_under_test", os.path.join(BUILD, f"{name}.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(BUILD)
    return mod
