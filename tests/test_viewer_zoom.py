"""Run zoom regressions on the viewer's shipped Cytoscape dependency."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ViewerZoomTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Viewer zoom regression needs an existing Node.js')
    def test_screen_sizes_and_label_fade(self):
        result = subprocess.run(
            [shutil.which('node'), str(Path(__file__).with_suffix('.js'))],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
