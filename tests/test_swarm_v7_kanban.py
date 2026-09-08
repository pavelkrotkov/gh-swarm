import importlib, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).parents[1] / "skills" / "github-project-swarm" / "scripts"
sys.path.insert(0, str(SCRIPTS))
kb = importlib.import_module("swarm_v7_kanban")

H1 = "1" * 40


class FakeHermes:
    def __init__(self):
        self.calls = []
        self.by_key = {}
        self.tasks = {}
        self.next_id = 1

    def __call__(self, cmd, cwd, timeout):
        cmd = list(cmd)
        self.calls.append((cmd, cwd, timeout))
        if cmd == ["hermes", "--version"]: return "Hermes 0.test\n"
        if cmd == ["hermes", "kanban", "boards", "list", "--json"]: return "[]"
        if "--help" in cmd:
            if "create" in cmd: return "usage: create TITLE --body BODY --workspace WORKSPACE [--branch BRANCH] --idempotency-key KEY --max-retries N --max-runtime TIME [--assignee NAME] [--skill SKILL] --model MODEL [--provider PROVIDER]"
            return "usage: command TASK"
        action = cmd[4]
        if action == "create":
            key = cmd[cmd.index("--idempotency-key") + 1]
            if key not in self.by_key:
                tid = f"task-{self.next_id}"; self.next_id += 1; self.by_key[key] = tid; self.tasks[tid] = {"id": tid, "status": "todo", "runs": []}
            return json.dumps({"task": self.tasks[self.by_key[key]]})
        tid = cmd[5]
        if action == "show": return json.dumps({"task": self.tasks[tid]})
        if action == "runs": return json.dumps({"runs": self.tasks[tid]["runs"]})
        raise AssertionError(cmd)


def spec(**overrides):
    values = {"title":"work","body":"do one explicit operation","workspace":"dir:/tmp/repo-wt","model":"worker-model","assignee":"swarm-worker","skills":("ponytail",),"max_retries":2,"max_runtime":"20m"}; values.update(overrides); return kb.TaskSpec(**values)


class IdempotencyTests(unittest.TestCase):
    def test_same_attempt_key_recovers_same_task_without_duplicate(self):
        fake = FakeHermes(); adapter = kb.KanbanAdapter("board", "/repo", runner=fake); semantic = kb.semantic_key("s", 47, "implementation"); first = adapter.create(spec(), semantic); second = adapter.create(spec(), semantic); self.assertEqual(first, second); self.assertEqual(len(fake.tasks), 1)
    def test_crash_after_create_is_recovered_by_new_adapter_instance(self):
        fake = FakeHermes(); semantic = kb.semantic_key("s", 47, "implementation"); first = kb.KanbanAdapter("board", runner=fake).create(spec(), semantic); recovered = kb.KanbanAdapter("board", runner=fake).create(spec(), semantic); self.assertEqual(recovered, first); self.assertEqual(fake.by_key[semantic], first)
    def test_failed_a1_can_create_a2_without_new_semantic_identity(self):
        fake = FakeHermes(); adapter = kb.KanbanAdapter("board", runner=fake); semantic = kb.semantic_key("s", 47, "revision", head=H1); a1 = adapter.create(spec(), semantic); fake.tasks[a1]["status"] = "blocked"; self.assertEqual(adapter.observe(a1).outcome, kb.Outcome.FAILURE); a2 = adapter.create(spec(), semantic, 2); self.assertNotEqual(a1, a2); self.assertEqual(fake.by_key[f"{semantic}:a2"], a2); self.assertEqual(kb.attempt_key(semantic, 2), f"{semantic}:a2")
    def test_failed_execution_facts_allow_higher_layer_artifact_satisfaction(self):
        fake = FakeHermes(); adapter = kb.KanbanAdapter("board", runner=fake); semantic = kb.semantic_key("s", 47, "review", slot=1, head=H1); tid = adapter.create(spec(), semantic); fake.tasks[tid]["status"] = "archived"; facts = adapter.observe(tid); durable_artifact_exists = True; should_replay = facts.outcome is kb.Outcome.FAILURE and not durable_artifact_exists; self.assertFalse(should_replay); self.assertEqual(len(fake.tasks), 1)


