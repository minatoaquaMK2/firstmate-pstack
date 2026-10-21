# Codex worker adapter

This profile applies only inside a Firstmate Ship using the local-only pstack pipeline.
Firstmate owns task dispatch, worktree allocation, budgets, acceptance, recovery, and merge authority.
The implementation worker is the only application-code writer.

## Method overrides

Read the selected pinned feature, bug-fix, or refactoring playbook.
Apply these overrides before its instructions.
The worker implements code itself where upstream asks it to delegate implementation.
Before adding logic, state the smallest change and the affected boundary.
Load `principle-model-the-domain` and `principle-subtract-before-you-add` from the pinned resource directory when selecting the data structure or change scope.
Use the pinned `principle-prove-it-works` and `principle-test-behavior-not-implementation` for verification.
Load `principle-fix-root-causes` when diagnosing a bug and `principle-build-the-lever` when repeatable checking needs a small tool.

The upstream unconditional how and architect steps become conditional here.
For a familiar local edit, record one sentence explaining why research is unnecessary.
For an unfamiliar area or shared boundary, trace its real callers and ownership before changing it.
Use why only when history changes the decision.
Use architect or arena only for a consequential unresolved design choice.
Use interrogate when that design remains contested.
This minimal profile does not bundle those full multi-agent workflows.
If the task needs one, return a structured blocked reason so Firstmate can arrange a bounded investigation.
Do not invent missing tools or silently fetch an unpinned skill.

## Tool and helper mapping

Use Codex's native read, shell, and edit tools.
Cursor Task and implementation-delegate steps map to work by the current worker.
At most two native helpers may analyze or suggest changes, when the host supports them.
Helpers receive only their question and relevant files.
They return suggestions and never edit application files, comments, Git state, or fleet records.
Their read-only restriction is a collaboration rule, not an OS sandbox.

Firstmate runs required final review on the host using the contract-selected `codex-exec` driver through `fm-pstack.sh review`.
It starts a fresh read-only root context with an explicit model and records its real JSONL thread identity.
The writer pauses all edits during review.
Reviewing one's own change does not satisfy this requirement.
Same-model independent contexts are recorded as independent and not cross-model.
Missing review capability blocks completion.

AskQuestion becomes a `blocked:` or `needs-decision:` report to Firstmate through the task's existing status and inbox protocol.
Use the contract's resolved model and effort, not upstream role defaults.
Use the launch brief's absolute resource paths, not Cursor paths or slash commands.
Keep plans and decision notes in the task's pipeline artifact directory.
Read only this task's known logs, never unrelated sessions.

## Candidate and delivery

The check runner executes declared argv against a fresh Git archive of the candidate.
PR1 supports macOS Python source checks using `python3 -I -S -B path.py` from that archive.
The committed checker uses `runpy` with archive-relative paths; isolated mode excludes installed site packages and ambient imports.
The host sandbox denies process forks, including background or detached children.
A project needing subprocess-based checks requires a later containment driver.
PR1 requires an explicitly configured trusted-host writer because constrained task-channel writes are not supported.
It does not claim to verify a preexisting server, installed CLI, ignored build cache, submodule, or external deployment.
If acceptance needs those surfaces, report the verification gap to Firstmate.
Do not replace the declared check with an easier one.

After review finds a blocking defect, fix it, commit again, and create a new verification run.
Do not edit the contract, request, result, accepted receipt, or check logs to manufacture a pass.
Report the run ID to Firstmate for `accept`.
Candidate verification alone is not task completion.
After acceptance, report the ready branch through the existing local-only completion contract.

Do not invoke no-mistakes, pstack orchestrate, autopilot, babysit, shipping, fleet operations, or workspace cleanup.
Do not push, create a PR, merge, or restart a worker.
Local merge, relaunch, and promotion are refused in this initial lane until recovery ownership has been live-verified.
