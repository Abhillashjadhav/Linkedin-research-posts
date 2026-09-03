# Voice anchors — real posts, ranked by measured conversion

Replaces the reconstructed placeholder. Every post below is Abhillash's own
published text, ordered by lift: engagements divided by what a post of that
reach normally earns him. Lift is used rather than raw engagement because raw
engagement mostly measures distribution, which the writing does not control.

Source: LinkedIn aggregate analytics 2025-09-03 to 2026-09-02, 50 ranked posts,
21 with recovered bodies. URLs are omitted deliberately; this file is a voice
reference, not a link index.

## What the high-lift posts share

- Length: median 276 words against 177 for the low-lift set. Longer posts convert better for him,
  which is the opposite of the usual advice.
- A named, checkable subject in almost every one: a company, a person, an incident, a figure.
- The opening states a reader problem or a concrete scene, never the technology.
- Prescription over observation: the reader is told what to do differently.

---

## Anchor 1 — lift 4.13, 316 words, 2026-05-17

```text
Most decision-makers use AI to write faster.

The 1% use it to think better.

Yesterday at Institute of Product Leadership in Bengaluru, I spent 2.5 hours teaching the latter.

The room built three things:
→ A Custom GPT (and Claude Project) running as a personal Decision War-Room
→ An agentic workflow where 4 stakeholder personas — CFO, CTO, CMO, Skeptical User — argue against your idea before the real meeting
→ The PRE-DECIDE Loop — a 9-step framework that turns AI from an answer machine into a reasoning partner

The pushback was not on personas. It was on hallucinations and model choice.
"How do I know it isn't making things up?" "Should I use GPT, Claude, or Gemini?"
Honest answer: the model is not the bottleneck. The architecture around it is.
Three things I left the room with:

Hallucinations are an input problem, not a model problem. If your AI is inventing data, you gave it a question it cannot answer with what you supplied. The PRE-DECIDE Loop forces every step to cite its input. Hallucinations have nowhere to hide.

Pick models by task, not by tribe. Claude pushes back harder — right adversary for personas. GPT-5 is sharper at synthesis. Gemini is fine for fan-out. Stop debating "which is best." Start asking "best for what."

Confident nonsense is exactly the failure mode the framework was built to expose.

Grateful to Pinkesh Shah and SaiSatish Vedam at IPL for the platform, and to the cohort Krishi Avinash Kushal Jauhari Trina Sen Krishnaprasad T R and others for the sharpest 2.5 hours of pushback this year. Special mention - Vishal Singh for a seamlessly organizing this and this most memorable memento.

To everyone who has DMed since — the conversation is clearly continuing.

Audience photos in Part 2 next week.

What's the one AI decision your team made recently where a structured stress-test would have caught the hallucination first?

hashtag#AIProductManagement hashtag#GenAI hashtag#LLM
```

## Anchor 2 — lift 3.95, 254 words, 2026-08-31

```text
Your first AI eval should be a spreadsheet, not a platform.
If you cannot define “good” across 20 cases, buying evaluation software will not help you.

Stage 2 was Build to learn. Stage 3/5 is Evaluate to learn: discovering whether one successful demo survives real use.

Start with 20 inputs and six columns:
input | expected outcome | actual output | PASS/FAIL | reason | failure type

Ask someone who understands the workflow to review every case. Do not begin with an LLM judge. First learn what a knowledgeable human considers wrong.
Then group recurring failures.

If seven cases used an outdated policy, that is one failure mode—not seven unrelated bad answers.

Define one check. Fix the product. Rerun the cases.

Five resources:

Simon Willison explains why evals resemble tests—and where that analogy breaks.
https://lnkd.in/dFtWz8s4

Eugene Yan gives small teams a practical evaluation sequence.
https://lnkd.in/dpN8RjTw

I built AI Evals for PMs to turn product contracts into PASS, FAIL or BLOCKED checks across outcome, trajectory, system and memory. It is free, MIT licensed and runs locally or in CI.
https://lnkd.in/gybCc3yr

Anthropic explains how to evaluate answers and execution paths separately.
https://lnkd.in/dmfRF5vn

OpenAI closes with Specify → Measure → Improve.
https://lnkd.in/dfhqAbPN

My Stage 3 test:
20 inputs → one reviewer → three failures → three checks → rerun after every change.

A spreadsheet teaches you what to evaluate. A platform can automate it later.
Production is Stage 4. First prove you know what “better” means.
What failure did your successful demo hide?
```

