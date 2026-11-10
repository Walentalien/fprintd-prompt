import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import fprintd_prompt as fp
from tests import check_upstream


class TestUpstreamCompatibility(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parent / "fixtures" / "fprintd-1.94.5-msgids.json"
        self.msgids = json.loads(fixture.read_text(encoding="utf-8"))["msgids"]

    def header(self, msgids):
        entries = '\n'.join(f'N_({json.dumps(msgid)})' for msgid in msgids)
        return 'struct {} fingers[] = {\n' + entries + '\n};\nN_("retry message")'

    def test_supported_ids_match_independent_release_reference(self):
        self.assertCountEqual(fp.INITIAL_MSGIDS, self.msgids)

    def test_parser_only_reads_initial_prompt_table(self):
        self.assertEqual(check_upstream.initial_msgids(self.header(self.msgids)),
                         self.msgids)

    def test_checker_accepts_matching_header(self):
        with tempfile.TemporaryDirectory() as td:
            header = Path(td) / "fingerprint-strings.h"
            header.write_text(self.header(self.msgids), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(check_upstream.main([str(header)]), 0)

    def test_checker_reports_identifier_drift(self):
        changed = list(self.msgids)
        changed[0] = "Place your finger on the sensor"
        with tempfile.TemporaryDirectory() as td:
            header = Path(td) / "fingerprint-strings.h"
            header.write_text(self.header(changed), encoding="utf-8")
            with redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(check_upstream.main([str(header)]), 1)
            self.assertIn("Unsupported upstream prompt: " + changed[0], stderr.getvalue())
            self.assertIn("Prompt no longer in upstream: " + self.msgids[0], stderr.getvalue())

    def test_parser_rejects_missing_or_ambiguous_table(self):
        for source in ("<html>upstream unavailable</html>", self.header([]),
                       self.header([self.msgids[0], self.msgids[0]])):
            with self.subTest(source=source), self.assertRaises(ValueError):
                check_upstream.initial_msgids(source)
