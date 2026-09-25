import importlib.util, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).parents[1]; MODULE=ROOT/"skills/github-project-swarm/scripts/migrate_controlled_reconcile.py"; spec=importlib.util.spec_from_file_location("migration",MODULE); migration=importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)

class FakeHost:
    def __init__(self,state,fail=None): self.state=state; self.fail=fail; self.calls=[]; self.legacy_states=[]; self.standard_active=True; self.standard_enabled=True; self.tasks=[{"id":"t1","status":"running","title":"worker","idempotency_key":"k1"}]
    def __call__(self,cmd,check=True):
        self.calls.append(tuple(cmd)); joined=" ".join(cmd)
        if self.fail and self.fail in joined: raise RuntimeError("injected failure")
        if cmd[:3]==["systemctl","--user","show"]:
            unit=cmd[3]; legacy=self.legacy_states.pop(0) if unit.endswith("controlled-reconcile.service") and self.legacy_states else "inactive"; active="active" if unit=="hermes-swarm-reconcile.timer" and self.standard_active else legacy if unit.endswith("controlled-reconcile.service") else "inactive"; enabled=unit=="hermes-swarm-reconcile.timer" and self.standard_enabled; return f"LoadState=loaded\nActiveState={active}\nUnitFileState={'enabled' if enabled else 'disabled'}\n"
        if cmd[:4]==["systemctl","--user","disable","--now"]: return ""
        if cmd==["hermes","swarm","--help"]: return "merge-policy reconcile validate"
        if cmd[:3]==["hermes","kanban","--board"] and cmd[-2:]==["create","--help"]: return "--completion-contract"
        if cmd[:3]==["hermes","kanban","--board"] and cmd[-2:]==["list","--json"]: return json.dumps(self.tasks)
        if cmd==["hermes","--version"]: return "Hermes test\n"
        if cmd[:3]==["hermes","swarm","pause"]: self._manifest(paused=True); return "paused\n"
        if cmd[:3]==["hermes","swarm","resume"]: self._manifest(paused=False); return "resumed\n"
        if cmd[:3]==["hermes","swarm","merge-policy"]: self._manifest(merge_policy=cmd[-1]); return "policy\n"
        if cmd[:4]==["hermes","swarm","reconcile","--dry-run"]: return json.dumps([{"observation":{"unsafe_reason":None}}])
        if cmd[:3]==["hermes","swarm","reconcile"]:
            raw=json.loads((self.state/"demo.json").read_text())
            with open(self.state/"demo.journal.jsonl","a",encoding="utf-8") as out:
                for issue in raw["issues"]: out.write(json.dumps({"issue":issue,"action":"start_implementation","pr_head":None,"error":None})+"\n")
            return ""
        if cmd[:3]==["hermes","swarm","activate"]: self.standard_active=True; self.standard_enabled=True; return "activated\n"
        if cmd[:3]==["hermes","swarm","validate"]: return "validate: ok\n"
        return ""
    def _manifest(self,**changes):
        path=self.state/"demo.json"; raw=json.loads(path.read_text()); raw.update(changes); path.write_text(json.dumps(raw))

def manifest(state):
    raw={"schema":7,"id":"demo","repo":"owner/repo","issues":[1],"paused":True,"merge_policy":"manual","runtime":{"board":"demo"}}; (state/"demo.json").write_text(json.dumps(raw))

class MigrationTests(unittest.TestCase):
    def test_preflight_reports_native_capabilities_schedulers_and_workers(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as runtime:
            state=Path(td); manifest(state); (Path(runtime)/"current").mkdir(); host=FakeHost(state)
            with patch.object(migration,"STATE",state),patch.object(migration,"RUNTIME_ROOT",Path(runtime)): report=migration.preflight("demo",host,lambda _:True)
        self.assertEqual(report["capabilities"],{"merge_policy":True,"completion_contract":True}); self.assertEqual(report["manifest"]["merge_policy"],"manual"); self.assertEqual(report["in_flight"][0]["id"],"t1"); self.assertEqual(report["units"]["hermes-swarm-reconcile.timer"]["ActiveState"],"active"); report["manifest"]["paused"]=False
        with self.assertRaisesRegex(RuntimeError,"to be paused"): migration._require_ready(report)
    def test_apply_uses_native_cutover_and_keeps_evidence(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as runtime:
            state=Path(td); manifest(state); script=state/"controlled_reconcile.py"; script.write_text("legacy\n"); (Path(runtime)/"current").mkdir(); host=FakeHost(state); host.standard_enabled=False; host.legacy_states=["active","active","inactive"]; probes={"count":0}
            def probe(_): probes["count"]+=1; return probes["count"]>1
            with patch.object(migration,"STATE",state),patch.object(migration,"HOME",Path(home)),patch.object(migration,"UNIT_DIR",state),patch.object(migration,"RUNTIME_ROOT",Path(runtime)):
                result=migration.migrate("demo","automatic",script,runner=host,sleep=lambda _:None,probe=probe); backup=Path(result["backup"]); self.assertTrue((backup/"demo.json").exists()); self.assertTrue((backup/"controlled_reconcile.py").exists())
            raw=json.loads((state/"demo.json").read_text())
        self.assertFalse(raw["paused"]); self.assertEqual(raw["merge_policy"],"automatic"); self.assertIn(("systemctl","--user","disable","--now","demo-controlled-reconcile.timer"),host.calls); self.assertIn(("hermes","swarm","activate"),host.calls); self.assertGreaterEqual(probes["count"],3)
    def test_mid_cutover_failure_pauses_without_reviving_legacy_path(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as runtime:
            state=Path(td); manifest(state); script=state/"controlled_reconcile.py"; script.write_text("legacy\n"); (Path(runtime)/"current").mkdir(); host=FakeHost(state,fail="swarm validate")
            with patch.object(migration,"STATE",state),patch.object(migration,"HOME",Path(home)),patch.object(migration,"UNIT_DIR",state),patch.object(migration,"RUNTIME_ROOT",Path(runtime)):
                with self.assertRaisesRegex(RuntimeError,"target swarm left paused"): migration.migrate("demo","automatic",script,runner=host,sleep=lambda _:None,probe=lambda _:True)
                backups=list((Path(home)/"swarm-migration-backups").glob("demo-*")); self.assertEqual(len(backups),1); self.assertTrue((backups[0]/"preflight.json").exists())
            raw=json.loads((state/"demo.json").read_text())
        self.assertTrue(raw["paused"]); self.assertFalse(any(call[:4]==("systemctl","--user","enable","--now") for call in host.calls))
    def test_verification_rejects_duplicate_task_or_merge_identity(self):
        with tempfile.TemporaryDirectory() as td:
            state=Path(td); manifest(state); host=FakeHost(state); host.tasks.append({"id":"t2","status":"ready","title":"dup","idempotency_key":"k1"})
            with patch.object(migration,"STATE",state):
                with self.assertRaisesRegex(RuntimeError,"duplicate Kanban"): migration._verify("demo",0,host,lambda _:None,1)
            host.tasks.pop(); (state/"demo.journal.jsonl").write_text("\n".join(json.dumps({"issue":1,"action":"merge","pr_head":"a"*40,"error":None}) for _ in range(2))+"\n")
            with patch.object(migration,"STATE",state):
                with self.assertRaisesRegex(RuntimeError,"duplicate exact-head"): migration._verify("demo",0,host,lambda _:None,1)

if __name__=="__main__": unittest.main()
