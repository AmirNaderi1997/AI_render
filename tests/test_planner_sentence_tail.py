"""A source-truncated thought must not become the final line of a reel."""

from copy import deepcopy

from brain.planner import _clamp_output_events, _trim_incomplete_source_tail


def _sample():
    transcript = {
        "duration": 10.0,
        "sentences": [
            {"start": 0.0, "end": 5.0, "text": "A complete sentence."},
            {"start": 5.1, "end": 9.98, "text": "Because the next"},
        ],
        "words": [{"start": 9.4, "end": 9.98, "w": "next"}],
    }
    plan = {
        "canvas": {"fps": 30},
        "segments": [
            {"id": "s1", "in": 0.0, "out": 4.0},
            {"id": "s2", "in": 4.0, "out": 7.0},
            {"id": "s3", "in": 7.0, "out": 10.0},
        ],
        "visual_effects": [{"segment_id": id_, "type": "steady__neutral"} for id_ in ("s1", "s2", "s3")],
        "captions": [{"start": 4.0, "end": 7.0, "text": "tail", "style": "normal"}],
        "broll": [{"at": 6.0, "duration": 1.0, "file": "b.mp4"}],
        "sfx": [{"at": 6.0, "file": "s.wav"}],
    }
    return transcript, plan


def test_source_truncated_thought_ends_at_prior_complete_sentence():
    transcript, plan = _sample()
    assert _trim_incomplete_source_tail(plan, transcript)
    _clamp_output_events(plan)
    assert [(s["id"], s["out"]) for s in plan["segments"]] == [("s1", 4.0), ("s2", 5.0)]
    assert [effect["segment_id"] for effect in plan["visual_effects"]] == ["s1", "s2"]
    assert plan["captions"][0]["end"] == 5.0
    assert plan["broll"] == []
    assert plan["sfx"] == []


def test_complete_or_deliberately_shorter_edits_are_preserved():
    transcript, plan = _sample()
    complete = deepcopy(transcript)
    complete["sentences"][-1]["text"] += "."
    assert not _trim_incomplete_source_tail(plan, complete)
    assert plan["segments"][-1]["out"] == 10.0

    shorter = deepcopy(plan)
    shorter["segments"] = shorter["segments"][:2]
    shorter["segments"][-1]["out"] = 5.0
    assert not _trim_incomplete_source_tail(shorter, transcript)

    with_outro = deepcopy(transcript)
    with_outro["duration"] = 12.0
    assert not _trim_incomplete_source_tail(plan, with_outro)
