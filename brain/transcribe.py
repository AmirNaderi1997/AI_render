"""Word-level transcription with settings-aware raw candidates and review overlay."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "small"


def choose_engine(language: Optional[str] = None, explicit: Optional[str] = None) -> str:
    if explicit and explicit in ("elevenlabs", "whisper"):
        return explicit
    env = os.environ.get("ASR_ENGINE", "").lower()
    if env in ("elevenlabs", "whisper"):
        return env
    if (language or "").lower() == "fa" and os.environ.get("ELEVENLABS_API_KEY"):
        return "elevenlabs"
    return "whisper"


def _normalize_persian(text: str) -> str:
    """Normalize Arabic-script look-alikes to standard Persian in a word."""
    return (
        text
        .replace("ي", "ی")  # Arabic ي → Persian ی
        .replace("ى", "ی")  # Arabic alef maqsura → ی
        .replace("ك", "ک")  # Arabic ك → Persian ک
        .replace("ي", "ی")
        .replace("ك", "ک")
    )


def file_hash(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()[:16]


def transcript_key(file_digest: str, model_size: str, language: Optional[str],
                   device: str, compute_type: str, initial_prompt: str = "") -> str:
    settings = {"file_hash": file_digest, "model_size": model_size,
                "language": language, "device": device, "compute_type": compute_type,
                "initial_prompt": initial_prompt.strip(),
                "word_timestamps": True, "vad_filter": True, "beam_size": 5}
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:16]


def _try_hotwords(model, audio, *, language: Optional[str], initial_prompt: Optional[str],
                  hotwords: Optional[list[str]]) -> tuple:
    """Attempt transcription with hotwords; silently fall back if not supported."""
    base_kwargs = dict(
        word_timestamps=True, vad_filter=True,
        beam_size=5, language=language,
        initial_prompt=initial_prompt or None,
    )
    if hotwords:
        try:
            return model.transcribe(audio, hotwords=hotwords, **base_kwargs)
        except TypeError:
            log.debug("faster-whisper: hotwords not supported in this version — skipping")
    return model.transcribe(audio, **base_kwargs)


def _second_decode(model, audio, *, language: Optional[str]) -> list[dict]:
    """Run a second pass at temperature=0.3 / beam_size=3 and return word list."""
    try:
        segs_iter, _ = model.transcribe(
            audio, word_timestamps=True, vad_filter=True,
            beam_size=3, temperature=0.3, language=language,
            initial_prompt=None,
        )
        alt_words: list[dict] = []
        for seg in segs_iter:
            for w in (seg.words or []):
                alt_words.append(_normalize_persian(w.word.strip()))
        return alt_words
    except Exception as exc:
        log.debug("second decode failed: %s", exc)
        return []


def _candidate_key(raw: dict) -> str:
    return raw.get("cache_key", raw["file_hash"])


def _correction_path(out_dir: Path, key: str) -> Path:
    return out_dir / "transcript_corrections" / f"{key}.json"


def _archive_current(out_dir: Path) -> None:
    current = out_dir / "transcript.json"
    if not current.exists():
        return
    previous = json.loads(current.read_text())
    key = previous.get("cache_key", f"legacy-{previous.get('file_hash', 'unknown')}")
    archive = out_dir / "transcripts" / f"{key}.json"
    archive.parent.mkdir(exist_ok=True)
    if not archive.exists():
        archive.write_text(json.dumps(previous, indent=2, ensure_ascii=False))


def effective_transcript(out_dir: Path) -> dict:
    """Return raw ASR with saved word corrections applied only to its candidate."""
    out_dir = Path(out_dir)
    raw = json.loads((out_dir / "transcript.json").read_text())
    corrections_path = _correction_path(out_dir, _candidate_key(raw))
    if not corrections_path.exists():
        return raw
    corrections = json.loads(corrections_path.read_text())
    key = _candidate_key(raw)
    if corrections.get("base_key") != key:
        return raw
    words = [dict(w) for w in raw["words"]]
    for item in corrections.get("words", []):
        idx = item["index"]
        if 0 <= idx < len(words):
            words[idx]["original_w"] = words[idx]["w"]
            words[idx]["w"] = item["text"]
            words[idx]["start"] = item.get("start", words[idx]["start"])
            words[idx]["end"] = item.get("end", words[idx]["end"])
            words[idx]["reviewed"] = True
    result = {**raw, "words": words, "correction_count": len(corrections.get("words", []))}
    result["sentences"] = [
        {**sentence, "text": " ".join(
            words[index]["w"] for index, word in enumerate(raw["words"])
            if word["start"] >= sentence["start"] - 0.001
            and word["end"] <= sentence["end"] + 0.001
        )}
        for sentence in raw["sentences"]
    ]
    return result


def save_corrections(out_dir: Path, base_key: str, items: list[dict]) -> dict:
    out_dir = Path(out_dir)
    raw = json.loads((out_dir / "transcript.json").read_text())
    if base_key != _candidate_key(raw):
        raise ValueError("transcript changed; reload before saving corrections")
    seen = set()
    cleaned = []
    for item in items:
        idx, word = item.get("index"), item.get("text")
        if (not isinstance(idx, int) or isinstance(idx, bool) or idx in seen
                or idx < 0 or idx >= len(raw["words"]) or not isinstance(word, str)
                or not word.strip() or len(word) > 120):
            raise ValueError("invalid transcript correction")
        seen.add(idx)
        original = raw["words"][idx]
        start = item.get("start") if item.get("start") is not None else original["start"]
        end = item.get("end") if item.get("end") is not None else original["end"]
        if (not isinstance(start, (int, float)) or isinstance(start, bool)
                or not isinstance(end, (int, float)) or isinstance(end, bool)
                or start < 0 or end <= start or end > raw["duration"] + 0.5):
            raise ValueError("invalid transcript word timing")
        if (word.strip() != original["w"] or abs(start-original["start"]) > 0.001
                or abs(end-original["end"]) > 0.001):
            cleaned.append({"index": idx, "text": word.strip(),
                            "start": round(start, 3), "end": round(end, 3)})
    updated_starts = [word["start"] for word in raw["words"]]
    for item in cleaned:
        updated_starts[item["index"]] = item["start"]
    if any(later < earlier for earlier, later in zip(updated_starts, updated_starts[1:])):
        raise ValueError("corrected word start times must stay in spoken order")
    path = _correction_path(out_dir, base_key)
    path.parent.mkdir(exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"base_key": base_key, "words": cleaned}, ensure_ascii=False, indent=2))
    temp.replace(path)
    return effective_transcript(out_dir)


def _transcribe_whisper(
    video: Path,
    out_dir: Path,
    fhash: str,
    model_size: str,
    language: Optional[str],
    device: str,
    compute_type: str,
    initial_prompt: str,
    hotwords: Optional[list[str]],
) -> dict:
    key = transcript_key(fhash, model_size, language, device, compute_type, initial_prompt)
    transcript_path = out_dir / "transcript.json"
    archive = out_dir / "transcripts" / f"{key}.json"

    if archive.exists():
        cached = json.loads(archive.read_text())
        _archive_current(out_dir)
        transcript_path.write_text(json.dumps(cached, indent=2, ensure_ascii=False))
        log.info("transcript cache hit for %s (%s)", video.name, key)
        return effective_transcript(out_dir)
    if transcript_path.exists():
        cached = json.loads(transcript_path.read_text())
        if cached.get("cache_key") == key:
            log.info("transcript cache hit for %s", video.name)
            return effective_transcript(out_dir)

    from faster_whisper import WhisperModel
    log.info("loading whisper model %r (device=%s, compute=%s)", model_size, device, compute_type)
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    log.info("model cache dir: %s", model.model_path if hasattr(model, "model_path") else "unknown")

    log.info("transcribing %s (whisper) …", video.name)

    import subprocess
    wav_path = out_dir / "audio_tmp.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vn", "-acodec", "pcm_s16le",
         "-ar", "16000", "-ac", "1", str(wav_path)],
        capture_output=True, check=True,
    )

    import wave
    import numpy as np
    try:
        with wave.open(str(wav_path), "rb") as wav:
            audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
            audio = audio.astype(np.float32) / 32768.0
        segments_iter, info = _try_hotwords(
            model, audio, language=language,
            initial_prompt=initial_prompt or None,
            hotwords=hotwords or [],
        )
        words: list[dict] = []
        sentences: list[dict] = []
        for seg in segments_iter:
            if not seg.words:
                continue
            segment_words = []
            for w in seg.words:
                entry = {"w": _normalize_persian(w.word.strip()), "start": round(w.start, 3),
                         "end": round(w.end, 3), "prob": round(w.probability, 3)}
                words.append(entry)
                segment_words.append(entry)
            sentences.append({"text": " ".join(w["w"] for w in segment_words),
                              "start": segment_words[0]["start"],
                              "end": segment_words[-1]["end"]})

        alt_words = _second_decode(model, audio, language=language)
        if len(alt_words) == len(words):
            for i, (w_entry, alt) in enumerate(zip(words, alt_words)):
                if alt and alt != w_entry["w"]:
                    w_entry["alt_w"] = alt
            log.info("second decode: %d word(s) differ",
                     sum(1 for w in words if "alt_w" in w))
    finally:
        wav_path.unlink(missing_ok=True)

    detected_lang = info.language if info else (language or "unknown")
    duration = info.duration if info else (words[-1]["end"] if words else 0.0)

    transcript = {
        "file_hash": fhash,
        "cache_key": key,
        "engine": "whisper",
        "model_size": model_size,
        "requested_language": language,
        "initial_prompt": initial_prompt,
        "language": detected_lang,
        "duration": round(duration, 3),
        "words": words,
        "sentences": sentences,
    }

    archive.parent.mkdir(exist_ok=True)
    _archive_current(out_dir)
    encoded = json.dumps(transcript, indent=2, ensure_ascii=False)
    archive.write_text(encoded)
    transcript_path.write_text(encoded)
    log.info("transcribed %d words, %d sentences, lang=%s", len(words), len(sentences), detected_lang)

    return effective_transcript(out_dir)


def transcribe(
    video: Path,
    out_dir: Path,
    model_size: Optional[str] = None,
    language: Optional[str] = None,
    device: str = "cpu",
    compute_type: str = "int8",
    initial_prompt: str = "",
    hotwords: Optional[list[str]] = None,
    engine: Optional[str] = None,
    keyterms: Optional[list[str]] = None,
) -> dict:
    """Transcribe *video* and write transcript.json to *out_dir*.

    Returns the transcript dict: {words, sentences, language, duration}.
    If a cached transcript exists for the same video and ASR settings, returns it.
    """
    video = Path(video).resolve()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = out_dir / "transcript.json"

    fhash = file_hash(video)
    selected_engine = choose_engine(language, engine)

    if selected_engine == "elevenlabs":
        from brain.transcribe_elevenlabs import transcribe_elevenlabs
        try:
            log.info("transcribing %s (elevenlabs scribe) …", video.name)
            transcript, asr_cost = transcribe_elevenlabs(
                video, out_dir,
                language=language,
                file_digest=fhash,
                keyterms=keyterms or hotwords,
            )
            _archive_current(out_dir)
            encoded = json.dumps(transcript, indent=2, ensure_ascii=False)
            transcript_path.write_text(encoded)

            cost_path = out_dir / "asr_cost.json"
            cost_path.write_text(json.dumps({
                "engine": "elevenlabs",
                "audio_seconds": transcript.get("duration", 0),
                "cost_usd": asr_cost,
            }, indent=2))

            return effective_transcript(out_dir)
        except Exception as exc:
            log.warning("ElevenLabs failed (%s), falling back to whisper", exc)
            selected_engine = "whisper"

    model_size = model_size or ("medium" if language == "fa" else _DEFAULT_MODEL)
    initial_prompt = initial_prompt.strip()[:500]

    result = _transcribe_whisper(
        video, out_dir, fhash, model_size, language,
        device, compute_type, initial_prompt, hotwords,
    )

    cost_path = out_dir / "asr_cost.json"
    cost_path.write_text(json.dumps({
        "engine": "whisper",
        "audio_seconds": result.get("duration", 0),
        "cost_usd": 0.0,
    }, indent=2))

    return result
