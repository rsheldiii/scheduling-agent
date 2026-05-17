# Realtime Scheduling Agent

An agentic appointment-scheduling application that connects the OpenAI Realtime API to phone calls via Twilio Media Streams. The agent can make and receive calls, create Google Calendar events, and is orchestrated via an MCP server that any MCP-compatible client (such as Claude) can connect to.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- OpenAI API key with [Realtime API](https://platform.openai.com/docs/guides/realtime) access
- [Twilio](https://www.twilio.com/docs/voice) account with a phone number
- A tunneling service like [ngrok](https://ngrok.com/) to expose your local server
- (Optional) Google Cloud service account with Calendar API enabled

## Setup

1. **Install dependencies:**

    ```bash
    uv sync
    ```

2. **Configure secrets.** Copy the template and fill in your values:

    ```
    OPENAI_API_KEY=sk-...
    TWILIO_ACCOUNT_SID=AC...
    TWILIO_AUTH_TOKEN=...
    PHONE_NUMBER_FROM=+1...
    DOMAIN=your-ngrok-url.ngrok-free.dev   # hostname only — no https:// prefix
    USER_INFO_SECRET=your-encryption-password
    API_BEARER_TOKEN=your-secret-token     # required for MCP and API access
    GOOGLE_CALENDAR_CREDENTIALS=credentials.json   # optional
    GOOGLE_CALENDAR_ID=you@gmail.com                # optional
    ```

3. **Set up user info.** Edit `user_info.yaml` with your details, then encrypt:

    ```bash
    uv run python user_info.py encrypt
    ```

4. **Start the server:**

    ```bash
    uv run python main.py
    ```

5. **Expose the server publicly:**

    ```bash
    ngrok http 2255
    ```

6. **Configure your Twilio phone number:**
    - Set the **Voice** webhook to: `https://<domain>/incoming-call` (POST)

7. **Add the MCP server to your client** (e.g. Claude):

    ```bash
    claude mcp add --transport sse scheduling-agent https://<domain>/mcp/sse \
      --header "Authorization: Bearer <your-api-bearer-token>"
    ```

## Features

### Voice Calls (Incoming & Outgoing)

- **Incoming:** Call the Twilio number and talk to the AI assistant in real time.
- **Outgoing:** `POST /outgoing-call` with `{"to": "+1...", "prompt": "doctor_appointment"}` to have the agent call on your behalf.
- Prompts are YAML files in `prompts/outgoing/` — add new scenarios by dropping in a new file.

### MCP Orchestration

The primary interface for triggering outgoing calls is an MCP server. Any MCP-compatible client (e.g. Claude) can connect to it and use three tools:

- **`prepare_call`** — describes the call scenario and asks the LLM to gather any missing context (e.g. preferred appointment times, special requests).
- **`place_call`** — triggers the outgoing call with the gathered context.
- **`get_call_outcome`** — polls for the post-call summary (calls typically take 1–5 minutes).

### Post-Call Processing

When a call ends, the captured transcript is handed to a non-realtime post-call agent that:

1. Summarizes what happened on the call.
2. Creates a Google Calendar event if an appointment was confirmed.
3. Records a persistent memory entry so future calls have context (e.g. "awaiting callback from Dr. Smith's office").

### Persistent Memory

After every call the post-call agent writes a brief outcome summary to a SQLite-backed memory store. When the next call starts, that memory is injected into the realtime agent's context — so if a business calls back, the agent already knows why.

### Google Calendar Integration

The agent uses a **Google Cloud service account** to create calendar events on your behalf after phone calls where an appointment is scheduled. This avoids interactive OAuth flows and works well for server/headless deployments.

#### Step 1: Create a Google Cloud project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project dropdown at the top of the page and select **New Project**.
3. Give it a name (e.g. "Scheduling Agent") and click **Create**.
4. Make sure the new project is selected in the project dropdown.

#### Step 2: Enable the Google Calendar API

1. In the Cloud Console, navigate to **APIs & Services > Library** (or go directly to [the API Library](https://console.cloud.google.com/apis/library)).
2. Search for **Google Calendar API**.
3. Click on it and press **Enable**.

#### Step 3: Create a service account

1. Navigate to **APIs & Services > Credentials** (or go to [Credentials](https://console.cloud.google.com/apis/credentials)).
2. Click **Create Credentials > Service account**.
3. Fill in a name (e.g. "scheduling-agent") and click **Create and Continue**.
4. You can skip the optional "Grant this service account access" and "Grant users access" steps — just click **Done**.
5. You should now see the service account listed on the Credentials page. **Copy the service account email address** (it looks like `scheduling-agent@your-project.iam.gserviceaccount.com`) — you'll need it in Step 5.

#### Step 4: Download the JSON key

1. On the Credentials page, click the service account you just created.
2. Go to the **Keys** tab.
3. Click **Add Key > Create new key**.
4. Select **JSON** and click **Create**.
5. A `.json` file will download automatically. Rename it to `credentials.json` and place it in the **root of this repository** (next to `secrets.env`).

> **Security note:** `credentials.json` is already listed in `.gitignore` and `.dockerignore`, so it won't be committed to version control or baked into Docker images.

#### Step 5: Share your Google Calendar with the service account

Service accounts cannot access your personal calendar by default. You need to explicitly share it:

1. Open [Google Calendar](https://calendar.google.com/) in your browser.
2. In the left sidebar, find the calendar you want the agent to use (e.g. your primary calendar).
3. Click the three-dot menu next to it and select **Settings and sharing**.
4. Scroll down to **Share with specific people or groups** and click **Add people and groups**.
5. Paste the **service account email** from Step 3.
6. Set the permission to **Make changes to events**.
7. Click **Send**.

#### Step 6: Configure environment variables

Add the following lines to your `secrets.env` file:

```
GOOGLE_CALENDAR_CREDENTIALS=credentials.json
GOOGLE_CALENDAR_ID=you@gmail.com
```

- `GOOGLE_CALENDAR_CREDENTIALS` — path to the JSON key file. Use `credentials.json` for local development, or an absolute path like `/app/credentials.json` for Docker.
- `GOOGLE_CALENDAR_ID` — the calendar to create events on. This should be your **email address** (e.g. `you@gmail.com`), which doubles as the calendar ID for your primary Google Calendar. You can also find it under **Settings and sharing > Integrate calendar** in Google Calendar. **Do not use `primary`** — that alias refers to the authenticated account's own calendar, which in a service account setup is the service account's calendar, not yours.

#### Step 7: Verify the setup

Start the server and make a test call that results in a scheduled appointment. The post-call agent will attempt to call `create_calendar_event` and you should see the event appear in your Google Calendar. If credentials are misconfigured, you'll see a `RuntimeError` in the server logs pointing to the missing env var or file.

#### Troubleshooting

| Problem | Fix |
|---------|-----|
| `RuntimeError: GOOGLE_CALENDAR_CREDENTIALS env var not set` | Add `GOOGLE_CALENDAR_CREDENTIALS=credentials.json` to `secrets.env`. |
| `RuntimeError: Credentials file not found` | Make sure `credentials.json` exists at the path specified and is readable. |
| `403 Forbidden` / insufficient permissions | Ensure you shared the calendar with the service account email and set permission to **Make changes to events**. |
| `403 Calendar API has not been used in project` | Go back to the Cloud Console and verify the Google Calendar API is **enabled** for your project. |
| Events created but not visible | Double-check `GOOGLE_CALENDAR_ID` — use `primary` or the correct calendar ID from Google Calendar settings. |

## API Endpoints

All endpoints except `/health` require `Authorization: Bearer <token>`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (unauthenticated) |
| GET | `/prompts` | List available outgoing-call prompts |
| POST | `/incoming-call` | Twilio voice webhook (validated via Twilio signature) |
| POST | `/outgoing-call` | Initiate an outgoing call |
| WS | `/media-stream` | WebSocket for incoming calls |
| WS | `/media-stream/{call_id}` | WebSocket for outgoing calls |
| SSE | `/mcp/sse` | MCP server endpoint |

## Docker Deployment

Build and run with Docker Compose:

```bash
docker compose up --build
```

This mounts `secrets.env`, `user_info.yaml.enc`, and `credentials.json` at runtime so secrets are never baked into the image. The Dockerfile uses [uv](https://docs.astral.sh/uv/) for fast, reproducible installs.

To build the image standalone:

```bash
docker build -t scheduling-agent .
docker run --rm -p 2255:2255 \
  --env-file secrets.env \
  -v $(pwd)/user_info.yaml.enc:/app/user_info.yaml.enc:ro \
  -v $(pwd)/credentials.json:/app/credentials.json:ro \
  -e GOOGLE_CALENDAR_CREDENTIALS=/app/credentials.json \
  scheduling-agent
```

### Runpod Deployment

1. Push the image to a container registry (Docker Hub, GHCR, etc.).
2. Create a Runpod Serverless or Pod endpoint using the image.
3. Inject secrets via Runpod's **Environment Variables** settings.
4. Mount `user_info.yaml.enc` and `credentials.json` via Runpod **Network Volumes**.
5. Expose port 2255 and point your Twilio webhooks at the Runpod URL.

> **Security:** Secrets are never baked into the image. The `.dockerignore` excludes `secrets.env`, `credentials.json`, and `user_info.yaml*`. All sensitive data is injected at runtime.

## Architecture

```
  MCP Client  ──────►  ┌──────────────┐
  (e.g. Claude)        │  MCP Server  │ (/mcp/sse, bearer auth)
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
                       │ (Realtime)   │      (gpt-realtime-2)
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

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `2255` | HTTP server port |
| `DOMAIN` | — | Public hostname (no `https://` prefix) |
| `API_BEARER_TOKEN` | random | Token for all API and MCP access |
| `RATE_LIMIT_CALLS_PER_HOUR` | `30` | Max outgoing calls per hour per token |
| `DATA_DIR` | `./data` | Directory for SQLite database |
| `TWILIO_SIGNATURE_VALIDATION` | `true` | Set to `false` for local dev only |
| `GOOGLE_CALENDAR_ID` | — | Calendar ID (omit to disable calendar) |
| `GOOGLE_CALENDAR_CREDENTIALS` | — | Path to service account JSON key |

## Security

- **Bearer token is required** for all API endpoints (`/prompts`, `/outgoing-call`) and the MCP server (`/mcp/sse`). If `API_BEARER_TOKEN` is not set, a random token is generated and printed to the log on startup.
- **The MCP endpoint should not be exposed publicly without auth.** The bearer middleware on `/mcp/sse` enforces this, but double-check your reverse proxy or tunnel configuration.
- **Rotate credentials** if they are ever exposed: `API_BEARER_TOKEN`, `OPENAI_API_KEY`, `TWILIO_AUTH_TOKEN`, and `USER_INFO_SECRET`. Each is injected at runtime and never baked into the Docker image.
- **Twilio signature validation** is enabled by default. Only disable it (`TWILIO_SIGNATURE_VALIDATION=false`) for local development — without it, anyone who knows your webhook URL can trigger incoming-call handling.
