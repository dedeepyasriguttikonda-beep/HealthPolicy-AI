"""Configuration: environment variables + the source registry (config/sources.yaml)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

try:  # optional, lets users keep keys in a .env file
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
FIXTURE_DIR = DATA_DIR / "fixtures"
OUTPUT_DIR = ROOT / "outputs"
SOURCES_FILE = ROOT / "config" / "sources.yaml"


@dataclass
class Source:
    id: str
    name: str
    url: str
    category: str
    region: str
    authority: str
    enabled: bool = True
    fixture: str | None = None


@dataclass
class Settings:
    firecrawl_api_key: str | None = field(default_factory=lambda: os.getenv("FIRECRAWL_API_KEY"))
    # gemini | openai | groq | offline
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "gemini").lower())
    llm_model: str | None = field(default_factory=lambda: os.getenv("LLM_MODEL"))
    gemini_api_key: str | None = field(default_factory=lambda: os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    groq_api_key: str | None = field(default_factory=lambda: os.getenv("GROQ_API_KEY"))
    memento_db: Path = field(default_factory=lambda: Path(os.getenv("MEMENTO_DB", str(DATA_DIR / "memento.db"))))
    # "local" (built-in SQLite Memento store) or "memento-memory" (also mirror into the memento-memory knowledge graph)
    memento_backend: str = field(default_factory=lambda: os.getenv("MEMENTO_BACKEND", "local"))
    # similarity above which an edited item counts as cosmetic (not a meaningful change)
    change_threshold: float = field(default_factory=lambda: float(os.getenv("CHANGE_THRESHOLD", "0.97")))


def load_sources(path: Path = SOURCES_FILE, only_enabled: bool = True) -> list[Source]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    sources = [Source(**s) for s in raw["sources"]]
    return [s for s in sources if s.enabled] if only_enabled else sources
