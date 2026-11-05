Security review of the install-URL trust boundary in punt-kit PR #367 (bead pkit-fesz), branch fix/pkit-fesz-verify-readme-website.

Focus: the trusted-SHA-pin verification that decides whether a `curl | sh` install URL (in a product README and in public-website's projects.json `installCommand`) is trusted and current. The threat: an attacker-controlled or stale install URL being stamped "verified" by Phase 11, which would legitimize a `curl | sh` pointing at attacker content or a previous release.

Read: `git diff main..fix/pkit-fesz-verify-readme-website` and in full `src/punt_kit/phases/shared/readme_sha.py` (`classify_install_urls`, `find_pinned_shas`, `_url_prefix`, `bump`) and `src/punt_kit/phases/phase11_verify.py` (Check 7 README, Check 8 website, `VerificationCheck.matches_install_sha`).

Adversarially verify the trust boundary — try to construct an install URL that Phase 11 would classify as trusted+current but that curl would fetch from somewhere other than the exact `https://raw.githubusercontent.com/<owner>/<repo>/<sha>/install.sh`. Specifically probe:
- URL authority parsing: userinfo (`https://[REDACTED:email]/...`), lookalike hosts (`raw.githubusercontent.com.evil.com`), trusted string in path (`https://evil.example/raw.githubusercontent.com/...`), case/port/whitespace/`\t`/`\n`, scheme other than https, protocol-relative `//`, backslashes.
- The candidate-URL regex (`https://\S+/install\.sh`) — can a malicious URL evade being treated as a candidate (so `has_untrusted` stays False) while curl still runs it? e.g. multiple URLs, quoting, shell continuation.
- Commit-identity resolution (`git rev-parse <sha>^{commit}`) — any injection or ambiguous-ref risk from a hostile SHA string?
- Whether `has_untrusted` correctly forces failure regardless of trusted pins present.

Report concrete bypasses (input → why it passes) ranked by severity, or state clearly that the trust boundary holds. Do not fix — report.