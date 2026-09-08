import importlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).parents[1] / "skills" / "github-project-swarm" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

github = importlib.import_module("swarm_v7_github")
process = importlib.import_module("swarm_v7_cli_process")


class Result:
    def __init__(self, payload, *, returncode=0, stderr=""):
        self.stdout = payload
        self.stderr = stderr
        self.returncode = returncode


class GhReaderTests(unittest.TestCase):
    def test_get_is_explicit_read_only_get_with_timeout(self):
        with patch.object(process.subprocess, "run", return_value=Result(json.dumps({"ok": True}))) as run:
            reader = github.GhReader(timeout_s=7)
            self.assertEqual(reader.get("repos/o/r/issues/1"), {"ok": True})
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:4], ["gh", "api", "--method", "GET"])
        self.assertNotIn("POST", cmd)
        self.assertNotIn("PATCH", cmd)
        self.assertNotIn("DELETE", cmd)
        self.assertEqual(run.call_args.kwargs["timeout"], 7)

    def test_graphql_uses_native_bounded_pagination(self):
        payload=json.dumps([{"data":{"ok":1}},{"data":{"ok":2}}])
        with patch.object(process.subprocess,"run",return_value=Result(payload)) as run:
            self.assertEqual(github.GhReader(timeout_s=7).graphql("query($endCursor:String){x}"),[{"ok":1},{"ok":2}])
        cmd=run.call_args.args[0]; self.assertIn("--paginate",cmd); self.assertIn("--slurp",cmd); self.assertEqual(run.call_args.kwargs["timeout"],7)

    def test_timeout_and_invalid_json_fail_closed(self):
        with patch.object(process.subprocess, "run", side_effect=subprocess.TimeoutExpired(["gh"], 3)):
            with self.assertRaisesRegex(github.GitHubReadError, "timed out after 3s"):
                github.GhReader(timeout_s=3).get("repos/o/r")
        with patch.object(process.subprocess, "run", return_value=Result("not-json")):
            with self.assertRaisesRegex(github.GitHubReadError, "invalid JSON"):
                github.GhReader().get("repos/o/r")

    def test_pagination_is_deterministic_and_bounded(self):
        reader = github.GhReader()
        pages = [[{"id": i} for i in range(100)], [{"id": 100}, "ignored"]]
        calls = []

        def get(endpoint):
            calls.append(endpoint)
            return pages[len(calls) - 1]

        reader.get = get
        rows = reader.list("repos/o/r/issues?state=open")
        self.assertEqual(len(rows), 101)
        self.assertEqual(calls, [
            "repos/o/r/issues?state=open&per_page=100&page=1",
            "repos/o/r/issues?state=open&per_page=100&page=2",
        ])

    def test_nonpositive_timeout_is_rejected_before_transport(self):
        for value in (0, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                github.GhReader(timeout_s=value)


if __name__ == "__main__":
    unittest.main()