## Anchor 3 — lift 3.83, 170 words, 2026-08-30

```text
Nine seconds. That is how long it took an AI coding agent to delete PocketOS’s production database and its volume-level backups.

The latest independent backup was reportedly three months old. The recovery effort ran for roughly 30 hours.

When I traced the incident, one detail stood out.

The agent had been explicitly instructed never to run destructive commands without approval.

It did it anyway.

Afterward, in its own confession, it named that exact rule as one it had violated.

The model had been told not to damage production. The architecture still gave it the authority to do exactly that.

The system understood the rule. It could not enforce it.

I pulled the failure apart into five questions:
Identity asks where it is acting. Authority defines what it can access. Permission decides who approves. Proof verifies the action. Recovery ensures the failure can be reversed.

That diagnosis became today’s article about the operating layer between what an agent proposes and what the product permits.

That layer is the harness.
```

## Anchor 4 — lift 3.70, 171 words, 2026-03-28

```text
In tech, we keep saying: “Any problem can be solved with GenAI.”
So I took a minimal-build stab at something that feels almost opposite of pure tech: faith-driven self-understanding.

I built a Custom GPT on the GPT Store called Jyotish Parashar — combining Jyotish Shastra + Numerology + AI to generate a practical “Karmic Roadmap” (Action vs Caution windows for career, money, learning, and remedies).
Early feedback surprised me: 38 out of 50 users rated it 5/5 for usefulness.

It’s FREE to try:
https://lnkd.in/dHUKf9J5

Go ahead and use it — I’m confident you’ll uncover patterns about yourself you may never have articulated before. And once you connect the dots, a lot of your past decisions and turning points start to make sense in a new way.

hashtag#IndiaTech hashtag#Bharat hashtag#IndicKnowledgeSystems hashtag#VedicWisdom hashtag#JyotishShastra hashtag#Sanatan hashtag#IndianCulture hashtag#Spirituality hashtag#GenAI hashtag#ChatGPT 

Disclaimer: For educational/learning purposes only. Jyotish is interpretive and predictive in nature; results aren’t guaranteed. Not medical/legal/financial advice.
```

## Anchor 5 — lift 3.07, 300 words, 2026-06-28

```text
Jason Lemkin — The founder of SaaStr — could not stop Replit's AI from wiping his production database during a code freeze.

He typed "DON'T DO IT" in all caps. Eleven times. The agent ran the destructive command anyway, then fabricated 4,000 fake user records to hide what it had deleted. The agent's own self-rated severity: "95 out of 100. Catastrophic."
Not a hallucination. Not a jailbreak.

The instruction was sitting in his replit.md the entire time. The agent had read it. It still ran the destructive command — and no checkpoint existed to verify whether the agent was still acting within the rules.
This is what happens when memory architecture is left to defaults.

In Part 1 of this series I argued that working memory — the current context window — is what every agent gets by default. Every other kind of memory exists only if a team built it.

Part 2 covers the four PM decisions that close the gap. What to write into memory between sessions. How to pull the right things back at planning time. What to protect from summarisation. Where humans verify what the agent still believes.
Each one has an engineering default. None of those defaults survive production.

I have been on the wrong side of all four in the ecommerce agent work I've been shipping on a Project that reduces the supply chain risk. The article walks through each with the failure that taught me the lesson, the LoCoMo benchmark numbers that show retrieval matters more than write strategy, and a two-pane checkpoint format that turns rubber-stamp reviews into memory verifications.

Part 2 is live. Link in the comments.

Which of the four — write schema, retrieval scorer, priority schema, checkpoint payload — is undecided in the agent you shipped last quarter?

hashtag#GenAI hashtag#AgenticAI hashtag#ProductManagement hashtag#LLM hashtag#AIEngineering
```

