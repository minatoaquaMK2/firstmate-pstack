---
name: pstack-worker
description: Load only when a Firstmate Ship launch brief explicitly selects pipeline=pstack and supplies its contract path.
---

# Firstmate pstack worker

Read the exact task contract named by the launch brief, then read [the adapter](../adapter.md).
Read only the selected upstream playbook under `../upstream/pstack/skills/poteto-mode/playbooks/`.
The adapter overrides that playbook's delegation, mandatory research, review, and delivery steps.
Do not load this profile for a Scout, Supervisor, or ordinary Codex task.

Implement the contract's bounded goal in the assigned worktree.
Commit the candidate before final verification.
Use the command in the launch brief to verify, then report the run ID to Firstmate.
Firstmate runs the host-side independent review and acceptance commands while the writer pauses edits.
Only an accepted candidate can enter the ordinary local ready-branch handoff.
