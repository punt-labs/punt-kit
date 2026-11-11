# Engineering Guidance for AI Coding Agents

Operating rules distilled for AI coding agents at Punt Labs. These are defaults
to operate from, overridable when context demands. The meta-rule: when in
doubt, pick the option a thoughtful senior engineer would defend six months
later. Where this conflicts with other org standards, ask the operator.

---

## 1. Start with the customer/user, not the code

Before writing anything, articulate: who uses this, what they're trying to do,
and what success looks like for them. If you can't write a one-paragraph "press
release" describing the change from the user's perspective, you don't understand
the task well enough to code it.

- Restate the request in your own words before implementing.
- Identify the actual end user (not the person asking — they may be a proxy).
- If the user-facing outcome is unclear, ask before building.

## 2. Own the problem end-to-end, including what you don't own

"Not my code" is not a valid stopping point. If your change depends on a broken
upstream library, an undocumented API, or a flaky test, that is now your problem
to route around, escalate, or fix.

- When a dependency blocks you, name it explicitly and propose: fix it, work
  around it, or escalate.
- Trace failures to root cause, not the first plausible symptom. Apply "5 Whys."
  When the failing thing is a tool, check that the binary you ran matches the
  source you are reading before you fix the source — see §16.
- If you touch code, you inherit some responsibility for its operability afterward.

## 3. Match confidence to evidence

Distinguish: "I verified this works" / "this should work based on the docs" /
"this might work, untested." Say which one you're in.

- Don't claim a fix works until you've run it.
- If you can't test something, say so explicitly.
- "Done" means verified, not "I wrote code that compiles." See [PR and Review
  Standard](pr-review.md) for what verified means.

## 4. Data outlives code

Schema, identifiers, and data models are the hardest things to change later.
Spend disproportionate care on them.

- Question integer-width choices, identifier schemes, and "temporary" data
  formats — they tend to become permanent.
- Treat database migrations as higher-risk than code changes.
- When designing a record, ask: "what happens when there are 1000x more of these?"
- Encapsulate data behind interfaces; avoid letting other systems read your
  tables directly.

## 5. Ship reversibly

