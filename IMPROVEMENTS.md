# Improvements

Tracked best-practice improvements for the codebase. Items are roughly ordered by impact.

## Use `logging` instead of `print()` everywhere

Every module uses `print()` for diagnostics. Python's `logging` module provides levels, timestamps, structured output, and configurability (e.g., shipping logs to a file or external service). In a telephony app where you need to debug call flows, this matters.

```python
# before
print(f"SMS sent to {to}: sid={message.sid}")

# after
import logging
logger = logging.getLogger(__name__)
logger.info("SMS sent to %s: sid=%s", to, message.sid)
```

Configure a root logger in `main.py` and use `logging.getLogger(__name__)` per module.

## Add `__init__.py` files to all packages

`src/`, `src/agents/`, and `src/tools/` all lack `__init__.py` files. While Python 3.3+ implicit namespace packages can technically make this work, it's fragile for application code with relative imports (like `from ..tools.google_calendar import ...`). Explicit `__init__.py` files signal intent and let tools like `mypy`, `pytest`, and IDE linting resolve packages reliably.

## Rename `src/agents/` to avoid collision with `agents` library

The third-party package is called `agents` (from `openai-agents`), and the local directory is also called `src/agents/`. This works today because of the `src.` prefix, but it's confusing — a reader seeing `from agents.realtime import RealtimeAgent` in `twilio_handler.py` naturally assumes it references the local `src/agents/` directory, when it actually imports from the third-party package. Renaming the local directory (e.g., `src/agent_factory/`) removes the ambiguity.

## Validate Twilio webhook signatures

None of the Twilio webhook endpoints (`/incoming-call`, `/incoming-sms`) validate the `X-Twilio-Signature` header. Anyone who discovers the public URL can forge requests. Twilio provides `RequestValidator` for this:

```python
from twilio.request_validator import RequestValidator

validator = RequestValidator(auth_token)
is_valid = validator.validate(url, params, signature)
```

For a system that makes phone calls and handles PII, this is a meaningful security gap. Can be implemented as FastAPI middleware or a dependency.

## Use the TwiML builder instead of f-string XML

Constructing raw XML with f-strings is error-prone and risks XML injection if any user-controlled value ever flows into the template. The Twilio SDK ships `VoiceResponse` / `MessagingResponse` builders:

```python
from twilio.twiml.voice_response import VoiceResponse, Connect

response = VoiceResponse()
response.say("Hello! You're now connected to an AI assistant.")
connect = Connect()
connect.stream(url=f"wss://{host}/media-stream")
response.append(connect)
return PlainTextResponse(content=str(response), media_type="text/xml")
```

Applies to `server.py` (incoming call, outgoing call, incoming SMS) and `src/tools/sms.py`.

## Eliminate module-level side effects

`src/prompts.py` loads all YAML files at import time, and `src/agents/realtime.py` decrypts user info at import time. If a file is missing or the decryption secret isn't set, the app crashes on import rather than at the point of use. Lazy loading (like the existing `_get_sms_manager()` pattern in `server.py`) is more resilient and testable.

## Stop recreating the Twilio client in `send_sms`

`src/sms.py` constructs a new `TwilioClient` on every invocation of `send_sms()`, reading env vars each time. `server.py` already has a Twilio client instance. Either inject the client as a parameter or cache it at module level. This function runs on every completed call via the post-call handler.

## Make `TwilioHandler` constants class-level

`CHUNK_LENGTH_S`, `SAMPLE_RATE`, and `BUFFER_SIZE_BYTES` are set as instance attributes in `__init__` but use ALL_CAPS naming, which conventionally means class-level or module-level constants. They should be class attributes:

```python
class TwilioHandler:
    CHUNK_LENGTH_S = 0.05
    SAMPLE_RATE = 8000
    BUFFER_SIZE_BYTES = int(SAMPLE_RATE * CHUNK_LENGTH_S)
```

## Improve task lifecycle / cleanup in `TwilioHandler`

Three `asyncio.Task`s are spawned in `start()`, but only the Twilio message loop's `finally` block cancels the other two. If `start()` fails after creating `_realtime_session_task` but before `_message_loop_task`, the realtime task leaks. An async context manager (`__aenter__` / `__aexit__`) or a structured `try/finally` in `start()` would be more robust.

## Read env vars lazily in `server.py`

`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, etc. are captured at import time. In tests or when env is injected later (e.g., via a FastAPI lifespan event), they'll be `None`. Reading them lazily or via a config object / FastAPI dependency would be more testable and less order-dependent.

## Replace `get_weather` stub with Open-Meteo

The current `get_weather` tool returns a hardcoded joke. [Open-Meteo](https://open-meteo.com/) is a free, open-source weather API that requires no sign-up or API key:

```python
import httpx

async def get_weather(city: str) -> str:
    # Step 1: geocode the city name
    geo = httpx.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1},
    ).json()
    location = geo["results"][0]
    lat, lon = location["latitude"], location["longitude"]

    # Step 2: fetch current weather
    weather = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weather_code",
            "temperature_unit": "fahrenheit",
        },
    ).json()
    current = weather["current"]
    return f"{current['temperature_2m']}°F in {location['name']}"
```

## Give `end_call` a return value

`end_call` in `src/tools/common.py` has no body and implicitly returns `None`. The agents SDK may or may not handle this gracefully. At minimum return a confirmation string so the model sees feedback.

## Add type checking with `mypy`

The codebase uses type hints consistently, but there's no type checker configured. Adding `mypy` (with a `py.typed` marker and config in `pyproject.toml`) would catch issues — especially around the `Any` types in `SmsAgentManager`.

## Evict stale SMS conversations

`SmsAgentManager._conversations` has per-number turn trimming, but the dict itself never evicts stale phone numbers. Over a long-running deployment, this is a slow memory leak. A simple TTL-based eviction or an LRU cache would fix it.
