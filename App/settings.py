import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("EMBED_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "liquid/lfm-3-1.7b:free")
EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-base")
TOP_K = 5
MIN_SCORE = 0.35
