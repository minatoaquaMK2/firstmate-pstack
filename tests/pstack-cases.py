
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


ROOT = Path(sys.argv.pop()).resolve()


@unittest.skipUnless(sys.platform == "darwin", "PR1 check containment requires macOS sandbox-exec")
class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fm-pstack-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.project = self.home / "project"
        self.wt = self.home / "worker"
        self.project.mkdir()
        self.env = dict(os.environ, FM_HOME=str(self.home), FM_STATE_OVERRIDE=str(self.home / "state"),
                        FM_DATA_OVERRIDE=str(self.home / "data"), CODEX_HOME=str(self.home / "codex"),
                        GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.com",
                        GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.com")
        self.git(self.project, "init", "-q", "-b", "main")
        (self.project / "app.py").write_text("def add(a, b):\n    return a - b\n")
        (self.project / ".gitignore").write_text("cached.py\n__pycache__/\n")
        (self.project / "verify.py").write_text("import runpy\nf=runpy.run_path('app.py')['add']\nassert f(2,3)==5, 'wrong addition'\n")
        self.git(self.project, "add", ".")
        self.git(self.project, "commit", "-qm", "baseline")
        self.git(self.project, "worktree", "add", "-qb", "fm/demo", str(self.wt))
        self.writer = str(uuid.uuid4())
        self.runtime(self.writer, "writer-model", "high", self.wt, "danger-full-access")
        self.env["CODEX_THREAD_ID"] = self.writer
        self.policy = {"schema_version": 1, "goal": "Add two numbers", "acceptance": ["add(2, 3) is 5"],
                       "implementation": {"playbook": "bug-fix", "model": "writer-model", "effort": "high"},
                       "checks": [{"id": "behavior", "argv": ["python3", "-I", "-S", "-B", "verify.py"],
                                   "cwd": ".", "timeout_seconds": 10}],
                       "review": {"required": True, "driver": "codex-exec", "model": "review-model", "effort": "high", "timeout_seconds": 10},
                       "permission_profile": "trusted-host"}
        self.input = self.home / "policy.json"
        self.input.write_text(json.dumps(self.policy))
        self.cli("prepare", "demo", "--input", self.input)
        digest = self.cli("bind", "demo", "--project", self.project, "--worktree", self.wt, "--branch", "fm/demo").stdout.strip()
        self.meta = self.home / "state/demo.meta"
        self.meta.parent.mkdir()
        self.meta.write_text(f"pipeline=pstack\nkind=ship\nmode=local-only\nyolo=off\nharness=codex\nbackend=herdr\n"
                             f"project={self.project}\nworktree={self.wt}\nbranch=fm/demo\nendpoint_task_id=demo\n"
                             f"spawn_gen=s{int(time.time())}.test\nherdr_session=fm-lab-test\nherdr_workspace_id=w1\n"
                             f"herdr_tab_id=w1:t1\nherdr_pane_id=w1:p1\nmodel=writer-model\neffort=high\n"
                             f"pipeline_contract_sha256={digest}\npipeline_permission_profile=trusted-host\n")
        self.fakebin = self.home / "fakebin"
        self.fakebin.mkdir()
        fake = self.fakebin / "codex"
        fake.write_text("#!" + sys.executable + "\n" + '''import sys,json,uuid,os,pathlib,datetime
args=sys.argv
thread=str(uuid.uuid4())
model=args[args.index('--model')+1]
report=pathlib.Path(args[args.index('--output-last-message')+1])
finding=os.environ.get('REVIEW_FINDING')
report.write_text(json.dumps({'verdict':'changes_required' if finding else 'passed','findings':[finding] if finding else [],'summary':'Mock review for portable tests'}))
directory=pathlib.Path(os.environ['CODEX_HOME'])/'sessions'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y/%m/%d')
directory.mkdir(parents=True,exist_ok=True)
runtime={'type':'turn_context','payload':{'model':model,'effort':'high','cwd':os.getcwd(),'sandbox_policy':{'type':'read-only'},'approval_policy':'never'}}
(directory/('rollout-'+thread+'.jsonl')).write_text(json.dumps({'type':'session_meta','payload':{'id':thread}})+'\\n'+json.dumps(runtime)+'\\n')
print(json.dumps({'type':'thread.started','thread_id':thread}))
print(json.dumps({'type':'turn.completed'}))
''')
        fake.chmod(0o755)
        self.env["PATH"] = str(self.fakebin) + os.pathsep + self.env["PATH"]
        self.pipeline = self.home / "data/demo/pipeline"

    def runtime(self, context, model, effort, cwd, sandbox):
        directory = Path(self.env["CODEX_HOME"]) / "sessions" / datetime.datetime.now(datetime.timezone.utc).strftime("%Y/%m/%d")
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ("rollout-" + context + ".jsonl")).write_text(
            json.dumps({"type": "session_meta", "payload": {"id": context}}) + "\n" +
            json.dumps({"type": "turn_context", "payload": {"model": model, "effort": effort, "cwd": str(cwd),
                       "sandbox_policy": {"type": sandbox}, "approval_policy": "never"}}) + "\n")

    def git(self, directory, *args):
        result = subprocess.run(["git", "-C", str(directory), *args], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def cli(self, *args, fail=None):
        result = subprocess.run([str(ROOT / "bin/fm-pstack.sh"), *map(str, args)], env=self.env, capture_output=True, text=True)
        if fail is None:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn(fail, result.stderr)
        return result

    def fix(self):
        (self.wt / "app.py").write_text("def add(a, b):\n    return a + b\n")
        self.git(self.wt, "add", "app.py")
        self.git(self.wt, "commit", "-qm", "correct addition")
        return self.git(self.wt, "rev-parse", "HEAD")

    def verified(self):
        run = self.cli("verify", "demo", "--candidate", self.fix()).stdout.strip()
        self.cli("review", "demo", "--run", run)
        self.cli("accept", "demo", "--run", run)
        return run

    def done(self, expect):
        script = '. "$1/bin/fm-classify-lib.sh"; . "$1/bin/fm-dod-lib.sh"; fm_dod_accept_ship_done ship local-only "$2" "$3" "done: ready in branch fm/demo" "$4" demo "$5"'
        result = subprocess.run(["bash", "-c", script, "bash", str(ROOT), str(self.wt), str(self.project), str(self.meta.parent), str(self.meta)],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, expect, result.stdout + result.stderr)

    def test_wrong_candidate_then_correct_and_idempotent_accept(self):
        (self.wt / "cached.py").write_text("def add(a,b): return a+b\n")
        self.cli("verify", "demo", "--candidate", self.git(self.wt, "rev-parse", "HEAD"), fail="check behavior failed")
        log = next(self.pipeline.glob("r*/checks/behavior.log")).read_text()
        self.assertIn("AssertionError: wrong addition", log)
        self.done(False)
        run = self.verified()
        receipt = (self.pipeline / run / "accepted.json").read_bytes()
        self.cli("accept", "demo", "--run", run)
        self.assertEqual(receipt, (self.pipeline / run / "accepted.json").read_bytes())
        self.done(True)

    def test_receipt_drives_done_without_pane_busy_signal(self):
        self.verified()
        (self.home / "state/demo.status").write_text("done: ready in branch fm/demo\n")
        command = [str(ROOT / "bin/fm-crew-state.sh"), "demo"]
        result = subprocess.run(command, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("state: done", result.stdout)
        self.meta.write_text(self.meta.read_text().replace("pipeline=pstack\n", ""))
        result = subprocess.run(command, env=self.env, capture_output=True, text=True)
        self.assertIn("state: blocked", result.stdout)

    def test_required_review_and_fabricated_writer(self):
        sha = self.fix()
        self.cli("verify", "demo", "--candidate", sha, "--writer-context", str(uuid.uuid4()), fail="exact Codex context")
        run = self.cli("verify", "demo", "--candidate", sha).stdout.strip()
        self.cli("accept", "demo", "--run", run, fail="result.json")
        self.env["REVIEW_FINDING"] = "Incorrect result"
        self.cli("review", "demo", "--run", run, fail="review requires changes")
        self.cli("accept", "demo", "--run", run, fail="review has blocking findings")

    def test_dirty_head_generation_and_contract_invalidate(self):
        self.verified()
        (self.wt / "untracked").write_text("dirty")
        self.cli("gate", "demo", fail="dirty")
        (self.wt / "untracked").unlink()
        self.meta.write_text(self.meta.read_text().replace("spawn_gen=s", "spawn_gen=s9"))
        self.cli("gate", "demo", fail="no accepted receipt")
        self.meta.write_text(self.meta.read_text().replace("spawn_gen=s9", "spawn_gen=s", 1))
        self.git(self.wt, "commit", "--amend", "--no-edit", "--date=2001-01-01T00:00:00Z")
        self.cli("gate", "demo", fail="no accepted receipt")

    def test_evidence_tampering_and_missing_check_fail(self):
        run = self.verified()
        path = self.pipeline / run / "checks/behavior.log"
        path.write_text(path.read_text() + "altered")
        self.cli("gate", "demo", fail="artifact changed")
        self.done(False)

    def test_unknown_policy_and_duplicate_checks_refused(self):
        self.policy["checks"].append(self.policy["checks"][0])
        self.input.write_text(json.dumps(self.policy))
        self.cli("prepare", "other", "--input", self.input, fail="duplicate check")
        self.policy["schema_version"] = True
        self.input.write_text(json.dumps(self.policy))
        self.cli("prepare", "third", "--input", self.input, fail="unknown schema")

    def test_unconfirmed_process_blocks_even_old_receipt(self):
        self.verified()
        (self.pipeline / "active.json").write_text('{"pid":123}')
        self.cli("gate", "demo", fail="termination is unconfirmed")
        self.done(False)

    def test_missing_pipeline_cannot_bypass_done(self):
        self.meta.write_text(self.meta.read_text().replace("pipeline=pstack\n", ""))
        self.done(False)

    def replace_policy(self, change):
        change(self.policy)
        (self.pipeline / "request.json").write_text(json.dumps(self.policy))
        contract_path = self.pipeline / "contract.json"
        contract = json.loads(contract_path.read_text())
        contract["policy"] = self.policy
        contract_path.write_text(json.dumps(contract))
        import hashlib
        digest = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        lines = self.meta.read_text().splitlines()
        self.meta.write_text("\n".join("pipeline_contract_sha256=" + digest if line.startswith("pipeline_contract_sha256=") else line for line in lines) + "\n")

    def check_source(self, code):
        self.fix()
        (self.wt / "verify.py").write_text(code)
        self.git(self.wt, "add", "verify.py")
        self.git(self.wt, "commit", "-qm", "exercise verifier failure")
        return self.git(self.wt, "rev-parse", "HEAD")

    def test_timeout_never_passes(self):
        self.replace_policy(lambda p: p["checks"][0].update(timeout_seconds=1))
        sha = self.check_source("import time; time.sleep(30)")
        self.cli("verify", "demo", "--candidate", sha, fail="blocked")
        self.done(False)

    def test_detached_descendants_are_denied(self):
        sha = self.check_source("import subprocess; subprocess.Popen(['python3','-c','import time; time.sleep(30)'], start_new_session=True)")
        self.cli("verify", "demo", "--candidate", sha, fail="failed")
        self.assertIn("Operation not permitted", next(self.pipeline.glob("r*/checks/behavior.log")).read_text())
        self.cli("gate", "demo", fail="no accepted receipt")

    def test_installed_entrypoint_is_rejected(self):
        self.policy["checks"][0]["argv"][4] = "/tmp/installed/check.py"
        self.input.write_text(json.dumps(self.policy))
        self.cli("prepare", "other", "--input", self.input, fail="within its root")

    def test_check_cannot_rewrite_the_tested_source(self):
        sha = self.check_source("open('app.py','w').write('def add(a,b): return a+b')")
        self.cli("verify", "demo", "--candidate", sha, fail="modified candidate source")
        self.done(False)

    def test_new_failure_supersedes_accepted_run(self):
        sha = self.check_source("import os,runpy; assert runpy.run_path('app.py')['add'](2,3)==5; assert not os.environ.get('FAIL_CHECK')")
        run = self.cli("verify", "demo", "--candidate", sha).stdout.strip()
        self.cli("review", "demo", "--run", run)
        self.cli("accept", "demo", "--run", run)
        self.env["FAIL_CHECK"] = "1"
        self.cli("verify", "demo", "--candidate", sha, fail="failed")
        self.cli("gate", "demo", fail="no accepted receipt")
        self.cli("accept", "demo", "--run", run, fail="superseded")

    def test_conflicting_brief_keys_are_rejected(self):
        import hashlib
        sha = hashlib.sha256(json.dumps(self.policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        brief = self.home / "brief.md"
        brief.write_text("Delivery contract: mode=local-only pipeline=pstack pipeline=unknown pipeline_request=" + sha)
        self.cli("preflight", "demo", "--brief", brief, fail="duplicate JSON key")

    def test_contract_and_review_tampering_are_refused(self):
        run = self.verified()
        report = self.pipeline / run / "review.md"
        report.write_text('{"verdict":"changes_required","findings":["bug"],"summary":"fail"}')
        self.cli("gate", "demo", fail="review report does not pass")
        self.policy["goal"] = "Changed contract"
        (self.pipeline / "request.json").write_text(json.dumps(self.policy))
        self.cli("gate", "demo", fail="contract policy changed")

    def test_brief_matrix_and_empty_pipeline_refused(self):
        command = [str(ROOT / "bin/fm-brief.sh")]
        for tail in [["--mode", "direct-PR", "--pipeline", "pstack"],
                     ["--mode", "no-mistakes", "--pipeline", "pstack"],
                     ["--scout", "--pipeline", "pstack"],
                     ["--mode", "local-only", "--pipeline="],
                     ["--mode", "local-only", "--pipeline", "unknown"]]:
            result = subprocess.run(command + ["invalid", "project"] + tail, env=self.env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, tail)
            self.assertFalse((self.home / "data/invalid/brief.md").exists())

    def test_path_escape_is_rejected(self):
        self.policy["checks"][0]["cwd"] = "../outside"
        self.input.write_text(json.dumps(self.policy))
        self.cli("prepare", "other", "--input", self.input, fail="within its root")


unittest.main(verbosity=2)
