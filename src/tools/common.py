from datetime import datetime

from agents import function_tool


@function_tool
def get_weather(city: str) -> str:
    """Get the weather in a city."""
    return f"The weather in {city} is 69 degrees, with a 420% chance of rain."


@function_tool
def get_current_time() -> str:
    """Get the current time."""
    return f"The current time is {datetime.now().strftime('%H:%M:%S')}"


@function_tool
def end_call() -> str:
    """End the call."""
    return "The call has been ended."
