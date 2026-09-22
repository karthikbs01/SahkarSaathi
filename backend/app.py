"""HTTP adapter for the existing SahkarSaathi RAG pipeline."""
import sys
from pathlib import Path
from threading import Lock
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from generate_rag_answer import run, precheck  # noqa: E402
from backend.conversation_context import contextualize  # noqa: E402
from backend.bhashini_service import (BhashiniError, SUPPORTED_LANGUAGES,
                                      synthesize_speech, transcribe_audio,
                                      translate_text)  # noqa: E402

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["POST"],
    allow_headers=["*"],
)
generation_lock = Lock()
MAX_AUDIO_BYTES = 5 * 1024 * 1024
MAX_TTS_TEXT_LENGTH = 4000


class HistoryMessage(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(max_length=4000)
    language: Literal['en', 'kn', 'hi', 'mr'] | None = None


class ChatRequest(BaseModel):
    question: str
    jurisdiction: str | None = None
    language: str | None = "en"
    conversation_history: list[HistoryMessage] = Field(default_factory=list, max_length=4)


class TranslationRequest(BaseModel):
    text: str
    source_language: str
    target_language: str


class TTSRequest(BaseModel):
    text: str
    language: str


def audio_format(filename: str | None, content_type: str | None, audio: bytes) -> str | None:
    suffix = Path(filename or "").suffix.casefold()
    formats = {
        ".wav": ("wav", audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"),
        ".flac": ("flac", audio[:4] == b"fLaC"),
        ".mp3": ("mp3", audio[:3] == b"ID3" or audio[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}),
    }
    value = formats.get(suffix)
    if not value or not value[1]:
        return None
    if content_type and content_type not in {"audio/wav", "audio/x-wav", "audio/flac", "audio/mpeg"}:
        return None
    return value[0]


def normalize_jurisdiction(value: str | None) -> str:
    normalized = (value or "").strip().casefold()
    mapping = {
        "karnataka": "Karnataka",
        "maharashtra": "Maharashtra",
        "multi-state cooperative": "Multi-State",
        "central / india scheme": "India",
        "not sure": "Unknown",
        "": "Unknown",
    }
    if normalized not in mapping:
        raise HTTPException(status_code=400, detail="Please choose a supported jurisdiction.")
    return mapping[normalized]


def provider_error(result: dict) -> HTTPException | None:
    reason = str(result["response"].get("abstention_reason") or "")
    if reason == "GROQ_HTTP_429":
        return HTTPException(status_code=429, detail="The answer service is busy. Please try again shortly.")
    if reason == "GROQ_HTTP_413":
        return HTTPException(status_code=413, detail="The request is too large to process.")
    if reason.startswith("GROQ_") or reason in {"RETRIEVAL_ERROR", "CITATION_VALIDATION_FAILED"}:
        return HTTPException(status_code=502, detail="The answer service is temporarily unavailable.")
    return None


def translate_or_error(text: str, source_language: str, target_language: str) -> str:
    try:
        translated = translate_text(text, source_language, target_language)
    except (BhashiniError, RuntimeError, ValueError, TypeError):
        raise HTTPException(status_code=502, detail="Translation is temporarily unavailable.")
    if not isinstance(translated, str) or not translated.strip():
        raise HTTPException(status_code=502, detail="Translation is temporarily unavailable.")
    return translated.strip()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat")
def chat(request: ChatRequest):
    original_question = request.question.strip()
    if not original_question:
        raise HTTPException(status_code=400, detail="Please enter a question.")
    if len(original_question) > 1500:
        raise HTTPException(status_code=400, detail="Please keep the question under 1500 characters.")
    language = (request.language or "en").strip().casefold()
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Please choose a supported language.")
    jurisdiction = normalize_jurisdiction(request.jurisdiction)
    rag_question = original_question if language == "en" else translate_or_error(
        original_question, language, "en")
    rag_question, clarification = contextualize(
        rag_question, request.conversation_history, translate_or_error, precheck, jurisdiction)
    if clarification:
        if language != 'en':
            clarification = translate_or_error(clarification, 'en', language)
        return {'answer': '', 'abstained': True, 'abstention_reason': clarification,
                'jurisdiction': jurisdiction, 'language': language, 'sources': []}
    case = {"id": "API_CHAT", "question": rag_question, "jurisdiction": jurisdiction}
    try:
        with generation_lock:
            _, results = run([case])
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="The backend could not process this request.")

    result = results[0]
    error = provider_error(result)
    if error:
        raise error
    response = result["response"]
    citations = result.get("citations", [])
    answer = response.get("answer", "")
    abstained = bool(response.get("abstained"))
    abstention_reason = response.get("abstention_reason")
    if language != "en":
        if abstained:
            if isinstance(abstention_reason, str) and abstention_reason.strip():
                abstention_reason = translate_or_error(abstention_reason, "en", language)
        else:
            answer = translate_or_error(answer, "en", language)
    sources = [{key: citation.get(key) for key in (
        "source_id", "title", "section", "page_start", "page_end", "source_url")}
        for citation in citations]
    return {
        "answer": answer,
        "abstained": abstained,
        "abstention_reason": abstention_reason,
        "jurisdiction": jurisdiction,
        "language": language,
        "sources": sources,
    }


@app.post("/api/translate")
def translate(request: TranslationRequest):
    try:
        translated = translate_text(request.text, request.source_language, request.target_language)
    except ValueError:
        raise HTTPException(status_code=400, detail="Use non-empty text and supported languages.")
    except RuntimeError:
        raise HTTPException(status_code=500, detail="Translation is not configured.")
    except BhashiniError as error:
        if error.status == 413:
            raise HTTPException(status_code=413, detail="The translation request is too large.")
        if error.status == 429:
            raise HTTPException(status_code=429, detail="Translation is busy. Please try again shortly.")
        raise HTTPException(status_code=502, detail="Translation is temporarily unavailable.")
    return {
        "translated_text": translated,
        "source_language": request.source_language.casefold(),
        "target_language": request.target_language.casefold(),
    }


@app.post("/api/transcribe")
async def transcribe(file: UploadFile | None = File(None), language: str | None = Form(None)):
    if file is None:
        raise HTTPException(status_code=400, detail="Please upload an audio file.")
    normalized_language = (language or "").strip().casefold()
    if normalized_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Please choose a supported language.")
    audio = await file.read(MAX_AUDIO_BYTES + 1)
    if not audio:
        raise HTTPException(status_code=400, detail="Please upload a non-empty audio file.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Please upload an audio file under 5 MB.")
    file_format = audio_format(file.filename, file.content_type, audio)
    if not file_format:
        raise HTTPException(status_code=400, detail="Upload a valid WAV, MP3, or FLAC audio file.")
    try:
        transcript = transcribe_audio(audio, normalized_language, file_format)
    except ValueError:
        raise HTTPException(status_code=400, detail="Use a supported audio format and language.")
    except RuntimeError:
        raise HTTPException(status_code=500, detail="Speech recognition is not configured.")
    except BhashiniError as error:
        if error.status == 413:
            raise HTTPException(status_code=413, detail="The audio request is too large to process.")
        if error.status == 429:
            raise HTTPException(status_code=429, detail="Speech recognition is busy. Please try again shortly.")
        raise HTTPException(status_code=502, detail="Speech recognition is temporarily unavailable.")
    return {"transcript": transcript, "language": normalized_language}


@app.post("/api/tts")
def text_to_speech(request: TTSRequest):
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Please enter text to speak.")
    if len(text) > MAX_TTS_TEXT_LENGTH:
        raise HTTPException(
            status_code=413,
            detail=f"Please keep spoken text under {MAX_TTS_TEXT_LENGTH} characters.",
        )
    language = request.language.strip().casefold()
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Please choose a supported language.")
    try:
        audio, media_type = synthesize_speech(text, language)
    except ValueError:
        raise HTTPException(status_code=400, detail="Use non-empty text and a supported language.")
    except RuntimeError:
        raise HTTPException(status_code=500, detail="Speech synthesis is not configured.")
    except BhashiniError as error:
        if error.status == 413:
            raise HTTPException(status_code=413, detail="The speech request is too large to process.")
        if error.status == 429:
            raise HTTPException(status_code=429, detail="Speech synthesis is busy. Please try again shortly.")
        raise HTTPException(status_code=502, detail="Speech synthesis is temporarily unavailable.")
    return Response(content=audio, media_type=media_type)
