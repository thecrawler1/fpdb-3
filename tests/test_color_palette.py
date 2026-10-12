"""Legibility and salience constraints, independent of Qt or screenshot rendering."""

import math

import pytest

from fpdb_3_legacy.color_science import contrast_ratio, luminance, oklab, oklch_hex, readable_mix
from fpdb_3_legacy.color_tokens import semantic_palette


def test_colour_measurements_match_reference_black_white_and_d65():
    assert luminance("#000000") == 0
    assert luminance("#ffffff") == pytest.approx(1)
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21)
    assert oklab("#ffffff") == pytest.approx((1, 0, 0), abs=1e-7)
    assert oklab("#ff0000") == pytest.approx((.627955, .224863, .125846), abs=1e-6)
    assert oklch_hex(0, 0, 0) == "#000000"
    assert oklch_hex(1, 0, 0) == "#ffffff"


@pytest.mark.parametrize("dark", [True, False])
def test_all_readable_roles_keep_contrast_in_normal_hover_and_selected_states(dark):
    p = semantic_palette(dark)
    for background in ("window", "base", "panel", "panel_alt", "selection", "selection_hover",
                       "result_positive_bg", "result_negative_bg"):
        assert contrast_ratio(p['text'], p[background]) >= 7, background
        for foreground in ("muted_text", "success", "danger", "info", "warning"):
            assert contrast_ratio(p[foreground], p[background]) >= 4.5, (foreground, background)
    for background in ("window", "base", "panel"):
        assert contrast_ratio(p['control_border'], p[background]) >= 3
        assert contrast_ratio(p['accent'], p[background]) >= 4.5
    for foreground in ("graph_up", "graph_down", "graph_showdown", "graph_ev", "graph_no_splash"):
        assert contrast_ratio(p[foreground], p['surface_panel']) >= 3
    for foreground in ("card_red", "card_blue", "card_green", "card_black"):
        assert contrast_ratio(p[foreground], p['card']) >= 7


def test_dark_surfaces_are_ordered_low_chroma_and_cards_do_not_create_white_islands():
    p = semantic_palette()
    levels = [oklab(p[role])[0] for role in ("window", "base", "panel", "panel_alt", "card")]
    assert levels == sorted(levels) and len(set(levels)) == len(levels)
    for role in ("window", "base", "panel", "panel_alt", "text", "muted_text", "card"):
        _lightness, a, b = oklab(p[role])
        assert math.hypot(a, b) < .015
    assert luminance(p['card']) < .05
    assert contrast_ratio(p['card'], p['base']) < 1.6


def test_financial_charts_use_vivid_classic_colours_and_never_gray_profit():
    p = semantic_palette()
    assert p['graph_hands'] == p['graph_up'] == "#39d98a"
    assert p['graph_showdown'] == "#45a6ff"
    assert p['graph_nonshowdown'] == "#ff647c"
    assert p['graph_ev'] == "#fbbf3a"
    assert p['graph_up'] != p['muted_text']


@pytest.mark.parametrize("dark", [True, False])
@pytest.mark.parametrize("role", ["success", "danger", "accent"])
def test_heatmaps_remain_readable_and_preserve_intensity_order(dark, role):
    p = semantic_palette(dark)
    ramp = [readable_mix(p['window'], p[role], p['text'], step / 10) for step in range(11)]
    assert len(set(ramp)) == len(ramp)  # Do not flatten distinct values into a cap.
    assert all(contrast_ratio(p['text'], colour) >= 4.5 for colour in ramp)
    levels = [oklab(colour)[0] for colour in ramp]
    assert levels == sorted(levels, reverse=not dark)
