# Human judgment

LinkedIn Authority OS is a decision-support workflow. It does not substitute model output for the author's expertise, proof approval, editorial judgement, or permission to publish.

This document names every material point where personal expertise or a manual decision enters the implemented flow.

## Before drafting

| Human input | What the person decides | What the runtime does |
| --- | --- | --- |
| Source selection | Which sources are relevant enough to import and whether the body was actually read. | Validates public URLs, source metadata, body provenance, and deduplication. It does not collect live sources. |
| Recent-work context | Which prior post text may be used to assess topic repetition. | Computes bounded similarity only when an explicit private file is supplied. Otherwise reports `not-evaluated`. |
| Target reader | Which reader the author intends to help or influence. | Requires the value in live strategy input and uses it in relevance checks. |
| Reader problem | Which concrete unresolved decision matters to that reader. | Carries the value into the brief and checks material overlap. |
| Core hypothesis | Which mechanism is worth testing or explaining. | Preserves the supplied hypothesis; it does not manufacture one from topic popularity. |
| Product decision | Which falsifiable action or trade-off the work should make useful. | Requires the decision and checks that final candidates materially reflect it. |
| Authority statement | Which demonstrated expertise the work should establish. | Requires the statement and applies the authority-conversion gate. |
| Strategic goal | Whether the intended outcome is Reach, Authority, or Opportunity. | Applies the selected route and keeps outcome measurement within that goal. |
| Output format | Which downstream container, if any, fits the work. | Stores format separately and never infers it from goal. |

The five live strategy fields are supplied together in a private JSON object:

```json
{
  "target_reader": "A specific professional audience",
  "reader_problem": "The decision that audience cannot make yet",
  "core_hypothesis": "The evidence-backed mechanism to examine",
  "product_decision": "The practical, falsifiable action",
  "authority_statement": "The demonstrated expertise this work should establish"
}
```

Completeness is validated. Quality is not assumed. The author must decide whether the fields are accurate, useful, and consistent with actual expertise.

## Proof and personal claims

The runtime can verify that a proof manifest has the exact schema, points to a distinct non-empty regular local file, and exposes only a bounded public-safe projection. It cannot decide that the artefact is genuine, representative, lawful to disclose, or appropriate for the audience.

Manual proof approval covers:

- the artefact selected as proof;
- the exact public claim associated with it;
- every personal or ownership attestation;
- confidentiality, customer, employer, and third-party obligations; and
- whether any proof should be used at all.

No personal incident, ownership statement, result, customer, credential, or private experience should enter a candidate without explicit support and approval. A structurally valid proof manifest is not human approval.

## Personal voice

The voice guide and performance-pattern anchors are reconstructed assets. They can calibrate mechanics such as paragraph length, directness, narrative shape, and banned language. They are not evidence of personal experience and are not automatically an approved description of the author's voice.

**Manual approval is required for every personal voice section before it is treated as authoritative or reused in a public portfolio narrative.** The author should confirm that the guidance sounds natural, that cited performance patterns are accurate, and that no reconstructed phrase is presented as an original quotation.

The Writer may propose phrasing. It may not decide that phrasing is personally authentic.

## Drafting, critique, and gates

The Writer creates three candidates. The Critic scores five aspects of expression. Deterministic gates block candidates that fail the implemented minimum conditions. None of those stages decides:

- whether the argument represents the author's considered view;
- whether source support is true, current, and fairly characterised;
- whether an approved proof claim should be disclosed;
- whether the voice is recognisably personal;
- whether an eligible candidate is the best editorial choice;
- whether a candidate needs a manual edit that changes its claims; or
- whether the work should be abandoned.

Any manual edit after package generation requires renewed claim, proof, and factual review. The saved gate result applies to the packaged text, not to a later rewrite.

## Human-review package

The package organises a decision; it does not make one. The reviewer must inspect all six files and then:

1. verify each factual claim against the cited source body;
2. confirm that any proof artefact and public-safe wording are approved;
3. check that the target reader, problem, hypothesis, decision, and authority statement remain coherent;
4. assess personal voice manually;
5. compare all candidates rather than accepting the score leader by default;
6. reject or edit any candidate that is technically eligible but editorially weak; and
7. make the final publication decision outside this repository.

The manifest deliberately remains `NOT_APPROVED`, `DISABLED`, and `manual_fact_verification_required=true` after package creation.

## Publication and performance

Publication is a separate human-controlled action. The runtime has no publishing or approval-recording command.

After publication, a person chooses the eligible package candidate that was actually used, confirms the external publication timestamp, and records each observation. The runtime validates checkpoint windows and metric shape; it cannot retrieve platform analytics, decide whether a metric was entered correctly, or infer missing paid performance as zero.

## Weekly learning

The weekly review compares only mature, comparable observations and reports evidence gaps. Human interpretation is still required to decide:

- whether an observed outcome matters commercially or professionally;
- whether the package goal was the right goal;
- whether external events explain the result;
- whether a hook or structure is worth testing again;
- whether a Critic axis deserves review; and
- whether the available sample is sufficient for any change.

The report does not establish causation and cannot mutate strategy, prompts, voice assets, the Critic rubric, approval state, or publishing state.
