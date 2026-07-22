# LinkedIn Authority OS — review package preview

> **Synthetic preview.** This file demonstrates the package shape only. Its research, claims, candidates, and scores are invented fixtures and must not be published as factual content.

## Package status

| Field | Value |
|---|---|
| Goal | Authority |
| Format | Text post |
| Evidence mode | Synthetic fixture |
| Model egress | Disabled |
| Publishing | Disabled |
| Human verification | Required |
| Recommendation | `BLOCKED — synthetic evidence` |

## Strategy brief

**Audience:** product and engineering leaders responsible for AI reliability.

**Intended outcome:** earn saves and useful discussion by explaining why a plausible final answer can still conceal a broken agent trajectory.

**Evidence-backed angle:** evaluate the path—retrieval, tool choice, and decision steps—not only the final answer.

**Evidence limitation:** the example failure and performance numbers are synthetic. No production or external claim may be inferred from this package.

## Candidate 1 — direct thesis

An AI agent can return the right answer for the wrong reason.

That is not a harmless evaluation edge case. The incorrect retrieval or tool path can later leak into advice, actions, or policy decisions even when the final yes/no looks correct.

Answer-only grading asks: “Did the result look right?”

Trajectory evaluation asks:

- Did the system retrieve the correct source?
- Did it use the permitted tool?
- Did each decision follow from recorded evidence?
- Would the same path remain safe on the next case?

The final answer is one checkpoint. The path is the product.

**Claim IDs:** `C1`, `C2`

## Candidate 2 — failure story

A return agent retrieves the wrong policy document.

The customer is still eligible, so the final answer says “yes.” An answer-only eval passes the case.

But the wrong policy recommends mail-back instead of an in-store return. The verdict looked correct; the customer instruction was wrong.

This is why teams need to evaluate the agent trajectory, not only the final response.

**Claim IDs:** `C1`, `C3`

## Candidate 3 — operating principle

For agentic products, “correct output” is an incomplete release gate.

A stronger gate verifies three layers:

1. the final decision;
2. the customer-facing action or method;
3. the retrieval and tool path that produced it.

A system that passes layer one while failing layers two or three is not reliable. It is lucky.

**Claim IDs:** `C1`, `C4`

## Critic evaluation

| Candidate | Evidence fidelity | Specificity | Usefulness | Voice fit | Discussion potential | Result |
|---|---:|---:|---:|---:|---:|---|
| Candidate 1 | 5 | 4 | 5 | 4 | 4 | Strongest structure |
| Candidate 2 | 4 | 5 | 5 | 4 | 5 | Strongest opening |
| Candidate 3 | 5 | 4 | 4 | 4 | 3 | Useful but less distinctive |

The critic may rank candidates. It cannot approve publication.

## Deterministic gates

| Gate | Result | Explanation |
|---|---|---|
| Authority fit | `PASS` | The content teaches a repeatable product principle |
| Claim mapping | `PASS` | Every factual statement carries a claim ID |
| Citation structure | `PASS` | Claims map to synthetic source records |
| Honesty | `PASS` | Synthetic evidence is labelled repeatedly |
| Public-safe proof | `FAIL` | No validated public evidence manifest exists |
| Publication eligibility | `BLOCKED` | Synthetic fixtures can never become live evidence |

## Final package decision

**No candidate is recommended for publication.**

The package is structurally complete, but its evidence mode is synthetic. A live run would require source-backed research, a public-safe proof manifest where relevant, manual factual verification, and explicit human selection outside the system.

## What this preview demonstrates

- strategy goal and content format are separate decisions;
- exactly three candidates remain visible for review;
- claims retain identifiers and evidence boundaries;
- critic scores cannot approve content;
- deterministic gates can block an otherwise polished draft;
- the final artifact explains both the recommendation and the reason for blocking.
