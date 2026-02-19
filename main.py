import os

import uvicorn
from dotenv import load_dotenv

load_dotenv("secrets.env")

from server import app

print(os.getenv("DOMAIN"))
print(os.getenv("PHONE_NUMBER_FROM"))
print(os.getenv("TWILIO_ACCOUNT_SID"))
print(os.getenv("TWILIO_AUTH_TOKEN"))
print(os.getenv("OPENAI_API_KEY"))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
