---
description: Run the site-verification harness against the deployed web URL. Reports status, internal-link, and expected-text checks.
allowed-tools: Bash(python tools/verify_site.py:*)
---

# /verify-site $ARGUMENTS

Run the agent-runnable site-verification harness against the deployed avird-2026 site.

## Steps

1. Determine the base URL, in priority order:
   - If `$ARGUMENTS` contains a URL, use it.
   - Else if the `WEB_URL` environment variable is set, use that.
   - Else ask the user for the deployed Railway URL.

2. Run: `python tools/verify_site.py --base-url <url>`

3. Print the harness's full output verbatim — the punch list is the artifact, do not summarize. End with the harness's exit status: 0 = green, non-zero = something is broken.

## What it checks

- `GET /` and `GET /about` both return 200.
- Every same-origin `<a href>` collected from those pages returns 200 when fetched. External links are skipped.
- `/` body contains `API: ok`. The degraded states `API: down` and `API: unreachable` are explicit failures even though the page itself rendered.
- `/about` body contains `About this project`.

To extend the assertion set, edit the config block at the top of `tools/verify_site.py`. Local fixture tests live in `tools/tests/test_verify_site.py` and run without network access.