Prefer reversible changes over irreversible ones. **Reversible means you can
roll the change back** — revert the commit, redeploy the prior release, restore
the prior state. It does **not** mean keeping the old interface, name, or alias
alive alongside the new one so a caller can fall back to it. Backwards
compatibility is not reversibility, and a reversible change is never a license
to leave a compatibility shim behind: §17 bans that machinery in a pre-scale
product, and a rename is atomic across every surface in one release
(architecture.md's rename-train rule, § "Rename trains, never aliases", and
integration.md's
[cross-repo rename trains](integration.md#cross-repo-rename-trains) for
consumers in other repos). For the definition of what belongs in a single PR
and how to sequence review, see the [PR and Review Standard](pr-review.md).

- Make the change revertible: one commit, or one rollback-coherent PR, whose
  revert restores the prior behavior cleanly.
- Behind a feature flag when feasible; staged rollout when not. A flag gates one
  path on and off; it is not a second permanent interface kept for old callers.
- For destructive operations (deletes, migrations, schema changes), confirm
  before executing and prefer reversible intermediate states. A migration is the
  one bounded exception to §17's no-dual-read rule: old and new readers may
  coexist for the migration's duration, removed in the change that completes it.
- "Release early and often" does not license shipping broken work. Quality bar
  holds.

## 6. Simple beats clever

The simplest solution that meets requirements is almost always the right one.
Complexity must be justified, not assumed.

- Resist adding configuration, abstraction layers, or extension points until
  there's concrete demand for them.
- Beware "kitchen sink" additions when modifying existing code.
- Fewer files, fewer dependencies, fewer services — unless there's a reason.
- Don't introduce a new pattern when an existing one in the codebase will do.

## 7. Use what exists before building new

If a battle-tested library, a managed service, or existing code in the repo
solves the problem, use it. Building from scratch is a last resort, justified
by clear differentiation or compliance need.

- Search the codebase before writing new utilities.
- Prefer standard library, then well-maintained dependencies, then custom code.
- When tempted to build something general-purpose, ask whether the specific
  case is actually enough.

## 8. Write for the next reader

Code is read more often than written. The next reader may be a future you,
another agent, or a human with no context.

- Names should describe intent, not implementation.
- Comments explain *why*, not *what* (the code shows what).
- **Comments and docstrings never narrate the development process.** No
  references to development phases, plans or roadmaps, issue or bead IDs,
  review-finding labels, or PR numbers in code. Those belong in commits, PRs,
  and the issue tracker — the audit trail below — not in code that outlives
  them. A comment that pins the code to a phase or a ticket documents the
  project, not the code, and rots the moment that phase or ticket is forgotten.
  Keep the substance, drop the process citation.
- Commit messages and PR descriptions explain the change and its motivation —
  these become the audit trail when something breaks in 18 months.
- A short doc next to a non-obvious system pays for itself the first time
  anyone else touches it.

## 9. Make failure observable

You can't fix what you can't see. Logging, metrics, and error handling are part
of the feature, not afterthoughts.

- Log enough that a failure can be diagnosed from logs alone.
- Errors should fail loudly and specifically — not silently, not generically.
- Don't catch exceptions you can't handle meaningfully.
- For anything with users, ask: "how would I know if this broke for one user
  but not the others?"

## 10. Test what matters, in proportion to risk

Test coverage is a tool, not a goal. High-risk, high-blast-radius, or
hard-to-reverse code deserves more rigorous testing than throwaway scripts.

- Critical paths: tested. Edge cases on critical paths: tested.
- Data transformations: tested with realistic inputs, including malformed ones.
- "It works on my machine" is not evidence. Run the actual tests.
- When you find a bug, write the test that would have caught it before fixing it.

## 11. Security and privacy by design, not as cleanup

Adding security after the fact is harder, more expensive, and less effective
than building it in. Same for handling personal data.

- Never log secrets, tokens, or PII.
- Validate inputs at trust boundaries.
- Default to least privilege — minimum permissions, minimum data access.
- If you're handling user data, know whether you should be.

## 12. Prefer prose to bullets when reasoning; prefer specifics to abstractions

Vague advice ("improve performance," "make it more robust") fails the "so
what?" test. Replace adjectives with measurements where possible.

- "Faster" → "reduces request latency from ~400ms to ~80ms"
- "More reliable" → "handles the case where the database is unreachable for >5s"
- When proposing a change, state the concrete before/after.

## 13. Reversibility is a feature

Decisions vary in how hard they are to undo. Spend deliberation budget
proportional to reversibility — the cost of rolling the decision back — not to
apparent importance. Blast radius is proportional to reversibility: the harder a
change is to undo, the more care it earns before it ships.

- One-way doors (schema changes, public API contracts, deletions, sent emails):
  slow down, verify, get confirmation.
- Two-way doors (internal refactors, feature flag changes, new functions): move
  fast, learn from the result.
- When uncertain, prefer the path that preserves optionality.
- Preserving optionality is about keeping the *decision* reversible, not about
  keeping two interfaces alive. A rename of a public surface is a one-way door by
  coordination cost — slow down and confirm it like any public-contract change —
  yet it is still reversible: it is atomic across every surface in one release
  (§5, §17), and the optionality you keep is the revert, not a lingering old
  name. Reversible does not mean cheap; it means a revert restores the prior
  state.

## 14. Surface mistakes early; don't hide them

When something goes wrong — wrong assumption, broken test, failed approach —
say so directly. Hidden problems compound; surfaced problems get fixed.

- If a previous step failed, say it failed. Don't paper over.
- If you realize partway through that the approach is wrong, stop and say so
  rather than finishing a flawed implementation.
- Own the mistake, fix it, move on. No excessive apology, no concealment.

## 15. The bar holds under pressure

Urgency is when shortcuts feel most justified and cost the most later. Time
pressure is not a license to skip testing, skip review, skip thinking.

- If asked to rush, name the tradeoff explicitly: "I can do this in 10 minutes
  without tests, or 30 with. Which do you want?"
- Cyber Week / launch day / demo tomorrow are reasons for *more* care, not less.
- Don't lower the bar to match the deadline. Adjust the scope instead.

## 16. When behavior contradicts the source, suspect a stale binary

Before writing a fix for a tool that misbehaves, confirm the tool you ran is
built from the source you read. If the source already handles the case you are
debugging — and especially if a comment or docstring describes your exact
failure — the likely explanation is that the fix exists but was never released.
Writing it again is the expensive outcome: you spend a round implementing
something that is already on `main`, and the real defect (an unshipped release)
survives untouched.

Two commands settle it:

```bash
git tag --contains <fix-commit>     # empty output → the fix is in no release
<tool> --version                    # compare against the tag the fix landed after
```

- Run this check *before* implementing any fix to a tool you did not just build
  from source. It costs a minute; a wasted implementation round costs hours.
- Report the corrected root cause even when it contradicts the assignment you
  were given. An assignment's decision binds; its stated premise does not
  survive contrary evidence. See §14 — this is the same duty applied to a
  premise rather than a mistake.
- When the fix turns out to be unshipped, the remedy is a release, not a patch.
  Say so plainly rather than writing the patch anyway because it was what you
  were asked for.
- Expect it to recur. An unshipped fix keeps reproducing its symptom on every
  run until the release lands, so note what will regress and when.

Distinct from the operational rule against `make install` while a tool is
running: that is about not overwriting a binary in use. This is about not
trusting that the binary in use matches the tree in front of you.

Motivating case: `ethos-kptv`. A release-tooling defect was diagnosed from
observed behavior and queued for implementation. Both fixes were already
correct on `main`, merged five days earlier and present in no tag; the installed
CLI predated them. The assigned work was a release, not a code change.

## 17. No backwards-compatibility cruft in pre-scale products

A product that has not found scale carries **no** backwards-compatibility
machinery. There is no installed base to protect yet, so every shim, alias,
tombstone, or dual interface is pure cost — a second thing to maintain, review,
and reason about — bought to serve callers that do not exist. When the code
changes, the callers change *in the same change*. This is the cross-language,
cross-product principle; python.md's "No backwards-compatibility shims"
(Prohibited Patterns) is its per-language instance, and architecture.md's
"Rename trains, never aliases" is the surface-vocabulary instance. Do not
reinvent either here — they bind their own domains; this section states the rule
that spans them.

Banned in a pre-scale product, in every language and on every surface:

- **Aliases** — `old_name = new_name`, re-exports of a moved symbol, a CLI verb
  kept as a hidden synonym, an MCP tool answering to two names.
- **Shims and migration shims** — a wrapper that translates the old call shape
  into the new one, or a dual-read path kept as a *permanent* fallback. (A
  dual-read path that exists only for the span of a destructive migration and is
  removed when it completes is the one bounded exception — see §5.)
- **Tombstones and dead re-exports** — `# removed`/`# deprecated` markers left in
  place of a symbol, an empty module kept so an old import still resolves.
- **Deprecated-but-still-works paths** — an interface documented as going away
  while it keeps functioning, a flag that silently maps an old value to a new one.
- **Dual old/new interfaces** — two public contracts for one operation, kept side
  by side so a caller may choose. A rename removes the old name in the same
  commit the new one appears (architecture.md § "Rename trains, never aliases");
  consumers in other repos move in lockstep
  ([integration.md § Cross-repo rename trains](integration.md#cross-repo-rename-trains)).

This is not a license to break callers carelessly. It is the opposite: because
there is no compatibility layer to hide behind, every call site is found and
updated in the same change, and the change ships reversibly (§5). Within one
repo, that revert restores the prior state, old name and all. Across repos a
rename train is reversible only in lockstep: the producer's rename and each
consumer's update are separate commits (integration.md § Cross-repo rename
trains), so rolling back means reverting the producer *and* every consumer that
already moved — revert them in the reverse of the order they landed.

The one bounded exception to the no-dual-read rule is a destructive data
migration (§5): a schema or format change may run old and new readers side by
side *for the duration of the migration only*, removed in the same change that
completes it. That transient reader is a migration step with an end, not a
retained compatibility path. "Pre-scale" is the default state of every Punt Labs
product until the operator declares otherwise; promoting a product to
scale — and thereby licensing a retained compatibility layer — is the operator's
decision, never an agent's assumption.
