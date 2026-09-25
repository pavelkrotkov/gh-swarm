import json, os, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).parents[1]; sys.path.insert(0,str(ROOT/"tools"))
import migrate_controlled_reconcile as migration

def report(paused=True,policy="manual"):
    return {"release":"/runtime/releases/r1","capabilities":{"merge_policy":True,"completion_contract":True},"schedulers":{migration.LEGACY_TIMER:{"active":"inactive","enabled":"disabled"},migration.LEGACY_SERVICE:{"active":"inactive","enabled":"disabled"},migration.GLOBAL_TIMER:{"active":"inactive","enabled":"disabled"},migration.GLOBAL_SERVICE:{"active":"inactive","enabled":"disabled"}},"manifest":{"path":"/state/demo.json","schema":7,"repo":"owner/repo","paused":paused,"merge_policy":policy,"board":"demo","issues":[1]},"active_tasks":[],"in_flight_workers":[],"legacy_script":None}

class MigrationTests(unittest.TestCase):
    def test_preflight_reports_release_capabilities_scheduler_manifest_and_workers(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{"HERMES_SWARM_STATE_DIR":td,"AGENT_SKILLFLEET_RUNTIME":td}),patch.object(migration,"unit_state",return_value={"active":"inactive","enabled":"disabled"}),patch.object(migration,"active_tasks",return_value=[{"id":"t1","status":"running"}]),patch.object(migration,"run") as run:
            Path(td,"demo.json").write_text(json.dumps({"schema":7,"repo":"owner/repo","paused":True,"merge_policy":"manual","runtime":{"board":"demo"}})); Path(td,"current").mkdir(); run.side_effect=[SimpleNamespace(stdout="automatic\n"),SimpleNamespace(stdout="--completion-contract\n")]; got=migration.preflight("demo")
        self.assertEqual(got["manifest"]["repo"],"owner/repo"); self.assertTrue(all(got["capabilities"].values())); self.assertEqual(got["in_flight_workers"][0]["id"],"t1"); self.assertTrue(got["release"].endswith("current"))
    def test_wait_inactive_observes_inflight_legacy_reconcile(self):
        with patch.object(migration,"unit_state",side_effect=({"active":"active"},{"active":"deactivating"},{"active":"inactive"})) as state,patch.object(migration.time,"sleep"): migration.wait_inactive(migration.LEGACY_SERVICE,5)
        self.assertEqual(state.call_count,3)
    def test_reconcile_retries_native_lock_contention(self):
        skipped=SimpleNamespace(stdout="",stderr="demo: reconcile already running; skipped",returncode=0); done=SimpleNamespace(stdout="",stderr="",returncode=0)
        with patch.object(migration,"run",side_effect=(skipped,done)) as run,patch.object(migration.time,"sleep"): migration.reconcile_once("demo",5)
        self.assertEqual(run.call_count,2)
    def test_mid_cutover_failure_leaves_swarm_paused_and_never_restores_legacy_timer(self):
        commands=[]
        def fake_run(*args,**kwargs):
            commands.append(args)
            if args[:3]==("hermes","swarm","merge-policy"): raise RuntimeError("boom")
            return SimpleNamespace(stdout="",stderr="",returncode=0)
        with patch.object(migration,"preflight",return_value=report()),patch.object(migration,"run",side_effect=fake_run),patch.object(migration,"wait_inactive"),patch.object(migration,"backup",return_value=Path("/backup")):
            with self.assertRaisesRegex(RuntimeError,"boom"): migration.migrate("demo","automatic",5)
        self.assertEqual(commands[0],("systemctl","--user","disable","--now",migration.LEGACY_TIMER)); self.assertEqual(sum(cmd[:3]==("hermes","swarm","pause") for cmd in commands),2); self.assertFalse(any(cmd[:3]==("systemctl","--user","enable") and migration.LEGACY_TIMER in cmd for cmd in commands))
    def test_successful_cutover_runs_native_gate_pass_and_global_activation(self):
        commands=[]; final=report(False,"automatic"); final["schedulers"][migration.GLOBAL_TIMER]={"active":"active","enabled":"enabled"}
        def fake_run(*args,**kwargs): commands.append(args); return SimpleNamespace(stdout="",stderr="",returncode=0)
        with patch.object(migration,"preflight",side_effect=(report(),final)),patch.object(migration,"run",side_effect=fake_run),patch.object(migration,"wait_inactive"),patch.object(migration,"backup",return_value=Path("/backup")),patch.object(migration,"safe_dry_run",return_value=[]),patch.object(migration,"journal_offset",return_value=0),patch.object(migration,"new_journal",return_value=[{"issue":1,"action":None,"outcome":"noop"}]),patch.object(migration,"verify_no_duplicates",return_value={"active_tasks":0,"merge_requests":0}),patch.object(migration,"unit_state",return_value={"active":"inactive","enabled":"disabled"}): got=migration.migrate("demo","automatic",5)
        self.assertIn(("hermes","swarm","merge-policy","--name","demo","automatic"),commands); self.assertIn(("hermes","swarm","validate","--name","demo"),commands); self.assertIn(("hermes","swarm","resume","--name","demo"),commands); self.assertIn(("hermes","swarm","reconcile","--name","demo"),commands); self.assertIn(("hermes","swarm","activate"),commands); self.assertEqual(got["backup"],"/backup")
    def test_journal_slice_uses_byte_offset_with_utf8_history(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{"HERMES_SWARM_STATE_DIR":td}):
            path=Path(td,"demo.journal.jsonl"); path.write_text(json.dumps({"detail":"café"},ensure_ascii=False)+"\n",encoding="utf-8"); offset=path.stat().st_size
            with open(path,"a",encoding="utf-8") as out: out.write(json.dumps({"issue":1,"intent_key":"new"})+"\n")
            self.assertEqual(migration.new_journal("demo",offset),[{"issue":1,"intent_key":"new"}])
    def test_duplicate_proof_rejects_worker_and_merge_replays(self):
        rows=[{"action":"merge","outcome":"requested","intent_key":"m1"},{"action":"merge","outcome":"requested","intent_key":"m1"}]
        with patch.object(migration,"active_tasks",return_value=[{"idempotency_key":"t1"},{"idempotency_key":"t1"}]):
            with self.assertRaisesRegex(RuntimeError,"not provably unique"): migration.verify_no_duplicates("demo",rows)
    def test_postcheck_requires_single_native_timer_end_state(self):
        bad=report(False,"automatic"); bad["schedulers"][migration.GLOBAL_TIMER]={"active":"inactive","enabled":"enabled"}
        with self.assertRaisesRegex(RuntimeError,"global reconciliation timer"): migration._postcheck(bad,"automatic")
if __name__=="__main__": unittest.main()
