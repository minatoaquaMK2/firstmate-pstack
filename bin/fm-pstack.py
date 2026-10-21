#!/usr/bin/env python3
"""Local candidate evidence. No fleet scheduling, publication, or merge authority."""

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid


ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "adapters/pstack-codex"
IDENTITY_KEYS = ("endpoint_task_id", "spawn_gen", "worktree", "branch", "harness",
                 "backend", "herdr_session", "herdr_workspace_id", "herdr_tab_id", "herdr_pane_id")


class Refused(Exception):
    pass


def need(condition, message):
    if not condition:
        raise Refused(message)


def context_record(context, started):
    need(type(context) is str and re.fullmatch(r"[0-9a-f-]{36}", context), "invalid Codex context identity")
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    dates = {datetime.datetime.now(datetime.timezone.utc).date()}
    dates.add(datetime.datetime.fromtimestamp(started, datetime.timezone.utc).date())
    matches = set()
    for date in dates:
        for delta in (-1, 0, 1):
            directory = home / "sessions" / (date + datetime.timedelta(days=delta)).strftime("%Y/%m/%d")
            matches.update(directory.glob("*" + context + ".jsonl"))
    need(len(matches) == 1, "cannot locate this task's exact Codex context record")
    path = matches.pop()
    session = None
    turns = []
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "session_meta":
            session = event["payload"]
        if event.get("type") == "turn_context":
            turns.append(event["payload"])
    need(session and session.get("id") == context and turns, "Codex runtime identity is missing")
    turn = turns[-1]
    return {"context": context, "model": turn.get("model"), "effort": turn.get("effort"),
            "cwd": turn.get("cwd"), "sandbox_policy": turn.get("sandbox_policy"),
            "approval_policy": turn.get("approval_policy"), "source": str(path)}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def read_json(path):
    need(not path.is_symlink() and path.is_file(), "missing or nonregular record: " + str(path))
    return json.loads(path.read_text(), object_pairs_hook=pairs)


