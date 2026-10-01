"""Word-level transcription with settings-aware raw candidates and review overlay."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "small"


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


def transcribe(
    video: Path,
    out_dir: Path,
    model_size: Optional[str] = None,
    language: Optional[str] = None,
    device: str = "cpu",
    compute_type: str = "int8",
    initial_prompt: str = "",
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

    model_size = model_size or ("medium" if language == "fa" else _DEFAULT_MODEL)
    initial_prompt = initial_prompt.strip()[:500]
    key = transcript_key(fhash, model_size, language, device, compute_type, initial_prompt)
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

    log.info("transcribing %s …", video.name)

    # Extract audio to WAV first to avoid av package version issues
    import subprocess
    wav_path = out_dir / "audio_tmp.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vn", "-acodec", "pcm_s16le",
         "-ar", "16000", "-ac", "1", str(wav_path)],
        capture_output=True, check=True,
    )

    # Pass decoded PCM directly to faster-whisper. This avoids changing av.open
    # process-wide, which could affect another job running at the same time.
    import wave
    import numpy as np
    try:
        with wave.open(str(wav_path), "rb") as wav:
            audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
            audio = audio.astype(np.float32) / 32768.0
        segments_iter, info = model.transcribe(
            audio, word_timestamps=True, vad_filter=True,
            beam_size=5, language=language, initial_prompt=initial_prompt or None,
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
    finally:
        wav_path.unlink(missing_ok=True)

    detected_lang = info.language if info else (language or "unknown")
    duration = info.duration if info else (words[-1]["end"] if words else 0.0)

    transcript = {
        "file_hash": fhash,
        "cache_key": key,
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
