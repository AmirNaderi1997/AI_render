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
