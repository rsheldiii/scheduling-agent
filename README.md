# Realtime Scheduling Agent

An agentic appointment-scheduling application that connects the OpenAI Realtime API to phone calls via Twilio Media Streams. The agent can make and receive calls, create Google Calendar events, and be orchestrated entirely over SMS.

## Prerequisites

- Python 3.9+
- OpenAI API key with [Realtime API](https://platform.openai.com/docs/guides/realtime) access
- [Twilio](https://www.twilio.com/docs/voice) account with a phone number
- A tunneling service like [ngrok](https://ngrok.com/) to expose your local server
- (Optional) Google Cloud service account with Calendar API enabled

## Setup

1. **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

2. **Configure secrets.** Copy the template and fill in your values:

    ```
    OPENAI_API_KEY=sk-...
    TWILIO_ACCOUNT_SID=AC...
    TWILIO_AUTH_TOKEN=...
    PHONE_NUMBER_FROM=+1...
    DOMAIN=your-ngrok-url.ngrok.io
    USER_INFO_SECRET=your-encryption-password
    GOOGLE_CALENDAR_CREDENTIALS=credentials.json   # optional
    GOOGLE_CALENDAR_ID=primary                      # optional
    ```

3. **Set up user info.** Edit `user_info.yaml` with your details (including `phone_number` for SMS summaries), then encrypt:

    ```bash
    python user_info.py encrypt
    ```

4. **Start the server:**

    ```bash
    python main.py
    ```

5. **Expose the server publicly:**

    ```bash
    ngrok http 8000
    ```

6. **Configure your Twilio phone number:**
    - Set the **Voice** webhook to: `https://<domain>/incoming-call` (POST)
    - Set the **Messaging** webhook to: `https://<domain>/incoming-sms` (POST)

## Features

### Voice Calls (Incoming & Outgoing)

- **Incoming:** Call the Twilio number and talk to the AI assistant in real time.
- **Outgoing:** `POST /outgoing-call` with `{"to": "+1...", "prompt": "doctor_appointment"}` to have the agent call on your behalf.
- Prompts are YAML files in `prompts/outgoing/` — add new scenarios by dropping in a new file.

### Post-Call Processing

When a call ends, the captured transcript is handed to a non-realtime post-call agent that:

1. Determines whether an appointment was scheduled.
2. Creates a Google Calendar event if so.
3. Sends the user an SMS summary of the call.

### SMS / Texting

Text the Twilio number to interact with a non-realtime chat agent. The SMS agent can:

- List available call prompts.
- Initiate outgoing calls on your behalf.
- Look up your personal information.

Multi-turn conversation state is maintained per phone number.

### Google Calendar Integration

Requires a Google Cloud service account:

1. Enable the Calendar API in your Google Cloud project.
2. Create a service account and download the JSON key as `credentials.json`.
3. Share your Google Calendar with the service account email.
4. Set `GOOGLE_CALENDAR_CREDENTIALS` and `GOOGLE_CALENDAR_ID` in `secrets.env`.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Health check |
| GET | `/prompts` | List available outgoing-call prompts |
| POST/GET | `/incoming-call` | Twilio voice webhook |
| POST | `/outgoing-call` | Initiate an outgoing call |
| POST | `/incoming-sms` | Twilio SMS webhook |
| WS | `/media-stream` | WebSocket for incoming calls |
| WS | `/media-stream/{call_id}` | WebSocket for outgoing calls |

## Docker Deployment

Build and run with Docker Compose:

```bash
docker compose up --build
```

This mounts `secrets.env`, `user_info.yaml.enc`, and `credentials.json` at runtime so secrets are never baked into the image.

To build the image standalone:

```bash
docker build -t scheduling-agent .
docker run --rm -p 8000:8000 \
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
5. Expose port 8000 and point your Twilio webhooks at the Runpod URL.

> **Security:** Secrets are never baked into the image. The `.dockerignore` excludes `secrets.env`, `credentials.json`, and `user_info.yaml*`. All sensitive data is injected at runtime.

## Architecture

```
                      ┌──────────────┐
  Phone Call ──────►  │    Twilio     │
                      └──────┬───────┘
                   Voice ▼        ▲ SMS
              ┌──────────────┐  ┌──────────────┐
              │  TwilioHandler│  │  SmsAgent    │
              │  (Realtime)   │  │  (Non-RT)    │
              └──────┬───────┘  └──────┬───────┘
                     ▼                 │
              ┌──────────────┐         │
              │ OpenAI RT API│         │
              └──────┬───────┘         │
                     ▼                 ▼
              ┌──────────────┐  ┌──────────────┐
              │ Post-Call    │  │ Orchestrate  │
              │ Agent (Non-RT)│  │ Outgoing Call│
              └──────┬───────┘  └──────────────┘
                     ▼
              ┌──────────────┐
              │Google Calendar│
              └──────────────┘
```

## Configuration

- **Port**: `PORT` env var (default: 8000)
- **Prompts**: YAML files in `prompts/{incoming,outgoing,sms}/`
- **User Info**: Encrypted in `user_info.yaml.enc`, decrypted at runtime with `USER_INFO_SECRET`
- **Tools**: Defined in `tools.py` and `google_calendar.py`
