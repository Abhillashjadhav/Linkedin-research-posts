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
  --allow-web-research \
  --allow-model-egress
```

The public-web Scout runs through Codex with live native web search as its only enabled model tool. It cannot use shell, browser automation, apps, plugins, subagents, local files, repository-writing tools, private data, credentials, or authenticated services. Public search-index snippets from X/Twitter or LinkedIn may contribute momentum evidence only when visible without authentication. The private authority profile reaches only zero-web Codex scoring/thesis stages after explicit model-egress consent.

## Conversation momentum

Before source selection, the Scout returns exactly ten distinct candidate conversations. Each candidate is measured on five axes from public evidence:

1. conversation breadth;
2. engagement strength;
3. acceleration;
4. cross-platform confirmation;
5. freshness.

The Scout may use free public evidence observable through web search/fetch, including Google Trends pages, Hacker News, Reddit, YouTube, publicly indexed X/Twitter or LinkedIn results, primary-source launches/research, and reputable reporting.

A score is allowed only when the relevant signal is observable. If engagement, acceleration, or another axis cannot be verified, the axis is `UNKNOWN` with `score=null`; missing data is never converted to zero. Python computes totals and ranking locally from the returned observations.

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

1. generates exactly three differentiated theses;
2. scores audience fit, distinctiveness, decision strength, proof fit, and simplicity;
3. regenerates the complete set up to three times until every thesis scores at least 23/25 and simplicity is at least 4/5;
4. stores the evidence, momentum ranking, thesis package, and five-field strategy files under ignored `data/private/`;
5. prints one existing `linkedin-os draft` command per thesis.

No weak thesis is silently promoted. Exhaustion returns no thesis set, while the already-persisted momentum package remains available for inspection.

## Human decision

Choose the thesis whose judgment you genuinely endorse. Run only its printed draft command.

The existing draft workflow then owns:

- three post candidates;
- the 24/25 post threshold and 5/5 hook floor;
- deterministic authority, honesty, citation, relevance, and proof gates;
- bounded regeneration;
- optional private human-review package.

A passing machine score remains review eligibility, not approval or an engagement prediction.

## Measurement boundary

Keep organic and paid observations separate. Do not boost a post during its initial 72-hour organic measurement window. Use qualified inbound, target-audience profile activity, saves, sends, and substantive comments as the authority indicators; reactions alone are insufficient.
