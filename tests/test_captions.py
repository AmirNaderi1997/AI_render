"""Caption helper tests — colour conversion, SRT emission, ASS timing."""
from __future__ import annotations

import pytest

from engine import captions as C


class TestAssColour:
    def test_pure_white_opaque(self):
        # #FFFFFF -> alpha 00 (opaque), BGR = FFFFFF
        assert C.ass_colour("#FFFFFF") == "&H00FFFFFF"

    def test_pure_red_opaque(self):
        # #FF0000 -> BGR order flips: 0000FF, alpha 00
        assert C.ass_colour("#FF0000") == "&H000000FF"

    def test_pure_blue_opaque(self):
        # #0000FF -> BGR: FF0000
        assert C.ass_colour("#0000FF") == "&H00FF0000"

    def test_hex_case_normalised(self):
        assert C.ass_colour("#ffd700") == "&H0000D7FF"

    def test_alpha_channel_preserved(self):
        # #RRGGBBAA -> &HAABBGGRR — alpha component sits first
        assert C.ass_colour("#FF008040") == "&H408000FF"
        assert C.ass_colour("#000000FF") == "&HFF000000"

    def test_no_hash_prefix_ok(self):
        assert C.ass_colour("00FF66") == "&H0066FF00"

    def test_invalid_length_raises(self):
        with pytest.raises(ValueError):
            C.ass_colour("#FFF")


class TestMltColour:
    def test_opaque_default(self):
        assert C.mlt_colour("#FFFFFF") == "0xffffffff"

    def test_alpha_from_input(self):
        assert C.mlt_colour("#FFD70080") == "0xffd70080"


class TestSrt:
    def test_srt_time_zero(self):
        assert C.srt_time(0.0) == "00:00:00,000"

    def test_srt_time_seconds_and_millis(self):
        assert C.srt_time(1.5) == "00:00:01,500"

    def test_srt_time_hours(self):
        assert C.srt_time(3661.123) == "01:01:01,123"


class TestAssTime:
    def test_ass_time_centiseconds(self):
        assert C.ass_time(0.0) == "0:00:00.00"
        assert C.ass_time(1.5) == "0:00:01.50"
        assert C.ass_time(3600 + 2 * 60 + 3.45) == "1:02:03.45"


class TestAssText:
    def test_newline_escaped(self):
        assert C.ass_text("hello\nworld") == "hello\\Nworld"

    def test_braces_escaped(self):
        assert C.ass_text("{tag}") == "\\{tag\\}"


class TestSrtNoFrameOverlap:
    """Back-to-back cues, even across different SRT feeds, must not share a
    frame. `build_srts` shortens each end by 1 frame (1/fps) to guarantee it."""

    def _plan(self, fps=30):
        from engine.schema import EditPlan, Canvas, Segment, Caption, Export
        return EditPlan(
            canvas=Canvas(width=1080, height=1920, fps=fps),
            source="s.mp4",
            segments=[Segment(id="s1", **{"in": 0.0}, out=10.0)],
            captions=[
                Caption(start=0.0, end=3.5, text="one", style="emphasis"),
                Caption(start=3.5, end=7.0, text="two", style="normal"),
                Caption(start=7.0, end=10.0, text="three", style="cta"),
            ],
            export=Export(file="out.mp4"),
        )

    def test_end_is_shortened_by_one_frame(self):
        srts = C.build_srts(self._plan(fps=30))
        # 3.5 - 1/30 = 3.46666… -> 3467 ms (nearest ms)
        assert "00:00:03,467" in srts["emphasis"]
        # 7.0 - 1/30 = 6.96666… -> 6967 ms
        assert "00:00:06,967" in srts["normal"]

    def test_no_two_cues_share_a_frame(self):
        srts = C.build_srts(self._plan(fps=30))
        # Parse every timestamp and confirm no cue's end frame equals the
        # next cue's start frame (across all feeds combined).
        import re
        starts, ends = [], []
        for body in srts.values():
            for line in body.splitlines():
                m = re.match(r"(\d\d):(\d\d):(\d\d),(\d{3}) --> (\d\d):(\d\d):(\d\d),(\d{3})", line)
                if not m:
                    continue
                g = list(map(int, m.groups()))
                starts.append(g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000)
                ends.append(g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000)
        events = sorted(zip(starts, ends), key=lambda x: x[0])
        for (_, e1), (s2, _) in zip(events, events[1:]):
            assert int(round(e1 * 30)) < int(round(s2 * 30)), (
                f"cue ending at {e1}s overlaps frame with next starting at {s2}s"
            )

    def test_end_never_precedes_start(self):
        # Zero-duration or sub-frame cue must still emit end > start.
        from engine.schema import EditPlan, Canvas, Segment, Caption, Export
        plan = EditPlan(
            canvas=Canvas(width=1080, height=1920, fps=30),
            source="s.mp4",
            segments=[Segment(id="s1", **{"in": 0.0}, out=1.0)],
            captions=[Caption(start=0.0, end=0.02, text="x", style="normal")],
            export=Export(file="out.mp4"),
        )
        body = C.build_srts(plan)["normal"]
        # 0.02 - 1/30 is negative; guarded to start + 1ms = 1 ms
        assert "00:00:00,000 --> 00:00:00,001" in body
