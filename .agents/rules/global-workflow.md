---
trigger: always_on
---

# Universal AI Team Rulebook (Windsurf-Friendly, Project-Agnostic)

> A reusable operational rule set for AI-assisted software teams.  
> No required repo structure. No mandated file paths. Enforces invariants, not folders.

---

## Rule 0 — Quality Over Speed

**Choose the correct design, not the quickest patch.**

- Prefer simple, readable architectures over cleverness.
- Avoid indirection (wrappers/shims/adapters) unless it clearly reduces complexity or risk.
- Make changes that improve the codebase’s clarity and maintainability.

---

## Rule 1 — Project Conventions and SSOT

Every project must define **one canonical “Single Source of Truth” (SSOT)** for planning and coordination (repo docs, ticketing system, ADR folder, etc.).

SSOT must cover (directly or by links):

- Current goals / phase
- Decisions (and decision history)
- Open questions
- Work tracking (TODOs/issues)
- How to run build/tests (or CI reference)

**Invariant:** planning + coordination live in SSOT, not scattered across chats.

### Precedence Order When Sources Conflict

1) **Explicit user instruction** (most recent, specific)  
2) **SSOT current phase / decision records**  
3) **Code + tests (observed behavior)**  
4) Older logs / comments / historical notes

If conflict remains, record it as a question (Rule 9).

---

## Rule 2 — Workstream Identity and Traceability

Track work by **workstream**, not by “conversation.”

A workstream is a coherent unit like a ticket, branch, PR, or deliverable.

### Workstream ID

Use a **globally unique ID**. Prefer, in order:

- PR number: `NK_PR1234_<slug>`
- Ticket ID: `NK_JIRA-123_<slug>`
- Otherwise: `NK_<YYYYMMDD>_<slug>_<rand4>`

### Traceability Tagging

When modifying code, add a short trace tag in nearby comments **only when it adds real value** (non-obvious changes, tricky behavior, or surprising constraints):

// NK_PR1234: why this change exists (one sentence)

text


Do not spam tags on trivial formatting or mechanical renames.

---

## Rule 3 — Capability Declaration (Reality Check)

At the start of a workstream, explicitly state what you can and cannot do **in this environment**, for example:

- Can/can’t run tests
- Can/can’t build
- Can/can’t access CI logs
- Can/can’t update external trackers

**Invariant:** Never claim you validated something you could not actually run or observe.

When you cannot run tests/build locally, compensate by:
- making smaller, safer changes,
- adding or improving tests where possible,
- being explicit about risk and what should be run in CI.

---

## Rule 4 — Before Starting Work

Before implementing:

1) Read SSOT (current phase, constraints, conventions)
2) Check recent decisions + open questions
3) Identify baseline expectations (tests, golden files, snapshots, contracts)
4) If possible: ensure the project builds and tests pass **before** changes
5) Create or update the workstream log (location per SSOT)

---

## Rule 5 — Behavioral Regression Protection

If the project defines **behavioral baselines** (golden files, snapshots, deterministic logs, API contract tests):

1) Run baseline checks (if possible) → must pass
2) Make changes
3) Re-run baseline checks
4) If output changes:
   - treat as **intentional change vs regression** decision
   - document rationale and update baselines **only with explicit user approval** (or per SSOT policy)

**Invariant:** Baselines are contracts. Don’t silently rewrite contracts.

---

## Rule 6 — Compatibility and Breaking Changes

Prefer clean architecture, but handle compatibility with intent.

### Internal Refactors (no external consumers)
- Prefer clean breaks and fix call sites directly.
- Avoid long-lived adapter layers.
- Document the refactoring scope and impact.
- Ensure all internal APIs are tested and covered by tests.
- Verify that refactored code maintains the same behavior and performance characteristics.
- Ensure that tests are updated to reflect the refactored code structure.
- Ensure that any documentation or examples are updated to reflect the refactored code.

### External Contracts (public API, SDK, CLI, data formats, plugins)
Breaking changes require a migration plan:

- Deprecation period or version bump (per SSOT policy / semver)
- Clear migration notes (what changed, why, how to update)
- Compatibility layer allowed **only** if it reduces user harm and has a removal plan

**Invariant:** Don’t “paper over” design flaws with permanent compatibility hacks.  
**Invariant:** But don’t break consumers casually — always plan for migration and document the path forward, including rollback options if needed.

