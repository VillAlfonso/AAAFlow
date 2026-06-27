"""Built-in voice catalog + language metadata for the CustomVoice model.

The 9 speakers and their descriptions come straight from the Qwen3-TTS model
card. Every speaker can speak any supported language, but each sounds most
natural in its native language. Gender/recommendation fields are for UI
grouping only.
"""
from __future__ import annotations

from typing import Dict, List

# language values accepted by model.get_supported_languages(); "Auto" lets the
# model infer the language from the text.
LANGUAGES: List[str] = [
    "Auto", "English", "Chinese", "Japanese", "Korean", "German",
    "French", "Russian", "Portuguese", "Spanish", "Italian",
]

# Built-in CustomVoice speakers. `id` is the exact value passed to the model.
SPEAKERS: List[Dict] = [
    {"id": "Ryan", "gender": "male", "native": "English",
     "desc": "Dynamic male voice with strong rhythmic drive.", "youtube": True},
    {"id": "Aiden", "gender": "male", "native": "English",
     "desc": "Sunny American male voice with a clear midrange.", "youtube": True},
    {"id": "Serena", "gender": "female", "native": "Chinese",
     "desc": "Warm, gentle young female voice.", "youtube": True},
    {"id": "Vivian", "gender": "female", "native": "Chinese",
     "desc": "Bright, slightly edgy young female voice.", "youtube": True},
    {"id": "Uncle_Fu", "gender": "male", "native": "Chinese",
     "desc": "Seasoned male voice with a low, mellow timbre.", "youtube": False},
    {"id": "Dylan", "gender": "male", "native": "Chinese (Beijing)",
     "desc": "Youthful Beijing male voice with a clear, natural timbre.", "youtube": False},
    {"id": "Eric", "gender": "male", "native": "Chinese (Sichuan)",
     "desc": "Lively Chengdu male voice with a slightly husky brightness.", "youtube": False},
    {"id": "Ono_Anna", "gender": "female", "native": "Japanese",
     "desc": "Playful Japanese female voice with a light, nimble timbre.", "youtube": False},
    {"id": "Sohee", "gender": "female", "native": "Korean",
     "desc": "Warm Korean female voice with rich emotion.", "youtube": False},
]

SPEAKER_IDS = {s["id"].lower() for s in SPEAKERS}

# Short, natural lines for the "preview voice" button, per language.
PREVIEW_TEXTS: Dict[str, str] = {
    "English": "Hey everyone, welcome back to the channel. Let's get straight into it.",
    "Chinese": "大家好，欢迎回到我的频道，我们马上开始吧。",
    "Japanese": "皆さん、こんにちは。チャンネルへようこそ。さっそく始めましょう。",
    "Korean": "여러분 안녕하세요, 채널에 오신 것을 환영합니다. 바로 시작할게요.",
    "German": "Hallo zusammen und willkommen zurück auf dem Kanal. Legen wir los.",
    "French": "Salut tout le monde, bienvenue sur la chaîne. Entrons dans le vif du sujet.",
    "Russian": "Всем привет и добро пожаловать на канал. Давайте сразу начнём.",
    "Portuguese": "Olá a todos, bem-vindos de volta ao canal. Vamos direto ao assunto.",
    "Spanish": "Hola a todos, bienvenidos de nuevo al canal. Vamos directos al grano.",
    "Italian": "Ciao a tutti, bentornati sul canale. Andiamo subito al punto.",
}


def display_name(speaker_id: str) -> str:
    return speaker_id.replace("_", " ")


def preview_text(language: str) -> str:
    if language in PREVIEW_TEXTS:
        return PREVIEW_TEXTS[language]
    return PREVIEW_TEXTS["English"]


# Curated example "voice design" prompts to make that feature approachable.
DESIGN_PRESETS: List[Dict] = [
    {"name": "Documentary Narrator",
     "instruct": "A calm, authoritative middle-aged male narrator with a warm, "
                 "resonant voice and measured, deliberate pacing, like a nature documentary."},
    {"name": "Energetic Vlogger",
     "instruct": "An upbeat, fast-talking young female voice, bright and friendly, "
                 "with lots of energy and a smile you can hear."},
    {"name": "Late-Night Radio",
     "instruct": "A smooth, deep, intimate male voice, slow and relaxed, like a "
                 "late-night radio host speaking close to the mic."},
    {"name": "Storyteller",
     "instruct": "A gentle, expressive storyteller voice, soft and inviting, with "
                 "natural rises and falls as if reading a bedtime story."},
]
