# Writeups

Each phase ends with a short writeup landing here. The convention exists so that a year-from-now-you can re-read what was built in each phase and *why* the choices made sense — not just what changed in git.

## What belongs here

One file per phase, named `pN-<slug>.md` (e.g. `p0-scaffold.md`, `p1-data-eda.md`). A writeup answers, in plain prose:

- **What shipped.** The user-visible capability, not a file list.
- **Why these choices.** The decision points the phase resolved, and what was rejected.
- **What surprised you.** Things the plan didn't anticipate.
- **What's deferred.** Open questions handed to the next phase.

Keep it short — a single page is usually right. Longer means it should be split: detailed engineering notes belong in [`../solutions/`](../solutions/), API or data-shape contracts belong in [`../conventions/`](../conventions/).

## What does *not* belong here

- Step-by-step implementation logs (those are in git history).
- Stack snapshots or env-var contracts (those live in [`../conventions/stack.md`](../conventions/stack.md)).
- Reusable patterns (those live in [`../solutions/`](../solutions/)).

## Linking

Link from the writeup back to the relevant plan in `../plans/` and to any conventions or solutions docs the phase produced. The root [CLAUDE.md](../../CLAUDE.md) does not need to link each writeup individually — a pointer to this directory is enough.
