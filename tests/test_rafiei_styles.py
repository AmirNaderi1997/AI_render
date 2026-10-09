import pytest
from fastapi import HTTPException

from brain.effect_score_v4 import score_families_with_vision, select_effects_with_vision
from engine.effects_v4 import MyEffectsPreset


def test_rafiei_style_selection_is_separate_from_favorites_and_rules(tmp_path, monkeypatch):
    import engine.effects_v4 as effects_v4
    from app.routers.effects import (RafieiStyleSelection, get_rafiei_styles,
                                     list_effects, select_rafiei_style)
    from app.routers.fonts import list_fonts

    original = effects_v4.MyEffectsPreset
    monkeypatch.setattr(effects_v4, "MyEffectsPreset",
                        lambda: original(tmp_path / "my_effects.yaml"))

    original(tmp_path / "my_effects.yaml").add_rule("keep this rule")
    result = select_rafiei_style(RafieiStyleSelection(style_id="punch__neutral"))
    assert result == {"ok": True, "selected_rafiei_style": "punch__neutral"}
    my = original(tmp_path / "my_effects.yaml")
    style = get_rafiei_styles()
    assert len(style["preferred_effects"]) == 5
    assert my.selected_rafiei_style == "punch__neutral"
    assert my.favorites == {}
    assert my.dislikes == set()
    assert my.rules == [{"text": "keep this rule", "priority": "hard"}]

    cleared = select_rafiei_style(RafieiStyleSelection(style_id=None))
    assert cleared["selected_rafiei_style"] is None
    assert original(tmp_path / "my_effects.yaml").selected_rafiei_style is None

    with pytest.raises(HTTPException) as exc:
        select_rafiei_style(RafieiStyleSelection(style_id="rgb_split"))
    assert exc.value.status_code == 422

    catalog = list_effects()
    assert len(catalog) > 100
    assert all(1 <= e["energy"] <= 5 and e["mood"] and isinstance(e["best_roles"], list)
               for e in catalog)
    assert "RAY-EXTRABOLD" in list_fonts()["fonts"]
    assert "Maneli" in list_fonts()["fonts"]


def test_selected_rafiei_style_locks_every_segment_without_ai_choice(tmp_path):
    my = MyEffectsPreset(tmp_path / "my_effects.yaml")
    my.selected_rafiei_style = "punch__neutral"
    segments = [
        {"id": "s1", "in": 0, "out": 2},
        {"id": "s2", "in": 2, "out": 4},
    ]
    analyses = [
        {"segment_id": "s1", "role": "explanation", "energy": 2},
        {"segment_id": "s2", "role": "cta", "energy": 5},
    ]
    effects = select_effects_with_vision(
        segments, analyses, None, {}, my_effects=my,
    )
    assert [effect["type"] for effect in effects] == ["punch__neutral", "punch__neutral"]
    assert all(effect["source"] == "my_effects_selection" for effect in effects)
    assert all(effect["vision"] is None for effect in effects)
    assert my.favorites == {}
