# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run server (port 2255)
uv run python main.py serve

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_endpoints.py

# Type check
uv run mypy src/

# Encrypt user_info.yaml → user_info.yaml.enc
uv run python main.py encrypt

# Docker
docker compose up --build
```

## Configuration

Copy `.env.example` to `secrets.env`. Required variables:
- `OPENAI_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `PHONE_NUMBER_FROM`
- `DOMAIN` — public hostname without `https://` (use ngrok for local dev)
- `USER_INFO_SECRET` — password for user_info.yaml.enc decryption
- `TWILIO_SIGNATURE_VALIDATION=false` — disable for local dev/testing

Google Calendar requires a service account JSON at `GOOGLE_CALENDAR_CREDENTIALS` and the calendar shared with the service account email.

## Architecture

This is a voice-call scheduling agent. An MCP client (e.g., Claude) uses the MCP server to orchestrate calls that book appointments, make reservations, etc.

**Call flow:**
1. MCP client calls `prepare_call` → LLM analyzes the scenario, identifies missing info, generates questions
2. MCP client calls `place_call` with answers → Twilio initiates outbound call, request stored in SQLite as `in_progress`
3. Twilio connects the call to a WebSocket → `TwilioHandler` bridges Twilio audio (PCMU 8kHz) to OpenAI Realtime API
4. After call ends, `post_call` agent runs (non-realtime): summarizes transcript, creates Google Calendar event, appends to memory log, marks request `completed`
5. MCP client polls `get_call_outcome` until status is `completed`

**Key constraint:** Only the post-call agent may write to persistent state (calendar, memory). The realtime agent is ephemeral — it reads memory/calendar on startup but must not write, since the call can end abruptly before a tool call completes.

**ASGI composition** (`src/app.py`): The FastAPI server (`src/server.py`) and FastMCP server (`src/mcp_server.py`) are mounted as a single ASGI app. Bearer auth middleware protects `/mcp/sse`.

**Agent prompts** are YAML templates under `src/agent_factory/*/prompts/`. Outgoing call prompts are keyed by scenario (e.g., `doctor_appointment`, `restaurant_reservation`). User PII from `user_info.yaml.enc` is decrypted at runtime and injected into prompts as template variables.

**Persistence** (`src/persistence.py`): SQLModel + SQLite. Single `Request` table tracks MCP call lifecycle. `src/tools/memory.py` is a separate append-only SQLite log of call outcomes, loaded into realtime agent context on each call.

**Audio bridge** (`src/twilio_handler.py`): Handles the WebSocket from Twilio, converts audio, manages playback tracking (mark → bytes), runs three concurrent asyncio tasks (realtime events, Twilio messages, end-call watcher), and captures a full transcript on hangup.

## Project Structure Hints

- `src/agent_factory/realtime/agent.py` — factory for incoming vs. outgoing realtime agents; voice selection logic
- `src/agent_factory/post_call/agent.py` — non-realtime agent; runs after call, writes all persistent state
- `src/mcp_server.py` — the three MCP tools exposed to external clients
- `src/twilio_handler.py` — core real-time orchestration; most complexity lives here
- `src/tools/user_info.py` — PII encryption (PBKDF2-SHA256, 600k iterations) and template variable substitution
