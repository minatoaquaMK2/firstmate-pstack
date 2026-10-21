# Local pstack candidate verification

This opt-in lane delivers a verified local branch from one Ship worker running Codex in Herdr. Tasks without `--pipeline` keep their existing behavior. The lane never invokes no-mistakes.

## Supported first version

Use macOS with `sandbox-exec`, Python 3.9 or newer, Codex, Herdr, and the repository's supported Treehouse version. Checks must be committed Python source files executed as `python3 -I -S -B path.py`. They run from a fresh archive of the candidate commit. Use `runpy.run_path` with archive-relative paths to test local modules. Isolated mode excludes ambient import paths and installed site packages. The check sandbox denies forks, including detached processes. Subprocess-based test suites, services, submodules, symlinks, installed binaries, and deployments need a later verification driver.

The writer requires an explicit `trusted-host` permission profile. Constrained task status and inbox writes are not supported yet. No implicit permission fallback occurs. This is a cooperative local workflow; its records are not cryptographic attestation against a malicious host or worker with host access.

Only Ship, `local-only`, `codex`, `herdr`, and `yolo=off` are supported. Scout, promotion, relaunch, custom launch commands, and other delivery combinations are refused. Local merge is also refused, including after acceptance, until integration serialization is implemented. Review the delivered branch without publishing or merging it through this lane.

## Prepare and launch

Set `FM_HOME` to the intended operational home. Save a policy file with this shape, replacing the goal, acceptance, and model choices with the task's resolved settings:

```json
{
  "schema_version": 1,
  "goal": "Correct addition",
  "acceptance": ["add(2, 3) returns 5 and add(-2, 3) returns 1"],
  "implementation": {"playbook": "bug-fix", "model": "gpt-6.1-sol", "effort": "high"},
  "checks": [{"id": "behavior", "argv": ["python3", "-I", "-S", "-B", "verify.py"], "cwd": ".", "timeout_seconds": 30}],
  "review": {"required": true, "driver": "codex-exec", "model": "gpt-6-astra", "effort": "high", "timeout_seconds": 300},
  "permission_profile": "trusted-host"
}
```

All checks are required. Unknown keys, duplicate keys, and unsupported commands are rejected. An independent reviewer is required; a separate context using the same model is recorded accurately as independent but not cross-model.

```sh
bin/fm-pstack.sh doctor
bin/fm-brief.sh task-id project-name --mode local-only --pipeline pstack --pipeline-contract /absolute/policy.json
# Fill the generated task intent and implementation instructions.
bin/fm-spawn.sh task-id /absolute/project --mode local-only --pipeline pstack --harness codex --backend herdr --yolo off
```

Use the existing Herdr lab contract when testing runtime lifecycle changes. `doctor` checks tool versions, the pinned profile, and fork containment. Its `live_integration=not_probed` field means it has not launched a worker or validated model access. An unavailable reviewer blocks acceptance.

## Verify and accept

The worker commits its change and runs the absolute verification command from its launch instructions. `--candidate` requires the full current commit SHA. The worker identity comes from its actual `CODEX_THREAD_ID` and that exact context's runtime record. Model, effort, working directory, sandbox, and approval policy must match the contract.

```sh
bin/fm-pstack.sh verify task-id --candidate FULL_SHA
```

The command returns a run ID. The worker then pauses edits. Firstmate runs the next two commands on the host:

```sh
bin/fm-pstack.sh review task-id --run RUN_ID
bin/fm-pstack.sh accept task-id --run RUN_ID
bin/fm-pstack.sh status task-id
```

Review uses a fresh read-only Codex context with the configured model and effort. It inspects the change and whether the verifier actually covers acceptance. The result records the runtime identity, report, logs, and artifact hashes. The worker reports the existing ready-branch completion event only after acceptance.

Starting a new verification run supersedes previous acceptance, even for the same SHA. Dirty files, a changed commit, changed task generation, policy/profile changes, missing evidence, modified logs, review findings, or unconfirmed process termination prevent completion. Repeating acceptance for the same valid run returns the same receipt. Failed runs stay available for diagnosis.

## Records and recovery

Records live under `data/<task>/pipeline/`: `request.json`, the bound `contract.json`, `latest.json`, and one directory per run. Each run contains a checkpoint, sealed check result, independent review evidence, final result, and accepted receipt when valid. The result binds the candidate commit/tree, base commit, contract/profile digest, task generation, endpoint identity, check entrypoint, and interpreter hash.

`active.json` is a process-termination latch. If it remains after interruption, do not delete it and retry blindly. Confirm the recorded process group and every possible writer have stopped, preserve the evidence, and resolve recovery explicitly. Automatic relaunch and resume are outside this version.

The worker profile is selected only by the launch instructions. It is not registered globally or left in pooled worktree skill directories. Its minimal pinned upstream sources and centralized overrides live under `adapters/pstack-codex/`. Run `node scripts/generate-pstack-profile.mjs --check` to verify the lock; omit `--check` to restore pinned upstream files. Model choices belong in each task policy, not in the vendored upstream defaults.