def write_json(path, value, sealed=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".record-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        if sealed:
            os.link(temporary, path)
            os.unlink(temporary)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def object_keys(value, required, optional=()):
    need(type(value) is dict, "expected an object")
    need(set(required) <= value.keys(), "missing fields: " + ", ".join(sorted(set(required) - value.keys())))
    need(value.keys() <= set(required) | set(optional), "unknown fields: " + ", ".join(sorted(value.keys() - set(required) - set(optional))))


def string(value):
    need(type(value) is str and value.strip() and "\x00" not in value, "expected a nonempty string")


def identifier(value):
    need(type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", value), "invalid identifier")
    return value


def relative(value):
    string(value)
    need(not Path(value).is_absolute() and ".." not in Path(value).parts, "path must stay within its root")
    return value


def confined(root, name):
    relative(name)
    root = root.resolve()
    target = root / name
    need(target.resolve().is_relative_to(root), "artifact path escapes run")
    cursor = target
    while cursor != root:
        need(not cursor.is_symlink(), "symlink evidence is not allowed")
        cursor = cursor.parent
    return target


def git(directory, *args):
    result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True)
    need(result.returncode == 0, "git " + " ".join(args[:2]) + " failed: " + result.stderr.strip())
    return result.stdout.strip()


def profile():
    lock = read_json(PROFILE / "pstack.lock.json")
    for name, expected in lock["files"].items():
        path = confined(PROFILE, name)
        need(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
             "pstack profile changed: " + name)
    return {"commit": lock["commit"], "version": lock["version"],
            "adapter_revision": lock["adapter_revision"], "sha256": digest(lock)}


def check_support():
    need(sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file(),
         "PR1 check containment requires macOS sandbox-exec")
    probe = subprocess.run(["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny process-fork)",
                            "python3", "-I", "-S", "-B", "-c",
                            "import os,sys\ntry: os.fork()\nexcept PermissionError: sys.exit(0)\nelse: sys.exit(1)"],
                           capture_output=True, timeout=10)
    need(probe.returncode == 0, "check process-fork containment probe failed")


def policy(value):
    object_keys(value, ("schema_version", "goal", "acceptance", "implementation", "checks", "review", "permission_profile"))
    need(type(value["schema_version"]) is int and value["schema_version"] == 1, "unknown schema version")
    string(value["goal"])
    need(type(value["acceptance"]) is list and value["acceptance"], "acceptance must not be empty")
    for item in value["acceptance"]:
        string(item)
    impl = value["implementation"]
    object_keys(impl, ("playbook", "model", "effort"))
    need(impl["playbook"] in ("feature", "bug-fix", "refactoring"), "unsupported playbook")
    string(impl["model"])
    need(impl["model"] not in ("inherit", "default"), "resolve the actual worker model before dispatch")
    need(impl["effort"] in ("low", "medium", "high", "xhigh", "max"), "unsupported effort")
    need(value["permission_profile"] == "trusted-host", "PR1 requires explicit trusted-host; constrained task status writes are not yet supported")
    checks = value["checks"]
    need(type(checks) is list and checks, "at least one required check is needed")
    seen = set()
    for check in checks:
        object_keys(check, ("id", "argv", "cwd", "timeout_seconds"))
        identifier(check["id"])
        need(check["id"] not in seen, "duplicate check ID")
        seen.add(check["id"])
        need(type(check["argv"]) is list and check["argv"], "empty check argv")
        for arg in check["argv"]:
            string(arg)
        need(len(check["argv"]) == 5 and check["argv"][:4] == ["python3", "-I", "-S", "-B"],
             "PR1 checks require python3 -I -S -B <candidate-relative.py>")
        relative(check["argv"][4])
        need(check["argv"][4].endswith(".py"), "check entrypoint must be Python source")
        relative(check["cwd"])
        need(type(check["timeout_seconds"]) is int and 1 <= check["timeout_seconds"] <= 3600, "invalid check timeout")
    review = value["review"]
    object_keys(review, ("required", "driver", "model", "effort", "timeout_seconds"))
    need(review["required"] is True, "PR1 requires independent review")
    need(review["driver"] == "codex-exec", "PR1 supports the explicit codex-exec review driver")
    string(review["model"])
    need(review["model"] not in ("inherit", "default"), "resolve the reviewer model before dispatch")
    need(review["effort"] in ("low", "medium", "high", "xhigh", "max"), "invalid review effort")
    need(type(review["timeout_seconds"]) is int and 1 <= review["timeout_seconds"] <= 3600, "invalid review timeout")
    return value


class Pipeline:
    def __init__(self, task):
        self.task = identifier(task)
        home = Path(os.environ.get("FM_HOME") or os.environ.get("FM_ROOT_OVERRIDE") or ROOT).resolve()
        self.state = Path(os.environ.get("FM_STATE_OVERRIDE") or home / "state").resolve()
        self.data = Path(os.environ.get("FM_DATA_OVERRIDE") or home / "data").resolve()
        self.directory = confined(self.data, task + "/pipeline")

    def metadata(self):
        result = {}
        for line in (self.state / (self.task + ".meta")).read_text().splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            need(key not in result, "duplicate metadata key: " + key)
            result[key] = value
        need(result.get("pipeline") == "pstack", "task is not a pstack task")
        need(result.get("kind") == "ship" and result.get("mode") == "local-only", "unsupported pstack task kind or mode")
        need(result.get("harness") == "codex" and result.get("backend") == "herdr", "pstack requires Codex and Herdr")
        need(result.get("yolo") == "off", "PR1 requires yolo=off")
        for key in IDENTITY_KEYS:
            string(result.get(key))
        need(result["endpoint_task_id"] == self.task, "endpoint task identity mismatch")
        return result

    def request(self):
        return policy(read_json(self.directory / "request.json"))

    def contract(self):
        value = read_json(self.directory / "contract.json")
        object_keys(value, ("schema_version", "task_id", "task_kind", "pipeline", "mode", "yolo", "project", "worktree", "branch", "base_commit", "policy", "profile"))
        need(type(value["schema_version"]) is int and value["schema_version"] == 1, "unknown contract schema")
        need(value["task_id"] == self.task and value["task_kind"] == "ship" and value["pipeline"] == "pstack"
             and value["mode"] == "local-only" and value["yolo"] == "off", "contract selection mismatch")
        policy(value["policy"])
        need(value["policy"] == self.request(), "contract policy changed")
        need(value["profile"] == profile(), "profile revision changed")
        return value

    def current(self, candidate=None):
        need(not (self.directory / "active.json").exists(), "blocked: pipeline process termination is unconfirmed or a check is still running")
        meta = self.metadata()
        contract = self.contract()
        wt = Path(meta["worktree"])
        need(wt.resolve() == Path(contract["worktree"]) and meta["branch"] == contract["branch"], "worktree or branch changed")
        need(Path(meta["project"]).resolve() == Path(contract["project"]), "project changed")
        need(meta.get("pipeline_contract_sha256") == digest(contract), "contract digest changed")
        need(meta.get("model") == contract["policy"]["implementation"]["model"], "worker model changed")
        need(meta.get("effort") == contract["policy"]["implementation"]["effort"], "worker effort changed")
        need(meta.get("pipeline_permission_profile") == contract["policy"]["permission_profile"], "launch permissions changed")
        need(git(wt, "symbolic-ref", "--short", "HEAD") == contract["branch"], "current branch changed")
        head = git(wt, "rev-parse", "HEAD")
        need(candidate is None or candidate == head, "candidate SHA is not current HEAD")
        need(not git(wt, "status", "--porcelain", "--untracked-files=all"), "candidate worktree is dirty")
        need(git(wt, "rev-parse", contract["base_commit"] + "^{commit}") == contract["base_commit"], "base commit missing")
        need(git(wt, "merge-base", contract["base_commit"], head) == contract["base_commit"], "candidate does not descend from base")
        return {"task_id": self.task, "identity": {key: meta[key] for key in IDENTITY_KEYS},
                "contract_sha256": digest(contract), "profile": profile(), "candidate_commit": head,
                "candidate_tree": git(wt, "rev-parse", "HEAD^{tree}"), "base_commit": contract["base_commit"]}

    @contextlib.contextmanager
    def lock(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with open(self.directory / ".lock", "a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused("another pipeline operation is running")
            need(not (self.directory / "active.json").exists(), "previous check termination is unconfirmed; reconcile its process group before retry")
            yield

    def run_directory(self, run):
        return confined(self.directory, identifier(run))

    def artifact(self, directory, name):
        path = confined(directory, name)
        need(path.is_file(), "missing or nonregular artifact: " + name)
        data = path.read_bytes()
        return {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def command(self, argv, cwd, seconds, output, stdin=None):
        started = now()
        status = "passed"
        with open(output, "wb") as log:
            active = self.directory / "active.json"
            write_json(active, {"phase": "starting", "argv": argv, "started_at": started})
            try:
                proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
                                        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            except OSError:
                active.unlink()
                raise
            try:
                write_json(active, {"pid": proc.pid, "pgid": proc.pid, "argv": argv, "started_at": started})
                proc.communicate(input=stdin.encode() if stdin else None, timeout=seconds)
                if proc.returncode != 0:
                    status = "failed"
            except subprocess.TimeoutExpired:
                status = "blocked"
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    if status == "passed":
                        status = "blocked"
                    time.sleep(0.2)
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                stopped = False
                for _ in range(30):
                    try:
                        os.killpg(proc.pid, 0)
                    except ProcessLookupError:
                        stopped = True
                        break
                    time.sleep(0.1)
                if stopped:
                    (self.directory / "active.json").unlink()
                else:
                    status = "blocked"
        return {"status": status, "exit_code": proc.returncode, "started_at": started, "ended_at": now()}

    def snapshot(self, directory, candidate):
        snapshot = directory / "candidate"
        snapshot.mkdir()
        need("160000 " not in git(self.metadata()["worktree"], "ls-tree", "-r", candidate), "PR1 refuses submodule verification")
        archive = directory / "candidate.tar"
        git(self.metadata()["worktree"], "archive", "--format=tar", "--output=" + str(archive), candidate)
        with tarfile.open(archive) as stream:
            for member in stream.getmembers():
                confined(snapshot, member.name)
                need(member.isfile() or member.isdir(), "PR1 source verification refuses symlinks and submodules")
            stream.extractall(snapshot)
        archive.unlink()
        return snapshot

    def verify(self, candidate, writer):
        string(writer)
        need(re.fullmatch(r"[0-9a-f]{40}", candidate), "candidate must be a full commit SHA")
        check_support()
        before = self.current(candidate)
        runtime = context_record(writer, int(self.metadata()["spawn_gen"].split(".")[0][1:]))
        need(runtime["model"] == self.metadata()["model"] and runtime["effort"] == self.metadata()["effort"]
             and Path(runtime["cwd"]).resolve() == Path(self.metadata()["worktree"]).resolve(), "writer runtime does not match the task")
        need(runtime["sandbox_policy"].get("type") == "danger-full-access" and runtime["approval_policy"] == "never", "writer runtime permissions differ from contract")
        run = "r" + uuid.uuid4().hex
        directory = self.run_directory(run)
        directory.mkdir()
        write_json(self.directory / "latest.json", {"run_id": run})
        result = {"schema_version": 1, "run_id": run, "binding": before, "writer_context": writer,
                  "writer_model": self.metadata()["model"], "checks": [], "artifacts": [],
                  "review": {"status": "pending"}, "outcome": "blocked"}
        write_json(directory / "writer-runtime.json", runtime)
        result["artifacts"].append(self.artifact(directory, "writer-runtime.json"))
        write_json(directory / "checkpoint.json", result)
        snapshot = self.snapshot(directory, candidate)
        sources = {str(p.relative_to(snapshot)): hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.rglob("*") if p.is_file()}
        for check in self.contract()["policy"]["checks"]:
            cwd = confined(snapshot, check["cwd"])
            need(cwd.is_dir(), "check cwd is missing")
            log_name = "checks/" + check["id"] + ".log"
            log = confined(directory, log_name)
            log.parent.mkdir(exist_ok=True)
            entry = dict(check)
            try:
                entrypoint = confined(cwd, check["argv"][4])
                need(entrypoint.is_file(), "check entrypoint is not in the candidate")
                need(sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file(),
                     "PR1 check containment requires macOS sandbox-exec")
                interpreter = Path(shutil.which("python3")).resolve()
                entry["source"] = {"entrypoint": str(entrypoint.relative_to(snapshot)),
                                   "sha256": hashlib.sha256(entrypoint.read_bytes()).hexdigest(),
                                   "interpreter": str(interpreter),
                                   "interpreter_sha256": hashlib.sha256(interpreter.read_bytes()).hexdigest()}
                argv = ["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny process-fork)",
                        str(interpreter), *check["argv"][1:]]
                entry.update(self.command(argv, cwd, check["timeout_seconds"], log))
            except OSError as error:
                log.write_text(str(error))
                entry.update(status="blocked", exit_code=None, started_at=now(), ended_at=now())
            entry["artifact"] = "git-archive:" + candidate
            result["checks"].append(entry)
            result["artifacts"].append(self.artifact(directory, log_name))
            write_json(directory / "checkpoint.json", result)
            need(all((snapshot / name).is_file() and hashlib.sha256((snapshot / name).read_bytes()).hexdigest() == sha for name, sha in sources.items()), "check modified candidate source")
            if entry["status"] != "passed":
                result["outcome"] = "changes_required" if entry["status"] == "failed" else "blocked"
                write_json(directory / "checks.json", result, sealed=True)
                raise Refused("check " + check["id"] + " " + entry["status"] + "; run=" + run)
            need(self.current(candidate) == before, "task identity changed while verifying")
        result["outcome"] = "candidate"
        write_json(directory / "checks.json", result, sealed=True)
        return run

    def evidence(self, run, require_review=True):
        directory = self.run_directory(run)
        result = read_json(directory / ("result.json" if require_review else "checks.json"))
        object_keys(result, ("schema_version", "run_id", "binding", "writer_context", "writer_model", "checks", "artifacts", "review", "outcome"))
        need(type(result["schema_version"]) is int and result["schema_version"] == 1 and result["run_id"] == run, "result schema or run mismatch")
        need(result["binding"] == self.current(), "result is stale for the current candidate or task identity")
        string(result["writer_context"])
        need(result["writer_model"] == self.metadata()["model"], "writer model mismatch")
        checks = self.contract()["policy"]["checks"]
        need(type(result["checks"]) is list and len(result["checks"]) == len(checks), "missing required checks")
        runtime = read_json(directory / "writer-runtime.json")
        need(runtime["context"] == result["writer_context"] and runtime["model"] == result["writer_model"], "writer provenance mismatch")
        expected_paths = ["writer-runtime.json"]
        for expected, actual in zip(checks, result["checks"]):
            object_keys(actual, tuple(expected) + ("status", "exit_code", "started_at", "ended_at", "artifact", "source"))
            need(all(actual[k] == v for k, v in expected.items()), "check differs from contract")
            need(actual["status"] == "passed" and type(actual["exit_code"]) is int and actual["exit_code"] == 0, "required check did not pass")
            need(actual["artifact"] == "git-archive:" + result["binding"]["candidate_commit"], "tested artifact mismatch")
            source = actual["source"]
            object_keys(source, ("entrypoint", "sha256", "interpreter", "interpreter_sha256"))
            expected_entry = str(Path(expected["cwd"]) / expected["argv"][4])
            need(source["entrypoint"] == expected_entry, "check entrypoint mismatch")
            content = subprocess.check_output(["git", "-C", self.metadata()["worktree"], "show",
                                               result["binding"]["candidate_commit"] + ":" + expected_entry])
            need(hashlib.sha256(content).hexdigest() == source["sha256"], "check source differs from candidate")
            interpreter = Path(source["interpreter"])
            need(interpreter.is_file() and hashlib.sha256(interpreter.read_bytes()).hexdigest() == source["interpreter_sha256"], "check interpreter changed")
            string(actual["started_at"])
            string(actual["ended_at"])
            expected_paths.append("checks/" + expected["id"] + ".log")
        if require_review:
            review = result["review"]
            object_keys(review, ("status", "context", "model", "candidate_commit", "independent_context", "cross_model", "findings"))
            need(review["status"] == "passed" and review["findings"] == [], "review has blocking findings")
            need(review["candidate_commit"] == result["binding"]["candidate_commit"], "review candidate mismatch")
            need(review["independent_context"] is True and review["context"] != result["writer_context"], "review is not independent")
            need(review["model"] == self.contract()["policy"]["review"]["model"], "review model mismatch")
            need(review["cross_model"] is (review["model"] != result["writer_model"]), "cross-model claim is wrong")
            events = [json.loads(line) for line in (directory / "review.jsonl").read_text().splitlines() if line.startswith("{")]
            contexts = [e["thread_id"] for e in events if e.get("type") == "thread.started"]
            need(contexts == [review["context"]] and any(e.get("type") == "turn.completed" for e in events), "review context provenance is missing")
            runtime = read_json(directory / "review-runtime.json")
            need(runtime["context"] == review["context"] and runtime["model"] == review["model"], "review runtime mismatch")
            need(runtime["sandbox_policy"] == {"type": "read-only"} and runtime["approval_policy"] == "never", "review permissions were not read-only")
            decision = read_json(directory / "review.md")
            need(decision.get("verdict") == "passed" and decision.get("findings") == [], "review report does not pass")
            need(not any(e.get("type") in ("turn.failed", "error") for e in events), "review runtime failed")
            expected_paths += ["review-prompt.txt", "review-launch.json", "review.jsonl", "review.md", "review-runtime.json"]
            need(result["outcome"] == "verified", "result is not verified")
        need(type(result["artifacts"]) is list and [a.get("path") for a in result["artifacts"]] == expected_paths, "artifact inventory mismatch")
        for artifact in result["artifacts"]:
            need(artifact == self.artifact(directory, artifact["path"]), "artifact changed: " + artifact["path"])
        return result

    def review(self, run):
        need(read_json(self.directory / "latest.json") == {"run_id": run}, "a newer verification superseded this run")
        result = self.evidence(run, require_review=False)
        directory = self.run_directory(run)
        need(result["review"] == {"status": "pending"} and not (directory / "result.json").exists() and not (directory / "review.jsonl").exists(), "review already attempted; create a new run")
        cfg = self.contract()["policy"]["review"]
        report = directory / "review.md"
        prompt = ("You are an independent reviewer. Do not edit files, run fleet commands, or delegate. "
                  "Review the committed change and verifier adequacy against this contract: " +
                  json.dumps(self.contract()) + ". Candidate: " + result["binding"]["candidate_commit"] +
                  ". Inspect git diff " + result["binding"]["base_commit"] + " HEAD. "
                  "Return JSON with verdict (passed or changes_required), findings (blocking findings only), and summary. "
                  "Do not assume passing tests imply correct behavior. Check that the checks exercise the stated acceptance.")
        argv = ["codex", "exec", "--ignore-user-config", "--disable", "hooks", "--sandbox", "read-only",
                "-c", 'approval_policy="never"', "--model", cfg["model"], "-c", 'model_reasoning_effort="' + cfg["effort"] + '"',
                "--json", "--output-schema", str(ROOT / "schemas/pstack-review.schema.json"),
                "--output-last-message", str(report), "-"]
        (directory / "review-prompt.txt").write_text(prompt)
        write_json(directory / "review-launch.json", {"argv": argv, "selected_model": cfg["model"], "selected_effort": cfg["effort"]})
        status = self.command(argv, self.metadata()["worktree"], cfg["timeout_seconds"], directory / "review.jsonl", prompt)
        need(status["status"] == "passed", "independent review failed or timed out")
        need(self.current() == result["binding"], "candidate changed during review")
        decision = read_json(report)
        object_keys(decision, ("verdict", "findings", "summary"))
        need(decision["verdict"] in ("passed", "changes_required") and type(decision["findings"]) is list, "invalid reviewer verdict")
        for finding in decision["findings"]:
            string(finding)
        string(decision["summary"])
        events = [json.loads(line) for line in (directory / "review.jsonl").read_text().splitlines() if line.startswith("{")]
        contexts = [e["thread_id"] for e in events if e.get("type") == "thread.started"]
        need(len(contexts) == 1 and contexts[0] != result["writer_context"], "independent context missing")
        runtime = context_record(contexts[0], time.time())
        need(runtime["model"] == cfg["model"] and runtime["effort"] == cfg["effort"], "review runtime model or effort differs from selection")
        write_json(directory / "review-runtime.json", runtime)
        result["review"] = {"status": decision["verdict"], "context": contexts[0], "model": cfg["model"],
                            "candidate_commit": result["binding"]["candidate_commit"], "independent_context": True,
                            "cross_model": cfg["model"] != result["writer_model"], "findings": decision["findings"]}
        result["artifacts"] += [self.artifact(directory, name) for name in ("review-prompt.txt", "review-launch.json", "review.jsonl", "review.md", "review-runtime.json")]
        result["outcome"] = "verified" if decision["verdict"] == "passed" and not decision["findings"] else "changes_required"
        write_json(directory / "result.json", result, sealed=True)
        need(result["outcome"] == "verified", "review requires changes; create a new candidate and run")
        self.evidence(run)
        return result["review"]

    def accept(self, run):
        need(read_json(self.directory / "latest.json") == {"run_id": run}, "a newer verification superseded this run")
        result = self.evidence(run)
        receipt = {"schema_version": 1, "run_id": run, "binding": result["binding"], "result_sha256": digest(result)}
        path = self.run_directory(run) / "accepted.json"
        if path.exists():
            existing = read_json(path)
            need({k: v for k, v in existing.items() if k != "accepted_at"} == receipt, "accepted run has conflicting result")
            return existing
        receipt["accepted_at"] = now()
        need(self.current() == result["binding"], "candidate changed during acceptance")
        write_json(path, receipt, sealed=True)
        return receipt

    def gate(self, expected=None):
        current = self.current(expected)
        latest = read_json(self.directory / "latest.json") if (self.directory / "latest.json").exists() else None
        for path in sorted(self.directory.glob("r*/accepted.json"), reverse=True):
            if latest != {"run_id": path.parent.name}:
                continue
            receipt = read_json(path)
            if receipt.get("binding") != current:
                continue
            object_keys(receipt, ("schema_version", "run_id", "binding", "result_sha256", "accepted_at"))
            need(type(receipt["schema_version"]) is int and receipt["schema_version"] == 1, "unknown receipt schema")
            need(receipt["run_id"] == path.parent.name, "receipt run mismatch")
            result = self.evidence(path.parent.name)
            need(receipt["result_sha256"] == digest(result), "accepted result changed")
            return receipt
        raise Refused("no accepted receipt for current candidate and task generation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "preflight", "bind", "verify", "review", "accept", "gate", "status", "doctor"))
    parser.add_argument("task", nargs="?")
    parser.add_argument("--project")
    parser.add_argument("--input")
    parser.add_argument("--brief")
    parser.add_argument("--worktree")
    parser.add_argument("--branch")
    parser.add_argument("--candidate")
    parser.add_argument("--run")
    parser.add_argument("--writer-context", default=os.environ.get("CODEX_THREAD_ID"))
    args = parser.parse_args()
    if args.command == "doctor":
        details = {"profile": profile(), "firstmate_commit": git(ROOT, "rev-parse", "HEAD"), "tools": {}}
        for tool in ("codex", "herdr", "treehouse"):
            need(shutil.which(tool), "missing dependency: " + tool)
            details["tools"][tool] = subprocess.check_output([tool, "--version"], text=True).strip()
        check_support()
        details["check_driver"] = "macOS isolated Python source, process-fork denied"
        details["writer_permissions"] = "explicit trusted-host only"
        details["live_integration"] = "not_probed"
        print(json.dumps(details))
        return
    pipeline = Pipeline(args.task)
    if args.command in ("gate", "status"):
        try:
            receipt = pipeline.gate(args.candidate)
            print(json.dumps(receipt if args.command == "gate" else {"pipeline": "pstack", "state": "candidate_verified", "candidate": receipt["binding"]["candidate_commit"], "run_id": receipt["run_id"]}))
        except (Refused, OSError, ValueError) as error:
            if args.command == "gate":
                raise
            print(json.dumps({"pipeline": "pstack", "state": "blocked", "reason": str(error)}))
        return
    with pipeline.lock():
        if args.command == "prepare":
            value = policy(read_json(Path(args.input)))
            need(not (pipeline.directory / "request.json").exists(), "pipeline request already exists")
            profile()
            write_json(pipeline.directory / "request.json", value, sealed=True)
            print(digest(value))
        elif args.command == "preflight":
            check_support()
            value = pipeline.request()
            lines = [line for line in Path(args.brief).read_text().splitlines() if line.startswith("Delivery contract:")]
            need(len(lines) == 1, "pstack requires exactly one delivery contract")
            tokens = lines[0].split()[2:]
            pairs(token.split("=", 1) for token in tokens if "=" in token)
            need(tokens.count("mode=local-only") == 1 and tokens.count("pipeline=pstack") == 1
                 and tokens.count("pipeline_request=" + digest(value)) == 1, "brief/CLI/request pipeline conflict")
            profile()
            print(json.dumps(value))
        elif args.command == "bind":
            wt, project = Path(args.worktree).resolve(), Path(args.project).resolve()
            need(wt != project and (wt / ".git").is_file(), "pstack requires an isolated worktree")
            need(not git(wt, "status", "--porcelain"), "initial worktree is dirty")
            value = {"schema_version": 1, "task_id": pipeline.task, "task_kind": "ship", "pipeline": "pstack",
                     "mode": "local-only", "yolo": "off", "project": str(project), "worktree": str(wt),
                     "branch": args.branch, "base_commit": git(wt, "rev-parse", "HEAD"), "policy": pipeline.request(), "profile": profile()}
            need(not (pipeline.directory / "contract.json").exists(), "contract already bound; automatic relaunch is not enabled")
            write_json(pipeline.directory / "contract.json", value, sealed=True)
            print(digest(value))
        elif args.command == "verify":
            print(pipeline.verify(args.candidate, args.writer_context))
        elif args.command == "review":
            print(json.dumps(pipeline.review(identifier(args.run))))
        elif args.command == "accept":
            print(json.dumps(pipeline.accept(identifier(args.run))))


if __name__ == "__main__":
    try:
        main()
    except (Refused, OSError, ValueError, KeyError, TypeError) as error:
        print("pstack: " + str(error), file=sys.stderr)
        sys.exit(1)
