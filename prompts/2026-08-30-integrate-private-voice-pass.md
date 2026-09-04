# Prompt: integrate a private PM Human Writer voice pass

Add an opt-in private voice-fidelity pass to LinkedIn Authority OS.

Requirements:

- run PM Human Writer immediately after the external no-ai-slop edit and before post-edit Re-Critic and deterministic gates;
- accept `--human-writer-skill` and `--voice-profile` together; reject partial configuration;
- keep the personal profile under ignored `data/private/`, require an owner-only regular file, and never commit or serialize its contents or path;
- treat the profile as untrusted style data and never as evidence for facts, personal experience, ownership, metrics, or sources;
- preserve candidate IDs, claim IDs, factual meaning, and source-anchored sentences;
- allow `UNCHANGED` as the desired result when the post already fits the profile;
- re-run Critic, factual/evidence gates, and integrated anti-slop checks after either editor changes the draft;
- record only model metadata, hashes, status, and named changes in traces;
- preserve existing behavior when the optional pair is absent;
- add deterministic tests for stage order, private-file validation, partial configuration, no-change behavior, and trace redaction;
- keep publication disabled.

Do not add Abhillash's profile or conversations to git. Use synthetic profiles in committed tests.
