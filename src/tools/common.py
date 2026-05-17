from datetime import datetime

import httpx
from agents import function_tool

_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


@function_tool
def get_weather(city: str) -> str:
    """Get the current weather for a city using the Open-Meteo API."""
    try:
        geo = httpx.get(
            _GEOCODING_URL,
            params={"name": city, "count": 1},
            timeout=10,
        ).json()

        results = geo.get("results")
        if not results:
            return f"Could not find location: {city}"

        location = results[0]
        lat, lon = location["latitude"], location["longitude"]

        weather = httpx.get(
            _WEATHER_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code",
                "temperature_unit": "fahrenheit",
            },
            timeout=10,
        ).json()

        current = weather["current"]
        return f"{current['temperature_2m']}°F in {location['name']}"
    except Exception as e:
        return f"Failed to fetch weather for {city}: {e}"


@function_tool
def get_current_time() -> str:
    """Get the current time."""
    return f"The current time is {datetime.now().strftime('%H:%M:%S')}"
