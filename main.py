import os

import uvicorn
from dotenv import load_dotenv

load_dotenv("secrets.env")

from src.server import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
