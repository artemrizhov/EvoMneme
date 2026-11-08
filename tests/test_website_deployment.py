"""Keep operator details out of reusable builds; use synthetic configuration."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('website_build', ROOT / 'scripts/build_website.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class DeploymentTests(unittest.TestCase):
    def test_default_and_configured_artifacts(self):
        config = dict(measurement_id='G-EXAMPLE000', operator_name='Example <Operator>',
                      operator_email='privacy@example.invalid',
                      site_url='https://artemrizhov.github.io/EvoMneme/',
                      search_verification='example-verification')
        for configured in (False, True):
            with self.subTest(configured=configured), tempfile.TemporaryDirectory(dir=ROOT) as folder:
                output = Path(folder)
                with patch.object(builder, 'OUTPUT', output), patch.dict(os.environ,
                        {'WEBSITE_DEPLOYMENT_CONFIG': json.dumps(config) if configured else ''}):
                    builder.build()
                privacy = (output / 'privacy/index.html').read_text()
                self.assertNotIn('{{', privacy)
                self.assertEqual((output / 'deployment-config.js').exists(), configured)
                if configured:
                    self.assertIn('Example &lt;Operator&gt;', privacy)
                    self.assertIn('privacy@example.invalid', privacy)
                    self.assertIn('evomneme_ga_EXAMPLE000', privacy)
                else:
                    self.assertIn('no optional analytics enabled', privacy)
                    self.assertNotIn('mailto:', privacy)
                for name in ('index.html', 'demo/index.html', 'privacy/index.html'):
                    html = (output / name).read_text()
                    self.assertEqual('deployment-config.js' in html, configured)
                    if configured:
                        self.assertLess(html.index('deployment-config.js'), html.index('analytics.js'))
                    else:
                        self.assertNotIn('data-cookie-settings', html)
                landing = (output / 'index.html').read_text()
                self.assertEqual('example-verification' in landing, configured)

    def test_invalid_config_fails_before_build(self):
        for value in ('[]', '{"measurement_id":"G-EXAMPLE000"}'):
            with patch.dict(os.environ, {'WEBSITE_DEPLOYMENT_CONFIG': value}):
                with self.assertRaises(ValueError):
                    builder.deployment_config()


if __name__ == '__main__':
    unittest.main()
