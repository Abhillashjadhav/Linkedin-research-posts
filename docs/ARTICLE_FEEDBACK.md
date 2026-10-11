# Sunday article human feedback

After a completed live run is handed to a human editor, record the editor's actual decision separately from the model's review scores:

```sh
PYTHONPATH=src python -m authority_os.article_feedback record \
  --run outputs/2026-10-11-example \
  --decision accepted_light_edits \
  --edit-minutes 18.5 \
  --substantial-rewrites 0 \
  --hook-replacements 0 \
  --factual-corrections 1 \
  --notes 'Corrected a date before approval'
PYTHONPATH=src python -m authority_os.article_feedback summary
```

Decisions are `accepted_light_edits`, `accepted_substantial_edits`, or `rejected`. `accepted_light_edits` requires zero substantial rewrites and zero hook replacements. Factual corrections are counted separately: entering zero does not certify that the article is factually correct. Edit minutes may be fractional; all values must be finite and non-negative. `--notes` is optional and should contain only local editorial context.

The recorder requires a real `READY_FOR_HUMAN_REVIEW` run in ignored `outputs/` with `brief.json`, `article.json`, and `manifest.json`. It validates the article against the brief and checks the canonical article SHA-256 against the manifest's `artifact_sha256`. `FIXTURE_ONLY`, blocked, stale, or edited artifacts cannot be recorded. It stores the manifest's SHA-256 with the human observation. A run gets one immutable record in the ignored, owner-only `outputs/article-feedback/` directory. Repeating the exact observation is safe; changing its decision or measurements requires a new reviewed run rather than overwriting history. `--feedback-dir` can select another owner-only directory beneath `outputs/` for local tests or separated cohorts.

The summary reports observed reviewed runs as the denominator for the `accepted_light_edits` rate, decision counts, and medians for editor time, substantial rewrites, hook replacements, and factual corrections. Before the first record, a missing feedback directory yields zero reviewed runs with no rate or medians; summary does not create that directory. An existing unsafe directory or parent remains an error. These measurements make no reach projection and never grant factual approval, human approval, or publishing permission. No network or model calls occur in this feedback command.
