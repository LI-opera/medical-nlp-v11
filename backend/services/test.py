import os
from dotenv import load_dotenv
print("before load:", repr(os.getenv("DEEPSEEK_API_KEY")))

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
ENV_PATH = os.path.join(BACKEND_DIR, ".env")
load_dotenv(ENV_PATH, override=True)

print("after load:", repr(os.getenv("DEEPSEEK_API_KEY")))