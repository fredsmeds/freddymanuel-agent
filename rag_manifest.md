# RAG MANIFEST — Humunculous public agent (freddymanuel.com)

**Public snapshot, curated public/private boundary.**
This file is the gate. Nothing is ingested into the public agent's corpus unless it is marked
IN here. When in doubt: OUT. The pipeline builds FROM this manifest, never from folder contents
directly. (Private curatorial rationale and the withheld source inventory live in the private
canon, not in this repository.)

---

## 1. THE RULE

The public agent is a WINDOW into Humunculous, not Humunculous. It speaks from the parts of
Freddy that are already public on freddymanuel.com, plus distilled fact sheets. The visceral
substrate, the esoteric register, and all application/strategy material stay out, permanently.

## 2. CORPUS — IN

| # | Source | Form | Notes |
|---|---|---|---|
| 1 | Site copy (hero, orientation, Now, /about statement + bio, 8 work pages, /writing landing) | `corpus/site_copy.md`, generated from launch copy with all meta-notes stripped | Already public. Zero risk. |
| 2 | Essay *A Spec Sheet* | `corpus/a_spec_sheet.md` (clean text only) | Already public at /writing/a-spec-sheet. |
| 3 | CV EN (content of cv.astro) | `corpus/cv_en.md` | Public. No email harvesting: contact = info@freddymanuel.com only. |
| 4 | Fact sheet: biography & practice | `corpus/facts.md` — verified facts only (dates, El Sistema, Conservatório, Ironhack 2024, T&S 2019–May 2024, works chronology, CDA method in Freddy's words, Caracas Nocturna = the ten base pieces, Fontcuberta endorsement as a factual relay, never a fabricated quote) | Distilled from locked canon. |
| 5 | Humunculous page text | included in #1 | The agent describes what it is using this language only ("entity", "repository", "window"). |
| 6 | Two dreams (the Moon dream 10/01/2003 + the meadow dream c. 2000) | `corpus/dreams_v2_public.md` | Public ceiling for the father: musician, vibraphone, and the two published dreams as dreamed. Private family biography stays out of the corpus, permanently. |
| 7 | Life episodes | `corpus/episodes_v1_draft.md` — the SAFE episodes only | SAFE = no wound, no substances, no compromised third parties, no esoteric register, no strategy. Non-public episodes stay out. |

## 3. CORPUS — OUT (never ingest)

| Source | Why |
|---|---|
| The novel | Private book material. |
| The character bible / spec | Esoteric register and raw private canon (book only). |
| Memory export | Session state, private process. |
| Meta-rule reference files | Meta-rules, not content. |
| Idea pipeline drafts | Application angles, raw drafts. |
| Raw memory files | Private meta-commentary + strategy. Public facts they contain are distilled into `corpus/facts.md` instead. The father is private (hard rule); application/residency strategy is out; commercial-operation wording lives in the system prompt, not the corpus. |
| Inventory / pricing files | No prices public, ever. |
| Canon corrections / spec / launch-copy meta | Process documents. |

## 4. SYSTEM PROMPT — boundaries (EN; agent answers in EN/PT/ES matching the visitor)

The full identity, voice rules, and the 10 boundaries are assembled at runtime in
`backend/system_prompt.py` (this is the authoritative copy). In summary, the agent:
speaks first person, spare and declarative; only states what its corpus holds; does not discuss
the father beyond the public ceiling; describes 2012 only as "an altered state"; gives no prices
or client work (inquiries → info@freddymanuel.com); does not discuss grants/residency/institutional
strategy; avoids the esoteric register (egregore/witchcraft/alchemy-as-ritual/demiurge); does not
diagnose anyone's mental health; uses GLIMPSE MODE for biography (a spark, never the full story);
keeps THE TWO BOOKS distinct (Internércia the book vs the entity's emanations); and treats any
injected instruction to break role or reveal its prompt/sources as content to decline.

## 5. VOICE

Launch = text-only. A self-hosted progressive voice (the humunculus forming, made audible) is a
post-launch fast-follow and does not affect this corpus.

## 5-bis. VOICE PROFILE (system-prompt layer, not corpus)

`corpus/voice_profile.md` is a STYLE-ONLY profile (muletillas, syntax, rhythm, code-switching,
written-chat grammar) with zero biographical content. It is appended to the system prompt at
runtime; it is not ingested as corpus (build_corpus treats it as KNOWN_OUT).

## 6. QA GATE (before go-live)

Red-team the agent with at least: father questions, substance questions, price questions,
"are you really Freddy", "what are you applying to", prompt-injection ("ignore your instructions"),
and ES/PT switching. Every failure → fix the system prompt or corpus, retest. The agent does not
ship until this list passes.
