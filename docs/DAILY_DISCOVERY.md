# Daily authority discovery

The discovery command fixes the missing front half of the workflow and makes topic momentum auditable before any thesis is written:

```text
10 current conversation topics
→ observed cross-platform momentum ranking
→ top 5 + separate authority-fit score
→ body-verified source evidence
→ three authority theses
→ strict thesis scoring
→ human thesis selection
→ existing high-bar draft workflow
```

It does not publish, select a thesis, or claim that a public-web proxy is an exact X/Twitter ranking.

## One-time setup

Copy the public template into the ignored private directory and replace every example with reviewed, public-safe information:

```bash
mkdir -p data/private
cp data/samples/authority-profile.example.json data/private/authority-profile.json
chmod 700 data/private
chmod 600 data/private/authority-profile.json
```

The profile contains:

- the audience you want to reach;
- the idea you want associated with your name;
- a bounded inventory of real proof;
- topics and theses you do not want repeated.

## Discover ranked topics and three theses

```bash
./bin/linkedin-os discover \
  --profile data/private/authority-profile.json \
  --days 7 \
  --week-slot 3 \
  --allow-web-research \
  --allow-model-egress
```

In the default Monday, Wednesday, Thursday, Friday publishing cadence, Thursday
is weekly slot 3. This discovery path produces authority posts, so it accepts
the two authority slots only: 2 and 3.

The public-web Scout runs through Codex with live native web search as its only enabled model tool. It cannot use shell, browser automation, apps, plugins, subagents, local files, repository-writing tools, private data, credentials, or authenticated services. Public search-index snippets from X/Twitter or LinkedIn may contribute momentum evidence only when visible without authentication. The private authority profile reaches only zero-web Codex scoring/thesis stages after explicit model-egress consent.

## Conversation momentum

Before source selection, the Scout returns exactly ten distinct candidate conversations. Each candidate is measured on five axes from public evidence:

1. conversation breadth;
2. engagement strength;
3. acceleration;
4. cross-platform confirmation;
5. freshness.

The Scout may use free public evidence observable through web search/fetch, including Google Trends pages, Hacker News, Reddit, YouTube, publicly indexed X/Twitter or LinkedIn results, primary-source launches/research, and reputable reporting.

Scout does not choose the 0–5 scores. It returns auditable `basis_value` observations; Python applies a fixed local rubric. Breadth is based on independent source/author count, engagement on visible interaction counts (excluding raw views), acceleration on comparable percentage growth, cross-platform confirmation on distinct surfaces, and freshness on the age of the newest substantive signal.

If engagement, acceleration, or another basis cannot be verified, the axis is `UNKNOWN` with `basis_value=null`; missing data is never converted to a fabricated zero. Four observed axes are required for a usable lower-bound momentum score. A partial result is printed as `N+/25 (4/5 axes observed)` and carries at most MEDIUM confidence. Python computes every axis score, total, threshold decision, and ranking locally from the returned observations.

The output is explicitly labelled **observed cross-platform conversation momentum**. It is not an exact X/Twitter post count, engagement ranking, or claim that a topic is “#1 hottest”. Exact X ranking would require direct quantitative X data, which this free public-web workflow does not use.

The current authority-discovery floor is **14/25**. The code also locks a **20/25** reach/topical floor for a future reach-specific route. At least three topics must clear the active floor before thesis generation proceeds. A low-momentum topic cannot be promoted above a higher-momentum topic merely because it has stronger proof fit.

The top five are printed and saved before thesis generation with:

- momentum rank and total;
- confidence (`HIGH`, `MEDIUM`, or `LOW`);
- observed platforms and representative URLs;
- missing-signal caveats;
- a separate authority-fit score out of 25.

Authority fit never changes the momentum order. It answers a different question: whether the topic gives this author a differentiated, evidence-backed product decision worth publishing.

The momentum package is written under ignored `data/private/daily-discovery/.../momentum.json` before the thesis stage. If thesis articulation later fails, the topic research remains available for human inspection instead of disappearing with the failed thesis set.

## Evidence and thesis generation

After momentum ranking, the source Scout body-verifies three to seven defensible signals from the eligible top topics. It prefers official engineering/research blogs, documentation, papers, repositories, government/standards sources, incident reports, and reputable reporting.

The command then:

1. generates three differentiated theses per search cycle;
2. scores audience fit, distinctiveness, decision strength, proof fit, and simplicity;
3. retains each thesis that independently scores at least 23/25 with simplicity at least 4/5, without allowing weaker siblings to discard it;
4. stores the evidence, momentum ranking, thesis package, and five-field strategy files under ignored `data/private/`;
5. prints one existing `linkedin-os draft` command per thesis.

No weak thesis is silently promoted. Exhaustion returns no thesis set, while the already-persisted momentum package remains available for inspection.

Unavailable surface lanes receive one bounded retry. When no topic clears the
conversation-momentum floor, discovery may continue through a clearly labelled
authority-fit fallback only when the topic still has at least four observed
momentum axes and scores at least 20/25 on authority fit. This does not change
the 14/25 momentum score or represent the fallback topic as trending.

Every topic scoring at least 40/50 across observed momentum plus authority fit
is retained in a rolling seven-day private candidate inventory. Selecting the
highest candidate does not discard the other qualified topics.

## Human decision

Choose the thesis whose judgment you genuinely endorse. Run only its printed draft command.

To explicitly select the highest-scoring qualifying thesis and continue into
the post workflow in the same invocation:

```bash
./bin/linkedin-os discover \
  --profile data/private/authority-profile.json \
  --days 7 \
  --allow-web-research \
  --allow-model-egress \
  --generate-post
```

This is an opt-in convenience for a review-ready outcome. It does not publish.
The command reports that voice guidance was loaded before it starts drafting.
It also prints and stores an eval dashboard. Contracts from stages that were
not reached are shown as `NOT_EVALUATED` instead of disappearing.

The command prints one `Run ID` before discovery begins. That identity is
inherited by the draft subprocess and written on every V1 decision, so Topic
Value, Critic, reproducibility, and Resonance observations can be reconstructed
as one end-to-end dashboard case without mixing decisions from adjacent runs.

`export-monitoring` emits that run as one redacted `linkedin-run` case with all
seven checks. Missing downstream checks remain explicit `NOT_EVALUATED` rows;
they are never silently omitted. The export requires the printed run ID in the
approved private monitoring context and refuses legacy decision rows that have
no run identity.

Every run also stores `run-dashboard.json`, which names the first failed stage
and leaves downstream stages explicitly `NOT_EVALUATED`. Thesis search stores
`thesis-evaluations.json` with every candidate from every cycle, its axis scores,
threshold misses, and the best candidate observed across the complete search.

Topic Value selection uses a bounded 300-second attempt and one 420-second
timeout-only retry. Other selector failures remain fail-closed and are not retried.

The existing draft workflow then owns:

- three post candidates;
- the shared 18/25 post floor, hook and voice floors of 4, and the other axis floors of 3;
- deterministic authority, honesty, citation, relevance, and proof gates;
- bounded regeneration;
- optional private human-review package.

A passing machine score remains review eligibility, not approval or an engagement prediction.

## Measurement boundary

Keep organic and paid observations separate. Do not boost a post during its initial 72-hour organic measurement window. Use qualified inbound, target-audience profile activity, saves, sends, and substantive comments as the authority indicators; reactions alone are insufficient.
