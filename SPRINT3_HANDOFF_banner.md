# SPRINT3_HANDOFF.md — Archived Banner

**Manual edit instructions for SPRINT3_HANDOFF.md:**

Open the existing `SPRINT3_HANDOFF.md` and paste the block below at the
**very top** of the file, before the existing `# Sprint 3 Handoff —`
heading. Do not delete anything else in the file — it is kept for
historical context.

---

```markdown
> **ARCHIVED — January 2026.** Sprint 3 and Sprint 4 are both closed.
> This document was the *planning* note that opened Sprint 3 at the end
> of Sprint 2. It is preserved for historical context and to document
> the architectural decisions that were taken (ZeroMQ vs. asyncio, ASN.1
> vs. JSON, etc.) but the current project state is described in
> `PROGRESS.md` §10-§13. For the up-to-date project layout, run
> instructions, and empirical results, see `README.md`.
>
> Notable deviation from the Sprint 3 plan below:
> - We chose **in-process broker** (asyncio-free, queue-based) over
>   ZeroMQ. The ZeroMQ orchestration tax (7-10 days estimated) was
>   higher than the deployment-realism benefit at thesis scope. The
>   broker design holds CPMs as literal UPER-encoded bytes so swapping
>   the transport layer later requires no application-side changes.

---

```