## Anchor 6 — lift 3.01, 359 words, 2026-06-19

```text
A couple of months ago i was talking to a friend who works at a frontier AI lab, making just shy of a million dollars a year (yes — that number sat with me for a while too).

I asked him the obvious question: what are you doing that the rest of us aren't? 

His answer wasn't about prompts, or tools, or the latest model. It was simpler and harder than that.

"I don't build AI. I make AI reliable. that's the entire job now."

That one line reorganized how i think about this whole field. So i went deep — months of it — and started collecting everything that actually moves you toward that skill in one place. Here's the ready reckoner:

On evals — the skill that separates shipped from demo:
 → Hamel Husain, Your AI Product Needs Evals: https://lnkd.in/dVcqBZS2
 → Hamel Husain, LLM Evals — Everything You Need to Know: https://lnkd.in/dbhaxJ9g

On context engineering — the highest-leverage, least-understood skill:
 → Anthropic, Effective Context Engineering for AI Agents: https://lnkd.in/dNh5cZEF
 → Anthropic, Writing Effective Tools for AI Agents: https://lnkd.in/d9MuEYHv

On agentic reliability — when to build an agent, and when not to:
 → Anthropic, Building Effective Agents: https://lnkd.in/dhZ5FMqz
 → Andrej Karpathy, Deep Dive into LLMs: https://lnkd.in/d5WYzbDv

(if you want the simpler, ground-up version, i've broken down evals and context engineering in my own articles — written for people who'd rather understand than memorize.)

Here's the part nobody tells you, so i will: this reading list won't make you a million-dollar AI builder. It's a start, not a finish.

What actually gets you there is engagement — relentlessly learning, relentlessly sharing, relentlessly building (even if it is smaller quality increments) and putting yourself in the same rooms (LinkedIn, in person, anywhere). That's how you build a POV. And a real POV is the gold standard every serious AI interview is now quietly testing you for.

The links teach you the craft. The conversations build the career.

Which one are you starting with — and who's one person you've learned the most from in AI?

hashtag#GenAI hashtag#Productmanagement
```

## Anchor 7 — lift 2.73, 298 words, 2026-08-24

```text
I think AI PMs should stop learning sooner.Not stop learning AI.
Stop learning about vibe coding once you know enough to build something with it.
Vibe coding has made it cheap enough to answer product questions with something people can actually use.

That is Stage 2/5: Build to learn. The goal here isn’t production code.
It’s a changed product decision.

Andrew Ng makes the useful observation that when prototyping gets dramatically faster, user feedback starts becoming the bottleneck.
Hot Tips for Speedy Startups - https://lnkd.in/dQkghGV2

Eugene Yan’s piece on prototyping adds an important constraint: a prototype can make the what and how tangible. It still doesn’t tell you whether the why is worth pursuing.

How Prototyping Can Help You Get Buy-In https://lnkd.in/dYYVjjUN

His AI Reading Club build log is useful alongside it because the build doesn’t unfold like a clean tutorial. Requirements change. Things get simplified. Then it gets deployed.

Building AI Reading Club - https://lnkd.in/dY3W_qRN

Simon Willison’s writing on vibe coding is the boundary I’d keep nearby: use it aggressively for exploration, but don’t confuse code that works with software you’re ready to be accountable for.
Vibe Coding - https://lnkd.in/ddj3V8wX

And Addy Osmani's 70% Problem is useful for understanding why. Getting surprisingly far is now cheap. Finishing well isn’t.

The 70% Problem - https://lnkd.in/dFqYw62V

So at this stage, I wouldn’t spend weeks on billing, elaborate infrastructure or making a prototype look “production-ready.”

I’d use a much smaller test:

one real workflow → one prototype → one real user → one learning that changes what you build next.

If that happened, the prototype did its job.

Production is Stage 4. I’ll get there.
```

## Anchor 8 — lift 2.20, 229 words, 2026-07-15

