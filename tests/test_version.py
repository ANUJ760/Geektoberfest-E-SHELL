### Needed one becauase of pasring output or missing values.

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import commands
import version


class VersionTests(unittest.TestCase):
    def test_version_command_output(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            commands.handle_command("version")
        out = buf.getvalue()
        self.assertIn(f"E-SHELL v{version.__version__}", out)
        self.assertIn("Python", out)
        self.assertIn("Dependencies:", out)

    def test_tracked_packages_parses_names(self):
        with tempfile.TemporaryDirectory() as d:
            req = Path(d) / "requirements.txt"
            req.write_text(
                "# comment\nscikit-learn==1.5.0\n\nnumpy>=1.0  # inline\n"
                "-r other.txt\nfoo[extra]; python_version>'3'\n"
            )
            with mock.patch.object(version, "REQUIREMENTS", req):
                self.assertEqual(version.tracked_packages(),
                                 ["scikit-learn", "numpy", "foo"])

    def test_missing_requirements_file(self):
        missing = Path("/nonexistent/requirements.txt")
        with mock.patch.object(version, "REQUIREMENTS", missing):
            self.assertEqual(version.dependency_lines(),
                             ["requirements.txt not found or empty"])

    def test_usage_line_without_resource(self):
        with mock.patch.object(version, "resource", None):
            line = version.usage_line()
        self.assertIn("PID", line)
        self.assertNotIn("peak", line)