class ContractTests(unittest.TestCase):
    def test_all_supported_statuses_map_explicitly_and_unknown_fails_closed(self):
        expected = {"todo":kb.Outcome.ACTIVE,"ready":kb.Outcome.ACTIVE,"running":kb.Outcome.ACTIVE,"review":kb.Outcome.ACTIVE,"done":kb.Outcome.SUCCESS,**{name:kb.Outcome.FAILURE for name in ("blocked","archived","triage")}}; fake = FakeHermes(); adapter = kb.KanbanAdapter("board", runner=fake); task_id = adapter.create(spec(), "semantic")
        for status, outcome in expected.items(): fake.tasks[task_id]["status"] = status; self.assertEqual(adapter.observe(task_id).outcome, outcome)
        fake.tasks[task_id]["status"] = "cancelled"
        with self.assertRaises(KeyError): adapter.observe(task_id)
    def test_assignee_and_run_record_are_execution_contract(self):
        fake=FakeHermes(); adapter=kb.KanbanAdapter("board",runner=fake); task_id=adapter.create(spec(),"semantic"); create=next(call[0] for call in fake.calls if "create" in call[0]); self.assertEqual(create[create.index("--assignee")+1],"swarm-worker"); self.assertFalse(adapter.observe(task_id).has_run); fake.tasks[task_id]["runs"].append({"id":"run-1"}); self.assertTrue(adapter.observe(task_id).has_run)
        with self.assertRaises(TypeError): kb.TaskSpec("work","body","dir:/tmp","model")
    def test_live_create_prepares_headless_worker_for_agents_md_and_github_auth(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); hermes=root/"hermes"; profile=hermes/"profiles"/"swarm-worker"; config=root/"gh"; profile.mkdir(parents=True); config.mkdir(); (config/"hosts.yml").write_text("oauth_token: secret\n"); (profile/".env").write_text("API_KEY=keep\nGH_CONFIG_DIR=/old\n")
            with patch.dict(os.environ,{"HERMES_HOME":str(hermes),"GH_CONFIG_DIR":str(config),"GH_TOKEN":"outer-secret"},clear=False),patch("swarm_v7_cli_process.subprocess.run",return_value=Mock(returncode=0)) as auth,patch.object(kb,"run_command",return_value='{"task":{"id":"task-1"}}') as run: task=kb.KanbanAdapter("board").create(spec(body="create root AGENTS.md"),"semantic")
            text=(profile/".env").read_text(); self.assertEqual(task,"task-1"); self.assertEqual(run.call_args_list[0].args[0],("hermes","-p","swarm-worker","config","set","security.protected_instruction_files","false")); self.assertIn("API_KEY=keep",text); self.assertIn(f"GH_CONFIG_DIR={config.resolve()}",text); self.assertNotIn("secret",text); self.assertEqual((profile/".env").stat().st_mode&0o777,0o600); self.assertEqual(auth.call_args.args[0],("gh","auth","status","--active","--hostname","github.com")); self.assertNotIn("GH_TOKEN",auth.call_args.kwargs["env"]); self.assertEqual(auth.call_args.kwargs["env"]["GH_CONFIG_DIR"],str(config.resolve()))
            (config/"hosts.yml").unlink()
            with patch.dict(os.environ,{"HERMES_HOME":str(hermes),"GH_CONFIG_DIR":str(config)},clear=False),patch("swarm_v7_cli_process.subprocess.run") as auth,patch.object(kb,"run_command") as run,self.assertRaisesRegex(RuntimeError,"gh auth login"): kb.KanbanAdapter("board").create(spec(),"blocked")
            auth.assert_not_called(); run.assert_not_called()
    def test_probe_records_version_and_checks_used_command_surface(self):
        fake = FakeHermes(); adapter = kb.KanbanAdapter("board", runner=fake); self.assertEqual(adapter.probe_contract(), "Hermes 0.test"); calls = [row[0] for row in fake.calls]; self.assertIn(["hermes", "kanban", "boards", "list", "--json"], calls); self.assertIn(["hermes", "kanban", "--board", "board", "create", "--help"], calls); self.assertIn(["hermes", "kanban", "--board", "board", "show", "--help"], calls)
    def test_invalid_dir_workspace_branch_is_rejected_before_hermes(self):
        fake = FakeHermes(); adapter = kb.KanbanAdapter("board", runner=fake)
        with self.assertRaises(ValueError): adapter.create(spec(branch="feature"), "semantic")
        self.assertEqual(fake.calls, [])
    def test_worktree_workspace_can_supply_branch_and_cards_have_no_parents(self):
        fake = FakeHermes(); adapter = kb.KanbanAdapter("board", runner=fake); adapter.create(spec(workspace="worktree:/tmp/repo", branch="feature"), "semantic"); create = next(call[0] for call in fake.calls if "create" in call[0]); self.assertIn("--branch", create); self.assertNotIn("--parent", create)
    def test_semantic_keys_use_durable_facts_and_full_head(self):
        self.assertEqual(kb.semantic_key("s", 47, "implementation"), "swarm:s:issue:47:implementation"); self.assertEqual(kb.semantic_key("s", 47, "review", slot=2, head=H1), f"swarm:s:issue:47:review:v2:{H1}"); self.assertEqual(kb.semantic_key("s", 47, "adjudication", head=H1), f"swarm:s:issue:47:adjudication:{H1}"); self.assertEqual(kb.semantic_key("s", 47, "revision", head=H1), f"swarm:s:issue:47:revision:{H1}")
        with self.assertRaises(ValueError): kb.semantic_key("s", 47, "review", slot=1, head="1234")


class QualityTests(unittest.TestCase):
    def test_execution_boundary_stays_consolidated_and_small(self):
        for name in ("swarm_v7_controller.py", "swarm_v7_kanban.py"):
            lines = [line for line in (SCRIPTS / name).read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]; self.assertLessEqual(len(lines), 150)
        builders = [candidate.name for candidate in SCRIPTS.glob("swarm_v7*.py") if '"hermes","kanban"' in candidate.read_text().replace(" ","")]; self.assertEqual(builders, ["swarm_v7_kanban.py"])


if __name__ == "__main__": unittest.main()