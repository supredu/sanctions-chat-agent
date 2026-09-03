# Blockchain Sanctions Agent

MVP scaffold for a blockchain-address sanctions intelligence agent.

## Run

Create `.env`:

```bash
DEEPSEEK_API_KEY=your_deepseek_key
DEEPSEEK_MODEL=deepseek-v4-flash
# Optional, used by the chat MVP web enrichment layer.
BRAVE_SEARCH_API_KEY=your_brave_search_key
SERPAPI_API_KEY=your_serpapi_key
```

Run the hello-world smoke test:

```bash
.venv/bin/python helloworld.py
```

Run the sanctions agent:

```bash
.venv/bin/python main.py 0x0000000000000000000000000000000000000000 --json
```

Run local deterministic auto-routing without the LLM:

```bash
.venv/bin/python main.py Gaza --local --json
```

Reserve one-hop chain-neighbor checks for a future provider:

```bash
.venv/bin/python main.py 0x... --local --neighbors --json
```

Run the local chat MVP UI:

```bash
.venv/bin/python web_app.py
```

Open http://127.0.0.1:8765 and chat with the agent. Entity queries return local
candidates first; selecting a candidate triggers public web enrichment. Address
queries run precise local matching first, then public web enrichment and a basic
explorer page check.

Run a deterministic local-source lookup without the LLM:

```bash
.venv/bin/python local_lookup.py 0xE950DC316b836e4EeFb8308bf32Bf7C72a1358FF --pretty
```

Search sanctioned entities by fuzzy name:

```bash
.venv/bin/python local_lookup.py Gaza --entity --pretty
```

## Current MVP

- Uses DeepSeek through the OpenAI-compatible Chat Completions interface.
- Uses OpenAI Agents SDK for agent orchestration.
- Disables OpenAI tracing by default.
- Classifies common blockchain address formats.
- Builds targeted sanctions search queries.
- Lists priority sanctions source families.
- Returns a structured `SanctionResult`.
- Parses local OFAC Advanced XML and FollowTheMoney JSONL exports.
- Serves a simple chat-style MVP UI from `web_app.py`.
- Performs public web enrichment with official OFAC seed URLs, optional Brave
  Search / SerpAPI support, and a no-key DuckDuckGo HTML fallback.
- Uses DeepSeek in the chat MVP to synthesize local sanctions hits, web evidence,
  explorer context, and follow-up questions into a final Chinese analyst-style answer.

## Local Source Files

Place local sanctions source files in `source_files/`:

```text
source_files/sdn_advanced.xml
source_files/entities.ftm.OFAC.json
source_files/entities.ftm.ISRAEL.json
source_files/entities.ftm.JAPAN.json
source_files/entities.ftm.FRENCH.json
```

The local parser builds a normalized blockchain-address index from:

- OFAC Advanced XML `Digital Currency Address - ...` features.
- FollowTheMoney JSONL `CryptoWallet` entities.
- Linked `Sanction` and holder entities where available.

Date handling:

- OFAC Advanced XML `EntryEvent/Date` is treated as an official sanction date.
- OFAC Advanced XML `DateOfIssue` is treated as the local source-file publication date.
- FollowTheMoney JSONL dates are third-party metadata only and are not used as official sanction
  or publication dates.

Live web enrichment is implemented for the chat MVP, but production use should prefer a
stable search API key over the no-key DuckDuckGo HTML fallback.

## Build Local Index

Build the compact SQLite index before deploying:

```bash
.venv/bin/python scripts/build_local_index.py
```

The web app uses `data/sanctions_index.sqlite` automatically when it exists. Keep
the raw `source_files/` exports out of deployment; the SQLite index is the runtime
lookup artifact.

## Deploy on Render Free

This repository includes `render.yaml`. Push the project to GitHub, create a new
Render Blueprint from the repo, and set `DEEPSEEK_API_KEY` in Render environment
variables. Optional production search providers can be configured with
`BRAVE_SEARCH_API_KEY` or `SERPAPI_API_KEY`.
