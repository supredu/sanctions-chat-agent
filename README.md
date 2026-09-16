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
# Optional, used for outbound one-hop counterparty checks.
BITRACE_MCP_URL=https://...
BITRACE_API_TOKEN=your_bitrace_token
BITRACE_MCP_SESSION_ID=optional_session_id
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

Run local routing with outbound one-hop counterparty checks when Bitrace MCP is configured:

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
- Parses local UK Sanctions List XML exports.
- Checks outbound one-hop counterparties through Bitrace MCP when configured, then
  matches counterparties against the local sanctions index before involving the LLM.
- Serves a simple chat-style MVP UI from `web_app.py`.
- Performs public web enrichment with official OFAC seed URLs, optional Brave
  Search / SerpAPI support, and a no-key DuckDuckGo HTML fallback.
- Uses DeepSeek in the chat MVP to synthesize local sanctions hits, web evidence,
  explorer context, and follow-up questions into a final Chinese analyst-style answer.

## Documentation

- [Agent design](docs/agent_design.md)
- [Agent design, Chinese](docs/agent_design_zh.md)
- [API documentation](docs/api.md)
- [Data partner API requirements, Chinese](docs/data_partner_api_requirements_zh.md)

## Local Source Files

Place local sanctions source files in `source_files/`:

```text
source_files/sdn_advanced.xml
source_files/entities.ftm.OFAC.json
source_files/entities.ftm.ISRAEL.json
source_files/entities.ftm.JAPAN.json
source_files/entities.ftm.FRENCH.json
source_files/UK-Sanctions-List.xml
```

The local parser builds a normalized blockchain-address index from:

- OFAC Advanced XML `Digital Currency Address - ...` features.
- UK Sanctions List XML designations and crypto addresses embedded in `OtherInformation`.
- FollowTheMoney JSONL `CryptoWallet` entities.
- Linked `Sanction` and holder entities where available.

Date handling:

- OFAC Advanced XML `EntryEvent/Date` is treated as an official sanction date.
- OFAC Advanced XML `DateOfIssue` is treated as the local source-file publication date.
- UK Sanctions List XML `DateDesignated` is treated as an official sanction date.
- UK Sanctions List XML `DateGenerated` is treated as the local source-file publication date.
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

## Update Official XML Sources

Refresh the official OFAC and UK XML files, validate that both downloads are
parseable XML, and rebuild the SQLite index:

```bash
.venv/bin/python scripts/update_source_files.py
```

Update only one source:

```bash
.venv/bin/python scripts/update_source_files.py --source ofac
.venv/bin/python scripts/update_source_files.py --source uk
```

Download XML files without rebuilding the index:

```bash
.venv/bin/python scripts/update_source_files.py --skip-build
```

The updater uses these official XML endpoints:

- OFAC SDN Advanced XML: `https://sanctionslistservice.ofac.treas.gov/api/download/sdn_advanced.xml`
- UK Sanctions List XML: `https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml`

The repository includes a GitHub Actions workflow at
`.github/workflows/update_sanctions_data.yml`. It runs daily and can also be
triggered manually from GitHub Actions. It downloads the ignored raw XML files,
rebuilds `data/sanctions_index.sqlite`, writes `data/source_manifest.json`, and
commits those runtime artifacts back to the repository when they change.

## Deploy on Render Free

This repository includes `render.yaml`. Push the project to GitHub, create a new
Render Blueprint from the repo, and set `DEEPSEEK_API_KEY` in Render environment
variables. Optional production search providers can be configured with
`BRAVE_SEARCH_API_KEY` or `SERPAPI_API_KEY`. To enable one-hop checks in the
deployed chat UI, also set `BITRACE_MCP_URL` and `BITRACE_API_TOKEN`; set
`BITRACE_MCP_SESSION_ID` only if the provider requires a stable session id.
