import logging
import os
import sys

import uvicorn
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

load_dotenv("secrets.env")

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "serve"

    if command in ("encrypt", "decrypt"):
        from src.tools.user_info import decrypt_and_load, encrypt_file

        if command == "encrypt":
            encrypt_file()
            print("user_info.yaml -> user_info.yaml.enc")
        else:
            import yaml

            info = decrypt_and_load()
            print(yaml.dump(info, default_flow_style=False))
    elif command == "serve":
        from src.server import app

        port = int(os.getenv("PORT", 8000))
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        print(f"Unknown command: {command}")
        print("Usage: python main.py [serve|encrypt|decrypt]")
        sys.exit(1)
