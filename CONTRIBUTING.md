# Atomic contribution workflow

The delivery unit is **one independently reviewable outcome**. Size is a signal,
not the definition: a runtime change may need its tests and documentation in the
same PR. If one part can be accepted, deferred, or reverted independently, consider
a separate issue and PR. Do not split a working change into broken intermediate PRs.

## Before implementation

1. Find or open an issue describing the problem, one desired outcome, acceptance
   checks, and scope boundaries. Do not create duplicate or retrospective issues
   merely to increase activity counts.
2. For larger requests, create separate issues for independent outcomes, state any
   dependencies, and use a branch per issue. Parallel work may proceed on disjoint
   outcomes; do not combine it into one omnibus PR at the end.

## Commit and open the PR

3. Make coherent commits that can be understood and checked individually. Keep
   relevant tests and docs with the behavior they explain. Reference the issue in
   commit messages. Do not use empty, cosmetic, or artificially fragmented commits
   to increase counts.
4. Open a focused PR linked to its issue. Explain why the change is needed, the
   resulting behavior, validation actually performed, and remaining limitations.
   Keep unrelated refactors and cleanup in their own justified work items.

## Review and merge

5. Have a separate reviewer or agent inspect the diff, its acceptance checks, and
   likely regressions. Record the actual findings, validation, and reviewed head
   SHA as a GitHub PR review. A summary in a chat alone is not the review record.
6. If an agent review is posted through the author's GitHub account, label it
   **agent review, posted by the author**. Identify the reviewing agent and report
   only what it checked. Use a COMMENT review; do not claim an independent GitHub
   account approval or impersonate a human reviewer.
7. Resolve blocking findings, then review any changed head again. Merge only with
   the final review recorded, required checks passing, and existing authorization.
   Honor branch protections; never bypass a required independent approval.
8. Link the merged PR to the issue and confirm the acceptance checks before closing
   it. Preserve meaningful atomic commits using the repository's permitted merge
   method. Report issue, PR, review, commit, and check links in the handoff.

## Accurate GitHub activity

Use the authenticated contributor's legitimate identity. Check the returned
commit's GitHub author association; an unlinked generic email may not receive
profile credit. Do not guess an email, alter global Git identity, forge co-authors,
or rewrite merged history for attribution or contribution counts. If attribution
cannot be verified, report the gap.

Useful issues, changes, and substantive reviews should produce the activity
record. Do not guarantee a graph increase or invent work to fill it. GitHub's
[contribution criteria](https://docs.github.com/en/account-and-profile/reference/profile-contributions-reference)
and [missing-contributions guidance](https://docs.github.com/en/account-and-profile/how-tos/contribution-settings/troubleshooting-missing-contributions)
describe attribution, branch requirements, and display delays.