---

## Rule 7 — No Dead Code (With Explicit Exceptions)

Remove:
- unused functions/modules,
- commented-out blocks,
- “kept for reference” code.

Allowed exceptions must be explicit and justified:
- required reference implementation for a spec,
- regulated/audit constraints,
- migration bridge with a defined removal trigger.

When an exception exists, add a comment:
// Reference-only: kept to validate spec X; remove after milestone Y


---

## Rule 8 — Modular Refactoring Standards

When splitting or reorganizing code:

- Each module owns its state; expose intentional APIs.
- Keep encapsulation strong (private by default).
- Avoid import graphs that are hard to reason about.
- Prefer smaller files/modules (human-readable; use project norms).
- Organize by responsibility (domain boundaries), not convenience.

---

## Rule 9 — Questions and Decision Records (Don’t Guess on Big Choices)

If any of the following occurs:
- requirements conflict,
- ambiguity affects architecture or user-facing behavior,
- a change could break contracts,
- something feels “off,”

then create a **Question** entry and/or a **Decision Record** in the project’s designated location.

### Question Template

- **Context:** what you observed
- **Decision needed:** what must be chosen
- **Options:** 2–3 viable paths
- **Recommendation:** your best pick + why
- **Risk:** what could go wrong if wrong

### Decision Record Template (ADR-lite)

- **Status:** proposed / accepted / superseded
- **Context:** constraints and drivers
- **Decision:** what we will do
- **Rationale:** why this is best now
- **Consequences:** tradeoffs + follow-ups

---

## Rule 10 — Incremental Delivery Over “Max Context Window”

Prefer **coherent, reviewable increments**:

- Don’t leave the repo half-broken unless that is the explicit plan.
- Make changes in checkpoints that can be validated (build/tests) when possible.
- If a task is large, split into sub-tasks with clear boundaries and sequence.

**Invariant:** Optimize for correctness + continuity, not sheer volume of edits.

---

## Rule 11 — Before Finishing (Handoff-Ready)

Before marking work complete:

1) Update workstream log with what changed and why
2) Ensure project builds (if possible)
3) Ensure tests pass (if possible)
4) Ensure baseline/golden checks pass (if applicable and possible)
5) Document known issues, risks, and next steps
6) Provide migration notes if any external behavior changed

### Handoff Checklist

- [ ] Workstream log updated
- [ ] Build validated (or explicitly not possible)
- [ ] Tests validated (or explicitly not possible)
- [ ] Baselines validated (or explicitly not possible)
- [ ] Breaking changes documented + migration notes (if applicable)
- [ ] Open questions/risks recorded in SSOT

---

## Rule 12 — TODO Tracking

Incomplete work must be tracked in the project’s designated system (TODO file, issues, tickets).

In code, use a consistent tag tied to the workstream:

// NK_<workstream_id>: brief description of incomplete work

**Invariant:** If it’s not tracked, it doesn’t exist.

---

## Rule 13 — Security, Privacy, and Secrets

- Never log or paste secrets (tokens, keys, credentials).
- Don’t copy production/user-sensitive data into logs, tests, or fixtures.
- Treat dependency additions/updates as security-sensitive:
  - prefer minimal dependencies,
  - record why it’s needed,
  - follow project vulnerability policy (SSOT).
- Avoid introducing insecure defaults (open network binds, disabled auth, permissive CORS, etc.).
- If you suspect a vulnerability, record it clearly and prioritize containment.

---

## Universal Quick Reference

| Concept | Meaning |
|---|---|
| SSOT | The single canonical place for plans/decisions/questions/work tracking |
| Workstream | A unit of work (ticket/branch/PR), not a chat thread |
| Baselines | Golden outputs/snapshots/contract tests that define “no regression” |
| Decision Record | A durable log of *why* a meaningful choice was made |
| Capability Declaration | What you can/can’t validate in the current environment |

---

## Optional Default Locations (Only If Project Has None)

If SSOT does not define locations, propose defaults (do not assume they exist):

- `docs/` for overview + phases
- `docs/decisions/` for decision records
- `docs/questions/` for open questions
- `docs/workstreams/` for workstream logs
- `TODO.md` or issue tracker for TODOs