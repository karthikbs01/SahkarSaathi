"""Minimal BHASHINI translation, speech recognition, and speech synthesis client."""
import json
import os
from pathlib import Path
import base64
import re
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_URL = "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"
TRANSLATION_SERVICE_ID = "ai4bharat/indictrans-v2-all-gpu--t4"
TTS_SERVICE_ID = "Bhashini/IITM/TTS"
TTS_SAMPLE_RATE = 16000
SUPPORTED_LANGUAGES = {"en", "kn", "hi", "mr"}
ASR_SERVICE_IDS = {
    "en": "ai4bharat/whisper-medium-en--gpu--t4",
    "kn": "ai4bharat/conformer-multilingual-dravidian-gpu--t4",
    "hi": "ai4bharat/conformer-hi-gpu--t4",
    "mr": "ai4bharat/conformer-multilingual-indo_aryan-gpu--t4",
}


class BhashiniError(Exception):
    def __init__(self, status: int | None):
        self.status = status
        super().__init__("Bhashini request failed")


def _load_inference_key() -> str | None:
    key = os.getenv("BHASHINI_INFERENCE_KEY")
    if key:
        return key
    try:
        lines = (ROOT / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if line.strip().startswith("BHASHINI_INFERENCE_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def translate_text(text: str, source_language: str, target_language: str) -> str:
    source_language = source_language.casefold()
    target_language = target_language.casefold()
    if source_language not in SUPPORTED_LANGUAGES or target_language not in SUPPORTED_LANGUAGES:
        raise ValueError("Unsupported language")
    if not text.strip():
        raise ValueError("Text is required")
    if source_language == target_language:
        return text
    inference_key = _load_inference_key()
    if not inference_key:
        raise RuntimeError("BHASHINI_INFERENCE_KEY is not configured")
    payload = {
        "pipelineTasks": [{
            "taskType": "translation",
            "config": {
                "language": {"sourceLanguage": source_language, "targetLanguage": target_language},
                "serviceId": TRANSLATION_SERVICE_ID,
            },
        }],
        "inputData": {"input": [{"source": text}]},
    }
    request = urllib.request.Request(
        PIPELINE_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Accept": "*/*", "Authorization": inference_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.load(response)
        return body["pipelineResponse"][0]["output"][0]["target"]
    except urllib.error.HTTPError as error:
        raise BhashiniError(error.code) from None
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise BhashiniError(None) from None


def transcribe_audio(audio_bytes: bytes, language: str, audio_format: str) -> str:
    language = language.casefold()
    if language not in SUPPORTED_LANGUAGES or audio_format not in {"wav", "mp3", "flac"}:
        raise ValueError("Unsupported language or audio format")
    if not audio_bytes:
        raise ValueError("Audio is required")
    inference_key = _load_inference_key()
    if not inference_key:
        raise RuntimeError("BHASHINI_INFERENCE_KEY is not configured")
    payload = {
        "pipelineTasks": [{
            "taskType": "asr",
            "config": {
                "language": {"sourceLanguage": language},
                "serviceId": ASR_SERVICE_IDS[language],
                "audioFormat": audio_format,
            },
        }],
        "inputData": {"audio": [{"audioContent": base64.b64encode(audio_bytes).decode("ascii")}]},
    }
    request = urllib.request.Request(
        PIPELINE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Accept": "*/*", "Authorization": inference_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.load(response)
        transcript = body["pipelineResponse"][0]["output"][0]["source"]
    except urllib.error.HTTPError as error:
        raise BhashiniError(error.code) from None
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise BhashiniError(None) from None
    if not isinstance(transcript, str) or not transcript.strip():
        raise BhashiniError(None)
    return re.sub(r"\s+", " ", transcript).strip()


def synthesize_speech(text: str, language: str) -> tuple[bytes, str]:
    """Synthesize the provided text and return audio bytes with its media type."""
    language = language.casefold()
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError("Unsupported language")
    if not text.strip():
        raise ValueError("Text is required")
    inference_key = _load_inference_key()
    if not inference_key:
        raise RuntimeError("BHASHINI_INFERENCE_KEY is not configured")
    payload = {
        "pipelineTasks": [{
            "taskType": "tts",
            "config": {
                "language": {"sourceLanguage": language},
                "serviceId": TTS_SERVICE_ID,
                "gender": "female",
                "samplingRate": TTS_SAMPLE_RATE,
            },
        }],
        "inputData": {"input": [{"source": text}]},
    }
    request = urllib.request.Request(
        PIPELINE_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Accept": "*/*", "Authorization": inference_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.load(response)
        encoded_audio = body["pipelineResponse"][0]["audio"][0]["audioContent"]
        audio = base64.b64decode(encoded_audio, validate=True)
    except urllib.error.HTTPError as error:
        raise BhashiniError(error.code) from None
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError,
            ValueError, json.JSONDecodeError):
        raise BhashiniError(None) from None
    if not audio:
        raise BhashiniError(None)
    if audio[:4] == b"RIFF" and audio[8:12] == b"WAVE":
        media_type = "audio/wav"
    elif audio[:3] == b"ID3" or audio[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
        media_type = "audio/mpeg"
    elif audio[:4] == b"OggS":
        media_type = "audio/ogg"
    elif audio[:4] == b"fLaC":
        media_type = "audio/flac"
    else:
        raise BhashiniError(None)
    return audio, media_type
