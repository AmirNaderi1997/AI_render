"""Word-level transcription using faster-whisper.

Produces jobs/<id>/transcript.json with words and sentences.
Caches by file hash so the same file is never re-transcribed.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "small"


def file_hash(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()[:16]


def transcribe(
    video: Path,
    out_dir: Path,
    model_size: Optional[str] = None,
    language: Optional[str] = None,
    device: str = "cpu",
    compute_type: str = "int8",
) -> dict:
    """Transcribe *video* and write transcript.json to *out_dir*.

    Returns the transcript dict: {words, sentences, language, duration}.
    If a cached transcript exists for the same file hash, returns it immediately.
    """
    from faster_whisper import WhisperModel

    video = Path(video).resolve()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = out_dir / "transcript.json"

    fhash = file_hash(video)

    if transcript_path.exists():
        cached = json.loads(transcript_path.read_text())
        if cached.get("file_hash") == fhash:
            log.info("transcript cache hit for %s", video.name)
            return cached

    model_size = model_size or _DEFAULT_MODEL
    log.info("loading whisper model %r (device=%s, compute=%s)", model_size, device, compute_type)
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    log.info("model cache dir: %s", model.model_path if hasattr(model, "model_path") else "unknown")

    log.info("transcribing %s …", video.name)

    # Extract audio to WAV first to avoid av package version issues
    import subprocess
    wav_path = out_dir / "audio_tmp.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vn", "-acodec", "pcm_s16le",
         "-ar", "16000", "-ac", "1", str(wav_path)],
        capture_output=True, check=True,
    )

    # Monkey-patch av.open to drop metadata_errors kwarg (removed in av 19.0)
    import av
    _real_av_open = av.open
    def _patched_av_open(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _real_av_open(*args, **kwargs)
    av.open = _patched_av_open

    segments_iter, info = model.transcribe(
        str(wav_path),
        word_timestamps=True,
        vad_filter=True,
        language=language,
    )
    # Clean up temp wav after iteration is consumed (see below)

    words: list[dict] = []
    sentences: list[dict] = []
    current_sentence_words: list[dict] = []

    for seg in segments_iter:
        if not seg.words:
            continue
        for w in seg.words:
            entry = {
                "w": w.word.strip(),
                "start": round(w.start, 3),
                "end": round(w.end, 3),
                "prob": round(w.probability, 3),
            }
            words.append(entry)
            current_sentence_words.append(entry)

        if current_sentence_words:
            text = " ".join(wd["w"] for wd in current_sentence_words)
            sentences.append({
                "text": text,
                "start": current_sentence_words[0]["start"],
                "end": current_sentence_words[-1]["end"],
            })
            current_sentence_words = []

    if current_sentence_words:
        text = " ".join(wd["w"] for wd in current_sentence_words)
        sentences.append({
            "text": text,
            "start": current_sentence_words[0]["start"],
            "end": current_sentence_words[-1]["end"],
        })

    detected_lang = info.language if info else (language or "unknown")
    duration = info.duration if info else (words[-1]["end"] if words else 0.0)

    transcript = {
        "file_hash": fhash,
        "language": detected_lang,
        "duration": round(duration, 3),
        "words": words,
        "sentences": sentences,
    }

    transcript_path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))
    log.info("transcribed %d words, %d sentences, lang=%s", len(words), len(sentences), detected_lang)

    av.open = _real_av_open
    try:
        wav_path.unlink(missing_ok=True)
    except Exception:
        pass

    return transcript
