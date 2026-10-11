# Reviewed article delivery package

`package_reviewed_article(run_dir, *, output_dir=None, model_config=None,
invoker=invoke_structured, live_consent=False, assets=None, article_url=None)`
creates a private `run_dir/package/` by default. Both the run and any custom
package destination must stay inside the repository's ignored `outputs/`
tree; the destination must be a child of the supplied run. The run directory must contain
`article.json`, `brief.json`, `review.json`, `article-claim-map.json`, and
`manifest.json`. The last three
must contain the canonical `article_contract.article_hash(article, brief)`
under `artifact_sha256` and matching `READY_FOR_HUMAN_REVIEW` or `FIXTURE_ONLY`
statuses. A changed article or inconsistent review blocks packaging.
An explicit repository call to action in the reviewed article also blocks
packaging; the optional supplied resource remains an attributed source entry.

The CLI entry point accepts `article-package --run <private-run>` and optional
`--output`, `--assets <JSON-mapping-path>`, `--article-url <HTTPS-URL>`, and
for live runs `--model-config <JSON-path> --allow-model-egress`. The model
config JSON contains `runtime`, `model`, and `reasoning` for the companion
stages. Fixture runs need no model configuration.

The reviewed article has `topic_id`, `title`, `thesis`, and ordered `sections`
with `id`, `heading`, `text`, and `claim_ids`. The brief carries the same
`topic_id`, source records with `id`, `title`, and public HTTPS `url`, and
claims with `id` and `source_ids`. IDs must resolve to the brief's ledger.
This mapping supports traceability; a source link does not establish semantic
truth. A `FIXTURE_ONLY` run generates conspicuously synthetic post/comment
copy without model calls. Live copy requires `live_consent=True` and a
`ModelConfig`, then the configured `invoke_structured` callable generates
post and first-comment text with claim IDs and independently reviews each
derived text for claim coverage and source references. Any new or unreviewed
claim, missing coverage, or failed alignment blocks copy review eligibility.
The optional supplied resource enters both copy and review context. Its URL
may appear only with a cited finding linked to its supplied sources. Its
license is listed only when supplied in the validated brief; an invented
license alongside its URL is rejected.
The generated evaluation binds each copy review to its exact text and article
hash. Neither path approves or publishes content.

The output contains `article.md`, `post.md`, `source-comment.md`, `sources.md`,
escaped `article.html`, `evaluation.json`, `manifest.json`, and
`final-package.md`. The Markdown and HTML article preserve the reviewed title,
byline, headings and body; neither inserts a new thesis paragraph. On rerun,
all existing managed file hashes are checked before any replacement, so a
human-edited post or article is preserved and packaging stops. Only managed
names are atomically replaced. The
manifest records hashes for generated content and source inputs. It leaves
`article_url` null until the caller explicitly supplies a public HTTPS URL;
the package does not create a visible draft link or invent one.

Optional `assets` is a local path mapping from `cover` to a 1920 × 1080
PNG/JPEG, or `inline:<section-id>` to a 1200 × 900 PNG/JPEG. Image headers
and dimensions are checked. Provided image bytes are copied into the package.
Inline images are also embedded as data URLs in HTML at their section; the
cover stays separate from the article body for platform upload. The
evaluation distinguishes an asset plan from provided image bytes and marks
the full package `INCOMPLETE` when there are no assets. Image placement does
not certify rendering, reuse rights, or clipboard compatibility. Human
review, actual image rendering, and final platform checks remain outside
this local packaging operation.
