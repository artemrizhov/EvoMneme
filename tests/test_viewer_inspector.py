"""Run selection drawer regressions against the shipped viewer handlers."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ViewerInspectorTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Viewer inspector regression needs an existing Node.js')
    def test_expanded_selection_and_focus(self):
        result = subprocess.run(
            [shutil.which('node'), str(Path(__file__).with_suffix('.js'))],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
