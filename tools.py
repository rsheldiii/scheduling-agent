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
def get_user_info(field: str) -> str:
    """Look up a piece of personal information about the user, such as
    'name', 'date_of_birth', 'ssn_last_four', etc."""
    from user_info import load_user_info

    info = load_user_info()
    if field in info:
        return str(info[field])
    available = ", ".join(sorted(info.keys()))
    return f"No information found for '{field}'. Available fields: {available}"


@function_tool
def end_call() -> str:
    """End the call."""
