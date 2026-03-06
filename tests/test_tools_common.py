"""Tests for src.tools.common — get_weather and get_current_time.

These are @function_tool-decorated, so we invoke them via
``on_invoke_tool(ctx, json_input)`` with a stub context.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.tools.common import get_current_time, get_weather


def _ctx() -> MagicMock:
    """Minimal ToolContext stub."""
    return MagicMock()


class TestGetCurrentTime:
    @pytest.mark.asyncio
    async def test_returns_current_time_string(self):
        result = await get_current_time.on_invoke_tool(_ctx(), "{}")
        assert "The current time is" in result
        time_str = result.split()[-1]
        datetime.strptime(time_str, "%H:%M:%S")


class TestGetWeather:
    def _geo_response(self, name: str = "Paris", lat: float = 48.85, lon: float = 2.35) -> dict:
        return {"results": [{"name": name, "latitude": lat, "longitude": lon}]}

    def _weather_response(self, temp: float = 72.0) -> dict:
        return {"current": {"temperature_2m": temp, "weather_code": 0}}

    @pytest.mark.asyncio
    async def test_successful_weather(self):
        mock_responses = [
            MagicMock(json=MagicMock(return_value=self._geo_response())),
            MagicMock(json=MagicMock(return_value=self._weather_response(72.0))),
        ]
        with patch.object(httpx, "get", side_effect=mock_responses):
            result = await get_weather.on_invoke_tool(_ctx(), json.dumps({"city": "Paris"}))

        assert "72.0°F" in result
        assert "Paris" in result

    @pytest.mark.asyncio
    async def test_city_not_found(self):
        mock_resp = MagicMock(json=MagicMock(return_value={"results": None}))
        with patch.object(httpx, "get", return_value=mock_resp):
            result = await get_weather.on_invoke_tool(_ctx(), json.dumps({"city": "Nowheresville"}))

        assert "Could not find location" in result

    @pytest.mark.asyncio
    async def test_empty_results_list(self):
        mock_resp = MagicMock(json=MagicMock(return_value={}))
        with patch.object(httpx, "get", return_value=mock_resp):
            result = await get_weather.on_invoke_tool(_ctx(), json.dumps({"city": "Ghost"}))

        assert "Could not find location" in result

    @pytest.mark.asyncio
    async def test_network_error(self):
        with patch.object(httpx, "get", side_effect=httpx.ConnectError("timeout")):
            result = await get_weather.on_invoke_tool(_ctx(), json.dumps({"city": "Paris"}))

        assert "Failed to fetch weather" in result
