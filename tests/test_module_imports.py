"""Every module-scope name must actually resolve at module scope.

This exists because flo.py shipped a doctor() that referenced `Path` while the
only `from pathlib import Path` sat inside self_test(). ast.parse() accepted it,
the syntax check passed, and it would have raised NameError the first time
anyone ran --doctor.
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHECKER = ROOT / "tools" / "check_module_imports.py"


def test_no_module_scope_name_is_only_imported_inside_a_function():
    modules = sorted(str(p) for p in ROOT.glob("*.py"))
    result = subprocess.run([sys.executable, str(CHECKER), *modules],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_checker_catches_the_bug_it_was_written_for(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text(
        "def self_test():\n"
        "    from pathlib import Path\n"
        "    return Path('/tmp')\n"
        "\n"
        "def doctor():\n"
        "    return Path.home()\n"
    )
    result = subprocess.run([sys.executable, str(CHECKER), str(bad)],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "doctor() uses 'Path'" in result.stdout


def test_the_checker_does_not_flag_closures(tmp_path):
    """A nested function reading its enclosing scope is ordinary Python."""
    good = tmp_path / "good.py"
    good.write_text(
        "def outer():\n"
        "    total = 0\n"
        "    def inner():\n"
        "        return total\n"
        "    return inner()\n"
    )
    result = subprocess.run([sys.executable, str(CHECKER), str(good)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
