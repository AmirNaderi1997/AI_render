"""Word-level transcription with settings-aware raw candidates and review overlay."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "base"


class WhisperTimeoutError(TimeoutError):
    """Raised when the local Whisper runtime exceeds its configured budget."""


class _whisper_timeout:
    """Interrupt a local Whisper operation on POSIX worker main threads.

    faster-whisper may block while downloading a model or while iterating its
    lazy segment iterator. SIGALRM stops both cases without leaving a hanging
    executor thread behind. Other platforms retain the call but log the
    limitation instead of pretending a timeout was enforced.
    """
    def __init__(self, seconds: int):
        self.seconds = max(1, seconds)
        self.enabled = False
        self.previous = None

    def __enter__(self):
        if hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread():
            self.previous = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM, self._expired)
            signal.setitimer(signal.ITIMER_REAL, self.seconds)
            self.enabled = True
        else:
            log.warning("Whisper timeout cannot be enforced outside the POSIX main thread")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.enabled:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self.previous)
        return False

    @staticmethod
    def _expired(signum, frame):
        raise WhisperTimeoutError("Whisper timed out")


def _whisper_timeout_seconds() -> int:
    # The first transcription on a fresh machine also downloads the model, so
    # the default must cover download + decode. 120s was too short for that
    # cold path and caused empty transcripts (and therefore AI-free plans)
    # whenever Whisper was the fallback engine.
    raw = os.environ.get("WHISPER_TIMEOUT_SECONDS", "600")
    try:
        return max(1, int(raw))
    except ValueError:
        log.warning("invalid WHISPER_TIMEOUT_SECONDS=%r; using 600 seconds", raw)
        return 600


def _sarovi_stt_enabled() -> bool:
    """Sarovi hosted-Whisper fallback is on when a key is set and not disabled."""
    flag = os.environ.get("SAROVI_STT_ENABLED", "true").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    return bool(os.environ.get("SAROVI_API_KEY", "").strip())


def choose_engine(language: Optional[str] = None, explicit: Optional[str] = None) -> str:
    if explicit and explicit in ("elevenlabs", "sarovi", "whisper"):
        return explicit
    env = os.environ.get("ASR_ENGINE", "").lower()
    if env in ("elevenlabs", "sarovi", "whisper"):
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
                   device: str, compute_type: str, initial_prompt: Optional[str] = "") -> str:
    settings = {"file_hash": file_digest, "model_size": model_size,
                "language": language, "device": device, "compute_type": compute_type,
                "initial_prompt": (initial_prompt or "").strip(),
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
    corrections_by_index = {item["index"]: item for item in corrections.get("words", [])}
    effective_words = []
    for idx, word in enumerate(words):
        item = corrections_by_index.get(idx)
        if item and item.get("delete"):
            continue
        if item:
            word["original_w"] = word["w"]
            word["w"] = item["text"]
            word["start"] = item.get("start", word["start"])
            word["end"] = item.get("end", word["end"])
            word["reviewed"] = True
        effective_words.append(word)
        if item and item.get("insert_after"):
            inserted = item["insert_after"]
            effective_words.append({
                **word,
                "w": inserted["text"],
                "original_w": "",
                "start": inserted["start"],
                "end": inserted["end"],
                "reviewed": True,
                "inserted": True,
            })
    words = effective_words
    result = {**raw, "words": words, "correction_count": len(corrections.get("words", []))}
    result["sentences"] = [
        {**sentence, "text": " ".join(
            word["w"] for word in words
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
        deleting = item.get("delete") is True
        if (not isinstance(idx, int) or isinstance(idx, bool) or idx in seen
                or idx < 0 or idx >= len(raw["words"])
                or (not deleting and (not isinstance(word, str) or not word.strip() or len(word) > 120))):
            raise ValueError("invalid transcript correction")
        seen.add(idx)
        original = raw["words"][idx]
        if deleting:
            cleaned.append({"index": idx, "delete": True})
            continue
        start = item.get("start") if item.get("start") is not None else original["start"]
        end = item.get("end") if item.get("end") is not None else original["end"]
        if (not isinstance(start, (int, float)) or isinstance(start, bool)
                or not isinstance(end, (int, float)) or isinstance(end, bool)
                or start < 0 or end <= start or end > raw["duration"] + 0.5):
            raise ValueError("invalid transcript word timing")
        insert_after = item.get("insert_after")
        if insert_after is not None:
            inserted_text = insert_after.get("text") if isinstance(insert_after, dict) else None
            inserted_start = insert_after.get("start") if isinstance(insert_after, dict) else None
            inserted_end = insert_after.get("end") if isinstance(insert_after, dict) else None
            if (not isinstance(inserted_text, str) or not inserted_text.strip() or len(inserted_text) > 120
                    or not isinstance(inserted_start, (int, float)) or isinstance(inserted_start, bool)
                    or not isinstance(inserted_end, (int, float)) or isinstance(inserted_end, bool)
                    or inserted_start < 0 or inserted_end <= inserted_start
                    or inserted_end > raw["duration"] + 0.5):
                raise ValueError("invalid inserted transcript word")
            insert_after = {"text": inserted_text.strip(), "start": round(inserted_start, 3),
                            "end": round(inserted_end, 3)}
        if (word.strip() != original["w"] or abs(start-original["start"]) > 0.001
                or abs(end-original["end"]) > 0.001):
            cleaned.append({"index": idx, "text": word.strip(),
                            "start": round(start, 3), "end": round(end, 3),
                            **({"insert_after": insert_after} if insert_after else {})})
        elif insert_after:
            cleaned.append({"index": idx, "text": word.strip(),
                            "start": round(start, 3), "end": round(end, 3),
                            "insert_after": insert_after})
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

    def empty_transcript(reason: str) -> dict:
        from engine.probe import probe_duration

        transcript = {
            "file_hash": fhash,
            "cache_key": key,
            "engine": "none",
            "model_size": model_size,
            "requested_language": language,
            "initial_prompt": initial_prompt,
            "language": language or "unknown",
            "duration": round(probe_duration(video), 3),
            "words": [],
            "sentences": [],
            "fallback_reason": reason,
        }
        archive.parent.mkdir(exist_ok=True)
        _archive_current(out_dir)
        encoded = json.dumps(transcript, indent=2, ensure_ascii=False)
        archive.write_text(encoded)
        transcript_path.write_text(encoded)
        log.warning("using an empty transcript for %s: %s", video.name, reason)
        return transcript

    from engine.probe import has_audio
    if not has_audio(video):
        return empty_transcript("source has no audio stream")

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        # Preserve an audio-only artifact for diagnostics even when the
        # optional ASR runtime was not installed in this environment.
        import subprocess
        fallback_wav = out_dir / "audio_tmp.wav"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(video), "-vn", "-acodec", "pcm_s16le",
                 "-ar", "16000", "-ac", "1", str(fallback_wav)],
                capture_output=True, check=True, timeout=30,
            )
            log.info("FFmpeg audio extraction completed while Whisper was unavailable for %s", video.name)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("FFmpeg audio extraction also failed while Whisper was unavailable for %s (%s)", video.name, type(exc).__name__)
        finally:
            fallback_wav.unlink(missing_ok=True)
        return empty_transcript(
            f"faster-whisper is not installed in the API Python environment ({sys.executable})"
        )

    # Always prove that the source audio can be extracted before depending on
    # an optional model runtime. This produces a useful, non-blocking fallback
    # for environments where model downloads are blocked.
    import subprocess
    wav_path = out_dir / "audio_tmp.wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video), "-vn", "-acodec", "pcm_s16le",
             "-ar", "16000", "-ac", "1", str(wav_path)],
            capture_output=True, check=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        wav_path.unlink(missing_ok=True)
        return empty_transcript(f"FFmpeg audio extraction failed ({type(exc).__name__})")

    timeout_seconds = _whisper_timeout_seconds()
    try:
        log.info("loading whisper model %r (device=%s, compute=%s, timeout=%ss)", model_size, device, compute_type, timeout_seconds)
        with _whisper_timeout(timeout_seconds):
            model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as exc:
        wav_path.unlink(missing_ok=True)
        return empty_transcript(f"Whisper model unavailable ({type(exc).__name__}: {exc})")
    log.info("model cache dir: %s", model.model_path if hasattr(model, "model_path") else "unknown")

    log.info("transcribing %s (whisper, timeout=%ss) …", video.name, timeout_seconds)

    import wave
    import numpy as np
    try:
        with wave.open(str(wav_path), "rb") as wav:
            audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
            audio = audio.astype(np.float32) / 32768.0
        with _whisper_timeout(timeout_seconds):
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
    except Exception as exc:
        return empty_transcript(f"Whisper transcription skipped ({type(exc).__name__}: {exc})")
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
    initial_prompt: Optional[str] = "",
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
    elevenlabs_error: Optional[Exception] = None

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
            log.warning("ElevenLabs failed (%s), trying Sarovi hosted whisper", exc)
            elevenlabs_error = exc
            selected_engine = "sarovi"

    # Sarovi hosted Whisper sits between ElevenLabs and the local engine: it is
    # reached when explicitly selected, or as the first fallback after
    # ElevenLabs fails (commonly an exhausted credit balance). It needs no local
    # model download, so it is faster and steadier than cold local Whisper.
    sarovi_error: Optional[Exception] = None
    if (selected_engine == "sarovi" or elevenlabs_error is not None) and _sarovi_stt_enabled():
        from brain.transcribe_sarovi import transcribe_sarovi
        try:
            log.info("transcribing %s (sarovi hosted whisper) …", video.name)
            transcript, asr_cost = transcribe_sarovi(
                video, out_dir,
                language=language,
                file_digest=fhash,
                keyterms=keyterms or hotwords,
            )
            if elevenlabs_error is not None:
                transcript = {
                    **transcript,
                    "fallback_from": "elevenlabs",
                    "fallback_reason": f"ElevenLabs unavailable: {elevenlabs_error}"[:500],
                }
            _archive_current(out_dir)
            transcript_path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))

            cost_path = out_dir / "asr_cost.json"
            cost_path.write_text(json.dumps({
                "engine": "sarovi",
                "audio_seconds": transcript.get("duration", 0),
                "cost_usd": asr_cost,
            }, indent=2))

            return effective_transcript(out_dir)
        except Exception as exc:
            log.warning("Sarovi transcription failed (%s), falling back to local whisper", exc)
            sarovi_error = exc
    selected_engine = "whisper"

    if os.environ.get("WHISPER_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        model_size = model_size or os.environ.get("WHISPER_MODEL_SIZE") or os.environ.get("WHISPER_MODEL") or _DEFAULT_MODEL
        # Reuse the safe local fallback writer so disabled ASR leaves the same
        # transcript contract as a missing runtime.
        from engine.probe import has_audio, probe_duration
        transcript = {
            "file_hash": fhash, "cache_key": transcript_key(fhash, model_size, language, device, compute_type, initial_prompt),
            "engine": "none", "model_size": model_size, "requested_language": language,
            "initial_prompt": (initial_prompt or "").strip()[:500], "language": language or "unknown",
            "duration": round(probe_duration(video), 3) if has_audio(video) else 0.0,
            "words": [], "sentences": [], "fallback_reason": "Whisper skipped because WHISPER_ENABLED=false",
        }
        transcript_path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))
        log.warning("Whisper skipped for %s because WHISPER_ENABLED=false", video.name)
        result = transcript
    else:
        model_size = model_size or os.environ.get("WHISPER_MODEL_SIZE") or os.environ.get("WHISPER_MODEL") or _DEFAULT_MODEL
        initial_prompt = (initial_prompt or "").strip()[:500]

        try:
            result = _transcribe_whisper(
                video, out_dir, fhash, model_size, language,
                device, compute_type, initial_prompt, hotwords,
            )
        except Exception as whisper_error:
            if elevenlabs_error is not None or sarovi_error is not None:
                chain = []
                if elevenlabs_error is not None:
                    chain.append(f"ElevenLabs failed ({type(elevenlabs_error).__name__}: {elevenlabs_error})")
                if sarovi_error is not None:
                    chain.append(f"Sarovi failed ({type(sarovi_error).__name__}: {sarovi_error})")
                chain.append(f"Whisper fallback also failed ({type(whisper_error).__name__}: {whisper_error})")
                raise RuntimeError("; ".join(chain)) from whisper_error
            raise

    if elevenlabs_error is not None or sarovi_error is not None:
        # Preserve the actual engine and the reason the preferred providers were
        # not used. This prevents a successful Whisper fallback from being
        # presented as an ElevenLabs/Sarovi result.
        whisper_reason = str(result.get("fallback_reason") or "").strip()
        reasons = []
        if elevenlabs_error is not None:
            reasons.append(f"ElevenLabs unavailable: {elevenlabs_error}")
        if sarovi_error is not None:
            reasons.append(f"Sarovi unavailable: {sarovi_error}")
        if whisper_reason:
            reasons.append(f"Whisper fallback: {whisper_reason}")
        result = {
            **result,
            "fallback_from": "elevenlabs" if elevenlabs_error is not None else "sarovi",
            "fallback_reason": "; ".join(reasons)[:500],
        }
        transcript_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    cost_path = out_dir / "asr_cost.json"
    cost_path.write_text(json.dumps({
        "engine": result.get("engine", "whisper"),
        "audio_seconds": result.get("duration", 0),
        "cost_usd": 0.0,
    }, indent=2))

    return result
