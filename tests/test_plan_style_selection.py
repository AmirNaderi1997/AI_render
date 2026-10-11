from app import plan_style_store


def test_explicit_defaults_can_be_deselected(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_style_store, "DB_AVAILABLE", False)
    monkeypatch.setattr(plan_style_store, "_SELECTIONS", tmp_path)

    assert plan_style_store.get_selection(42) == {"style_id": None, "version": None, "selected": False}
    assert plan_style_store.set_selection(42, None, None)["selected"] is True
    assert plan_style_store.get_selection(42)["selected"] is True
    assert plan_style_store.clear_selection(42)["selected"] is False
    assert plan_style_store.get_selection(42)["selected"] is False
