# Sunday explanatory article route

The `sunday-article-v1` brief is a caller-supplied, locked decision about the topic and thesis. This article route is separate from daily discovery and post drafting. It drafts a 1,000–1,150-word explanatory article by default, then asks for narrative and factual review. A score or a valid JSON object does not prove the writing is good, the claims are true, or the article is ready to publish. No stage automatically publishes to LinkedIn.

The proposed explicit interface is `./bin/linkedin-os article --brief path/to/brief.json --models path/to/models.json --allow-model-egress` for a live model-assisted run, or `./bin/linkedin-os article --brief path/to/brief.json --dry-run` for local contract and routing inspection. The runtime implementation owns final option details; consult `--help`. Model egress requires the explicit flag. Review the output and publication decision separately. The article route does not alter the existing weekday or post workflow.

## Brief input

`src/authority_os/article_contract.py` exports `validate_brief(value)`, `validate_article(article, brief)`, `article_text(article, brief)`, and `article_hash(article, brief)`. Invalid input raises `WorkflowError`. The [synthetic example](../data/samples/article-brief.example.json) is a shape demonstration, not evidence for a publishable article.

| Field | Contract |
|---|---|
| `contract_version` | Exactly `sunday-article-v1`. |
| `topic_id`, `topic`, `thesis`, `technical_concept`, `worked_example` | Nonempty text; `topic_id` is a stable ID. The topic and thesis come from the human brief. |
| `reader` | Nonempty `audience`, `stake`, and `desired_outcome`. The stake should name the reader's concrete consequence before a technical mechanism. |
| `author` | Nonempty `name` and `byline`, with `attestations: [{id, text}]`. Only supplied attestation IDs can anchor first-person claims. |
| `sources` | Nonempty list of `{id, url, title, content}`; optional `version`, `retrieved_at`. `content` must contain the supplied passage; a URL alone is insufficient. IDs must be unique. |
| `claims` | Nonempty list of `{id, text, kind, source_ids}`; `kind` is `finding`, `author_attestation`, `interpretation`, or `proposal`. Optional `limitations`; `author_attestation` requires a known `attestation_id`. Every finding needs at least one known source ID. Other kinds may have empty source IDs, but any references must be known. IDs must be unique. |
| `voice_examples` | Optional list of nonempty text, used only to calibrate style. They cannot establish a fact or author experience. |
| `locked_title` | Optional nonempty exact title; if supplied, every article must retain it. Without it, the writer chooses a title, which subsequent editors should preserve. |
| `word_range` | Optional `{min, max}` with positive integer bounds, default `{min: 1000, max: 1150}`. |
| `resource` | Optional `{name, url, source_ids}` with nonempty known source IDs; optional `description`, `claim_ids`, `license`. A license requires a linked finding claim that references a resource source. The link structure does not verify availability or license truth. |

The validator normalizes defaults and detaches list/object values. Unknown fields, empty text, duplicate IDs, unknown references, and claims without required evidence links fail. It does not fetch URLs or check whether a source passage actually supports a claim. A factual reviewer must compare each sentence with the supplied evidence and disclose remaining uncertainty. Do not turn a source's association into a causal result or a short-term test into long-term retention. Attribute author experience only to actual author attestations. Verify a resource's described behavior, availability, and license with source passages before referring to it in a public article or companion post/comment.

## Article output

The article object has exactly `{topic_id, thesis, title, sections}`. Each section is `{id, heading, text, claim_ids}` with a stable unique ID, nonempty heading and body, and unique known claim IDs. Empty claim lists are allowed for prose that makes no evidence-bearing assertions. The article must preserve the exact brief `topic_id` and `thesis`, and `locked_title` when present. The body word count covers section `text` only; title, headings, and byline do not count. Obvious editorial placeholders fail. `article_text` renders the title, supplied byline, and section headings/bodies. `article_hash` hashes canonical normalized article and brief JSON, including supplied source content, author attestations, and byline; the hash identifies an article/input revision, not its factual status.

Write the reader's stake before technical detail, then teach one concept using the worked example. Make clear where source findings stop and interpretation begins; offer useful actions as proposals. A resource can appear within an explanation or a companion post/comment once supported by supplied evidence. There is no mechanical requirement to lead with the biggest number, mention the smallest number, use a fixed section sequence, or ban punctuation. Narrative review checks the reader's understanding and prose; factual review checks each used claim against supplied passages and attestations. Human editorial approval is still required before publication.
