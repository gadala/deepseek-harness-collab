"""Public package checks; no network, secrets, model calls or external files."""
import json
from pathlib import Path
import re
import unittest
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


class ReleaseHygieneTests(unittest.TestCase):
    def test_relative_markdown_links_resolve(self):
        for path in ROOT.rglob('*.md'):
            if '.git' in path.parts:
                continue
            for link in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
                if '://' in link or link.startswith(('#', 'mailto:')):
                    continue
                destination = (path.parent / unquote(link.split('#', 1)[0])).resolve()
                self.assertTrue(destination.is_relative_to(ROOT), (path, link))
                self.assertTrue(destination.exists(), (path, link))

    def test_json_assets_parse(self):
        for path in (ROOT / 'assets').rglob('*.json'):
            self.assertIsInstance(json.loads(path.read_text(encoding='utf-8')), dict)

    def test_no_live_paths_identifiers_or_common_secret_formats(self):
        patterns = [
            r'[A-Za-z]:[\\/](?:Users|deepseek|dsh-data|C_Drive_Caches)[\\/]',
            r'session-[0-9a-f]{8}-[0-9a-f-]{27,}',
            r'gh[pousr]_[A-Za-z0-9]{20,}',
            r'github_pat_[A-Za-z0-9_]{20,}',
            r'sk-[A-Za-z0-9]{24,}',
            r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        ]
        for path in ROOT.rglob('*'):
            if not path.is_file() or '.git' in path.parts or path.suffix not in {'.md', '.py', '.json', '.yaml', '.yml'}:
                continue
            text = path.read_text(encoding='utf-8')
            for pattern in patterns:
                self.assertIsNone(re.search(pattern, text), f'{path.relative_to(ROOT)}: sensitive pattern found')

    def test_historical_summary_does_not_claim_live_verification(self):
        data = json.loads((ROOT / 'assets/native-subagent-probe-summary.json').read_text(encoding='utf-8'))
        self.assertFalse(data['rawTranscriptsIncluded'])
        self.assertFalse(data['currentEnvironmentVerified'])
        self.assertGreater(len(data['unverified']), 0)
        self.assertFalse((ROOT / 'assets/native-subagent-probe-20261005.json').exists())


if __name__ == '__main__':
    unittest.main()
