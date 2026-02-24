"""Chainlit chat application mounted as a sub-app on the main FastAPI server."""

from __future__ import annotations

import chainlit as cl

from src.agent_factory.chat.agent import ChatAgentManager

_chat_manager: ChatAgentManager | None = None

_MAX_TURNS = 50


def _get_chat_manager() -> ChatAgentManager:
    """Lazily build the ChatAgentManager.

    Deferred so that ``src.server`` is fully loaded before we touch its
    globals (the module is still being evaluated when ``mount_chainlit``
    runs).
    """
    global _chat_manager
    if _chat_manager is not None:
        return _chat_manager

    from src.server import _get_config, manager
    from twilio.rest import Client as TwilioClient

    cfg = _get_config()
    twilio_client = TwilioClient(cfg["twilio_account_sid"], cfg["twilio_auth_token"])
    _chat_manager = ChatAgentManager(
        ws_manager=manager,
        twilio_client=twilio_client,
        phone_from=cfg["phone_number_from"] or "",
        domain=cfg["domain"] or "",
    )
    return _chat_manager


@cl.on_chat_start
async def on_chat_start() -> None:
    cl.user_session.set("history", [])


@cl.on_message
async def on_message(message: cl.Message) -> None:
    history: list[dict[str, str]] = cl.user_session.get("history")  # type: ignore[assignment]
    history.append({"role": "user", "content": message.content})

    mgr = _get_chat_manager()
    reply = await mgr.handle_message(history)

    history.append({"role": "assistant", "content": reply})

    if len(history) > _MAX_TURNS * 2:
        history = history[-_MAX_TURNS * 2 :]

    cl.user_session.set("history", history)
    await cl.Message(content=reply).send()