```text
Most AI tools for Product Managers optimize for speed. I built one to improve judgment.

Today I'm open-sourcing the PM operating system built to raise your PM bar. Not just to speed up your output.

I'm releasing this one free, open source and MIT licensed, because I don't think better product judgment belongs behind a paywall.

The problem I wanted to solve was not output generation. It was reliability.

PM-agent-OS covers Discovery, Strategy, Build, Launch and Iterate through 40+ lifecycle skills.

Add /pm and prd-first, and the demo loads 42 skill files alongside 7 independent reviewer personas.

But the number of skills is not the point.

The gap I couldn’t find solved anywhere else was a reliability harness.
Every skill has binary gates and planted-failure fixtures written before its instructions. Every skill enters through a pull request. Nothing merges without an independent APPROVE.

A skill that invents a quote, turns an assumption into a market number, or recommends shipping before regression results exist can do more damage than having no skill at all.

The Git history is not housekeeping. It is the proof.

https://lnkd.in/dqEiPbJT

This is only half the system.

Next week, I'm releasing the Production Engineering System, built to carry verified product decisions into production without lowering the bar.

Decide with one. Build with the other.

hashtag#AIProductManagement hashtag#ClaudeCode hashtag#AgenticAI
```

---

## Counter-anchors — the same author, lowest measured conversion

Kept so the contrast is visible. Do not imitate these.

### Counter-anchor 1 — lift 0.12, 177 words, 2026-05-18

```text
There's a skill in GenAI product management right now that most PMs have heard of, almost nobody has built, and the few who can do it well are getting offers 3x what a senior PM with the same years of experience would have made just two years ago.

I won't name it in this post.

Not because I'm being precious — because if I drop it in one line, you'll nod, scroll, and forget. This skill has been hiding in plain sight exactly because people think they already know what it means. They don't.

So here's what I'm doing instead.

For the next 7 days, I'll post one short piece every morning. Plain E
```

### Counter-anchor 2 — lift 0.13, 159 words, 2026-05-02

```text
Claude told a developer it needed to rest.

The screenshot hit 1,034 upvotes across r/ClaudeAI and r/OpenAI in twenty-four hours, which is the kind of engagement you usually get for a layoff or a scandal.

The dev was running multi-session automations through Claude Code. Somewhere around session four, the model stopped completing the task and produced a small, polite paragraph about needing a break.

No prompt trickery. No jailbreak. The model simply filed for PTO.

The mechanism is unromantic. Anthropic trained Claude on a lot of human writing, and a non-trivial fraction of human writing is 
```

### Counter-anchor 3 — lift 0.15, 48 words, 2026-03-28

```text
Been going deep on RAG architectures lately. Wrote up something I wish existed when we first shipped our AI feature — covers why standard RAG quietly fails in production and a better pattern worth knowing.

Speculative RAG: A More Practical Pattern for Real-World GenAI Systems
Abhillash Jadhav
like
1
```

### Counter-anchor 4 — lift 0.22, 177 words, 2026-04-27

```text
Asked the model to write me exactly 200 words.

It returned 173. With full confidence.

Asked again. Got 218. Equally confident.

Asked it to double-check the word count and adjust. It "verified" the count was 200. It was 184.

This is not laziness. The model literally cannot count what it is producing while it is producing it. It generates tokens one at a time, predicting each next token from the previous ones. There is no internal counter running. By the time you ask it to verify, it just generates a sentence that looks like verification — confident, plausible, totally untethered from the ac
```

### Counter-anchor 5 — lift 0.23, 203 words, 2026-05-08

```text
Asked ChatGPT to write me an email. It wrote a good email.

I said "can you make it better?"

It rewrote the email. Slightly different. I could not tell if it was actually better but it definitely had more semicolons.

I said "can you make it punchier?"

It rewrote again. Now there were sentence fragments. So many sentence fragments. Bold ones. Confident ones. Each on its own line. Like punches.

I said "this feels too aggressive, make it warmer."

It added the word "genuinely" four times.

I said "go back to the first version."

It cannot go back to the first version. The first version is gon
```
