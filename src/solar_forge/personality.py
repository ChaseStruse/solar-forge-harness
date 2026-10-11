"""One shared voice for conversational and structured model prompts."""
from importlib.resources import files

PERSONALITY = files('solar_forge').joinpath('guidance/personality.md').read_text(encoding='utf-8')
