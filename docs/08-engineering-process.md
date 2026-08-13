# 08 · Engineering process

[← back to the overview](../README.md)

This is a solo-built system. That makes the process question sharper rather than softer:
with no reviewer to catch you, the discipline has to be structural, or it does not exist.

**212 design and plan documents** sit behind the code. Not as ceremony — as the mechanism
that makes the next decision cheaper than the last.

## Design before plan before code

Every non-trivial change moves through the same pipeline, and each stage has a different
job:

1. **Spec** — what is being built and *why this shape*, with the alternatives that were
   rejected and the reason. Approved before anything is planned.
2. **Plan** — the implementation, decomposed into independently testable tasks with their
   test cycles written out.
3. **Implementation** — task by task, tests first.
4. **Review** — an adversarial pass over the diff, with findings reproduced before they are
   acted on.
5. **Eval gate** — the merge barrier described in [chapter 06](06-quality.md).

Specs and plans are **historical evidence**, deliberately not rewritten to match what the
code became. When implementation deviates from a spec, the deviation is recorded as an
erratum in the spec rather than edited away. The trail is therefore a record of what was
believed at each point — which is the only version of a design document worth keeping.

## Documentation as a routed system

One fact has one authoritative home; everything else links to it. Phase status lives in the
roadmap, contracts in the architecture documents, procedures in runbooks, decisions in
specs, defects in bug reports, eval freshness in generated status.

The always-loaded index carries hard budgets — 300 lines, 3,000 words — enforced by a guard
in CI, along with the existence of every file it links to. That constraint is the whole
point: an index that can grow without limit stops being an index, and the budget forces
detail into the document that owns it.

This is not a preference about tidiness. Context is finite. A knowledge base that repeats
itself produces contradictory status, and contradictory status is worse than none.

## Defects get written down before they get fixed

Bug reports carry the symptom, the production evidence that localized it, the exact seam at
fault, the commit that introduced it, and the fix commit by SHA. Rejected findings are
recorded too, with the reasoning — so the same non-bug is not re-investigated in six months.

The habit this enforces: **reproduce before you act.** A finding from a review, a static
analyzer, or another agent is a hypothesis until it is reproduced. Acting on unverified
findings is how a codebase accumulates changes that fix nothing.

## AI-assisted delivery, directed rather than trusted

Much of this system was built with AI assistance. The interesting part is not that it was —
it is what had to be true for that to produce something trustworthy.

Every guard in [chapter 04](04-security.md) and every gate in [chapter 06](06-quality.md) is
a mechanism for not trusting an assertion — including the model's, and including mine. The
eval gate does not care who wrote the change. The capability guard does not care how
confident the decision was. `mypy --strict` over tests catches a test that asserts nothing
just as readily whether a human or a model wrote it.

Concretely, this means:

- **A deterministic oracle beats a review.** When a change is mechanical but large — a
  167-string translation across two locales — the specification is a test that walks the
  result and fails on any Cyrillic, not a checklist that someone promises to have followed.
- **Findings are reproduced, not relayed.** A reviewer's claim gets verified before it is
  repeated, let alone acted on.
- **Flakes are attributed with an A/B against a stashed baseline**, not by rerunning until
  green. Repetition alone does not distinguish "my change broke it" from "this host is
  loaded" — a controlled comparison does.
- **A guard is added at the seam, not at the symptom.** Repeated defects at the same
  boundary are a redesign signal, not an invitation to another local patch.

The claim worth making from all this is not "I used AI to go faster". It is that the
verification apparatus is strong enough that speed does not cost correctness — which is the
same apparatus a team would need, built by one person because there was no one else to
catch the mistakes.

---

[← operations](07-operations.md) · [next: roadmap →](09-roadmap.md)
