from dataclasses import dataclass, field
from pathlib import Path
import json, os

ROOT = Path(__file__).resolve().parents[2]

@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: ROOT / '.local/character-ai')
    api_key: str = field(default='', repr=False)
    client_token: str = field(default='', repr=False)
    admin_token: str = field(default='', repr=False)
    host: str = 'https://dashscope.aliyuncs.com'
    character_model: str = 'qwen-plus-character'
    # Suggestions predict the user's next turn; they do not role-play the avatar.
    suggestions_model: str = 'qwen-turbo'
    translation_model: str = 'qwen-mt-flash'
    tts_model: str = 'qwen-audio-3.1-tts-flash'
    asr_model: str = 'fun-asr-realtime'
    max_daily_calls: int = 60
    max_daily_tts_characters: int = 3000
    max_daily_asr_seconds: int = 180
    max_voice_designs: int = 2
    # Normal conversation is not a development smoke test. Old stored daily
    # thresholds are inert unless an operator explicitly opts back in.
    enforce_conversation_limits: bool = False
    # Runs beside audio, never before the first progressive text response.
    narration_timeout_seconds: float = 8.0
    performance_timeout_seconds: float = 8.0
    reaction_pool_size: int = 1
    reaction_pool_ttl_seconds: float = 900
    entry_pool_ttl_seconds: float = 86400
    paid_enabled: bool = True
    # Testing deployments explicitly opt in; public deployments expose no
    # authored prompts, private persona, memory or provider request inspector.
    enable_test_inspector: bool = False
    # Provision with scripts/prepare_reply_novelty.py; no runtime downloads.
    semantic_novelty: bool = False

    @classmethod
    def load(cls):
        path = Path(os.environ.get('STARRY_AI_CONFIG', ROOT / '.local/character-ai/settings.json'))
        data = json.loads(path.read_text()) if path.exists() else {}
        result = cls(**{k:v for k,v in data.items() if k in cls.__dataclass_fields__})
        result.data_dir = Path(result.data_dir)
        if os.environ.get('STARRY_AI_DISABLE_PAID') == '1': result.paid_enabled = False
        if not result.host.startswith('https://') or not result.host.endswith('.aliyuncs.com'):
            raise ValueError('Provider host must be an Alibaba HTTPS endpoint')
        return result
