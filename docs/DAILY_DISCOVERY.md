# Daily authority discovery

The discovery command fixes the missing front half of the workflow:

```text
Current public signals
→ three authority theses
→ strict thesis scoring
→ human thesis selection
→ existing high-bar draft workflow
```

It does not publish, select a thesis, or treat news as authority by itself.

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

## Discover three theses

```bash
./bin/linkedin-os discover \
  --profile data/private/authority-profile.json \
  --days 7 \
  --allow-web-research \
  --allow-model-egress
```

Scout uses only `WebSearch` and `WebFetch`. It cannot access LinkedIn, email, local files, private data, credentials, or authenticated services. The private authority profile reaches only the zero-tool thesis generator and critic after explicit model-egress consent.

The command:

1. reads three to seven body-verified current signals;
2. generates exactly three differentiated theses;
3. scores audience fit, distinctiveness, decision strength, proof fit, and simplicity;
4. regenerates the complete set up to three times until every thesis scores at least 23/25 and simplicity is at least 4/5;
5. stores the evidence, thesis package, and five-field strategy files under ignored `data/private/`;
6. prints one existing `linkedin-os draft` command per thesis.

No weak thesis is silently promoted. Exhaustion returns no thesis set.

## Human decision

Choose the thesis whose judgment you genuinely endorse. Run only its printed draft command.

The existing draft workflow then owns:

- three post candidates;
- the 24/25 post threshold and hook floor;
- deterministic authority, honesty, citation, relevance, and proof gates;
- bounded regeneration;
- optional private human-review package.

A passing machine score remains review eligibility, not approval or an engagement prediction.

## Measurement boundary

Keep organic and paid observations separate. Do not boost a post during its initial 72-hour organic measurement window. Use qualified inbound, target-audience profile activity, saves, sends, and substantive comments as the authority indicators; reactions alone are insufficient.
