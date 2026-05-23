# Realtime Scheduling Agent

An AI agent that makes phone calls on your behalf — booking appointments, making reservations, or any other phone-based task. Connect it to Claude (or any MCP client) and ask it to "schedule a doctor's appointment for next Tuesday."

**How it works:** Claude calls `prepare_call` → gathers any missing info → calls `place_call` → the agent dials out and conducts the conversation in real time → a post-call agent summarizes the outcome, creates a Google Calendar event, and returns the result.

## Quick Start

Pick a deployment method:

- **[Bare metal](#bare-metal)** — best for development
- **[Docker](#docker)** — best for self-hosting
- **[Railway](#railway)** — one-click cloud deployment

Then **[connect your MCP client](#connect-your-mcp-client)**.

---

## Prerequisites

All deployment methods require:

- OpenAI API key with [Realtime API](https://platform.openai.com/docs/guides/realtime) access
- [Twilio](https://www.twilio.com/docs/voice) account with a phone number
- A public HTTPS URL pointing to this server (ngrok for local dev, or a cloud deployment)

Google Calendar integration is optional — skip those env vars if you don't need it.

---

## Bare Metal

```bash
# 1. Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install dependencies
uv sync

# 3. Configure secrets
cp .env.example secrets.env   # then fill in your values

# 4. Set up user info
#    Edit user_info.yaml with your name, DOB, etc., then encrypt it:
uv run python main.py encrypt

# 5. Start the server
uv run python main.py serve

# 6. In another terminal, expose it publicly (local dev only)
ngrok http 2255
```

Set `DOMAIN` in `secrets.env` to your ngrok hostname (no `https://` prefix), then [configure Twilio](#twilio-setup) and [connect your MCP client](#connect-your-mcp-client).

---

## Docker

```bash
# 1. Configure secrets
cp .env.example secrets.env   # fill in your values

# 2. Set up user info (requires uv, or run inside the container)
uv run python main.py encrypt

# 3. Build and run
docker compose up --build
```

Secrets are never baked into the image — `secrets.env`, `user_info.yaml.enc`, and `credentials.json` are mounted at runtime.

---

## Railway

Railway handles hosting, TLS, and a public domain automatically.

1. Fork or push this repo to GitHub.
2. Create a new Railway project and connect your GitHub repo.
3. Set the following environment variables in Railway's dashboard (see [Environment Variables](#environment-variables) for the full list):
   - `OPENAI_API_KEY`
   - `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `PHONE_NUMBER_FROM`
   - `API_BEARER_TOKEN`
   - `USER_INFO_SECRET`
   - `DOMAIN` — set this to your Railway-generated domain after first deploy
4. Mount `user_info.yaml.enc` as a file (Railway **Volumes** or paste contents into a variable and decrypt at runtime).
5. Railway auto-detects the `Dockerfile` and deploys. Port 2255 is exposed automatically.

Then [configure Twilio](#twilio-setup) and [connect your MCP client](#connect-your-mcp-client).

---

## Twilio Setup

Point your Twilio phone number's **Voice** webhook at:

```
https://<your-domain>/incoming-call   (HTTP POST)
```

---

## Connect Your MCP Client

Add the MCP server to Claude Code:

```bash
claude mcp add --transport http scheduling-agent https://<your-domain>/mcp/ \
  --header "Authorization: Bearer <your-api-bearer-token>"
```

Or add it manually to your MCP config:

```json
{
  "mcpServers": {
    "scheduling-agent": {
      "type": "http",
      "url": "https://<your-domain>/mcp/",
      "headers": { "Authorization": "Bearer <your-api-bearer-token>" }
    }
  }
}
```

> The `/mcp/` trailing slash is required — `/mcp` returns a 307 redirect.

Once connected, just ask Claude: *"Schedule a haircut at 3pm tomorrow."*

---

## Secrets Reference

Copy `.env.example` to `secrets.env` and fill in:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI key with Realtime API access |
| `TWILIO_ACCOUNT_SID` | Yes | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Yes | Twilio auth token |
| `PHONE_NUMBER_FROM` | Yes | Your Twilio phone number (E.164) |
| `DOMAIN` | Yes | Public hostname, no `https://` prefix |
| `USER_INFO_SECRET` | Yes | Password for `user_info.yaml.enc` |
| `API_BEARER_TOKEN` | Yes | Token for MCP and API access (random generated if unset) |
| `GOOGLE_CALENDAR_CREDENTIALS` | No | Path to service account JSON |
| `GOOGLE_CALENDAR_ID` | No | Calendar ID (your email address) |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `2255` | HTTP server port |
| `DATA_DIR` | `./data` | Directory for SQLite database |
| `RATE_LIMIT_CALLS_PER_HOUR` | `30` | Max outgoing calls per hour per token |
| `TWILIO_SIGNATURE_VALIDATION` | `true` | Set to `false` for local dev only |

---

## Features

**MCP Tools** (used by Claude or any MCP client):
- `prepare_call` — identifies the scenario and returns questions to ask the user
- `place_call` — dials out immediately with gathered context
- `get_call_outcome` — blocks until the call finishes and returns the summary

**Post-Call Processing:** After every call, a non-realtime agent summarizes the transcript, creates a Google Calendar event (if an appointment was made), and appends a memory entry so future calls have context.

**Persistent Memory:** Call outcomes are stored in SQLite and injected into the realtime agent on each new call — so if a business calls back, the agent knows why.

**Incoming Calls:** Call the Twilio number directly to talk to the agent in real time.

**Extensible Scenarios:** Add new outgoing call scenarios by dropping a YAML file in `src/agent_factory/realtime/prompts/outgoing/`. See [Adding a Scenario](#adding-a-scenario).

---

## Google Calendar Setup

The agent uses a service account (not OAuth) so it works headless in any environment.

1. **Create a Google Cloud project** and enable the **Google Calendar API**.
2. **Create a service account** under **APIs & Services > Credentials**. Copy its email address.
3. **Download the JSON key** and save it as `credentials.json` in the project root.
4. **Share your calendar** with the service account email, granting **Make changes to events**.
5. **Set env vars:**
   ```
   GOOGLE_CALENDAR_CREDENTIALS=credentials.json
   GOOGLE_CALENDAR_ID=you@gmail.com
   ```

> `credentials.json` is gitignored and dockerignored — it's never committed or baked into images.

### Troubleshooting

| Problem | Fix |
|---------|-----|
| `RuntimeError: GOOGLE_CALENDAR_CREDENTIALS env var not set` | Add the var to `secrets.env` |
| `RuntimeError: Credentials file not found` | Check the path — use an absolute path in Docker/Railway |
| `403 Forbidden` / insufficient permissions | Re-share the calendar with the service account email |
| `403 Calendar API has not been used in project` | Enable the Calendar API in Cloud Console |
| Events not appearing | Verify `GOOGLE_CALENDAR_ID` is your email, not `primary` |

---

## Adding a Scenario

Create `src/agent_factory/realtime/prompts/outgoing/<scenario_key>.yaml`:

```yaml
name: "Human-Readable Name"
description: "One-line description for scenario selection"
required_context:
  - "What info the agent needs before calling"
voice: cedar  # optional
instructions: |
  You are {name}, calling to ...

  {additional_context}

  Once confirmed and goodbyes exchanged, call end_call.
```

The file stem becomes the scenario key. Template variables `{name}`, `{age}`, `{date_of_birth}`, `{ssn_last_four}`, and `{additional_context}` are always available.

---

## API Endpoints

All endpoints except `/health` require `Authorization: Bearer <token>`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (unauthenticated) |
| GET | `/prompts` | List available outgoing-call scenarios |
| POST | `/incoming-call` | Twilio voice webhook |
| POST | `/outgoing-call` | Initiate an outgoing call directly |
| WS | `/media-stream` | WebSocket for incoming calls |
| WS | `/media-stream/{call_id}` | WebSocket for outgoing calls |
| POST | `/mcp/` | MCP server endpoint (StreamableHTTP) |

---

## Architecture

```
  MCP Client  ──────►  ┌──────────────┐
  (e.g. Claude)        │  MCP Server  │ (/mcp/, bearer auth)
                        └──────┬───────┘
                               │ place_call / get_call_outcome
                               ▼
  Phone Call ──────►  ┌──────────────┐
                       │    Twilio    │
                       └──────┬───────┘
                              │ Media Stream WebSocket
                              ▼
                       ┌──────────────┐
                       │ TwilioHandler│ ◄──► OpenAI Realtime API
                       │ (Realtime)   │
                       └──────┬───────┘
                              │ transcript on hang-up
                              ▼
                       ┌──────────────┐
                       │  Post-Call   │
                       │  Agent       │
                       └──────┬───────┘
                              │
                    ┌─────────┼──────────┐
                    ▼         ▼          ▼
             ┌──────────┐ ┌───────┐ ┌────────┐
             │ Google   │ │Memory │ │ MCP    │
             │ Calendar │ │ (DB)  │ │ result │
             └──────────┘ └───────┘ └────────┘
```

---

## Security

- Bearer token is required for all API and MCP endpoints. If `API_BEARER_TOKEN` is unset, a random one is generated and logged on startup.
- Twilio signature validation is on by default — only disable for local dev.
- `user_info.yaml` is encrypted at rest (PBKDF2-SHA256, 600k iterations); the plaintext file is gitignored.
- Secrets are never baked into the Docker image — injected at runtime via env vars or mounted files.
