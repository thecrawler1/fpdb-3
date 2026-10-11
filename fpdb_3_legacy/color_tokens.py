"""Semantic colours: restrained surfaces, readable data, no white islands in dark UI."""

from functools import lru_cache

from fpdb_3_legacy.color_science import oklch_hex

ACCENT = oklch_hex(.78, .09, 160)


@lru_cache(maxsize=2)
def _palette(dark: bool) -> dict[str, str]:
    def neutral(lightness):
        return oklch_hex(lightness, .012, 250)
    if dark:
        window, base, panel, hover = (neutral(level) for level in (.205, .235, .275, .315))
        text, muted, disabled = (neutral(level) for level in (.87, .73, .56))
        border, control_border = neutral(.38), neutral(.56)
        selection, selection_hover = oklch_hex(.33, .026, 160), oklch_hex(.36, .026, 160)
        accent, accent_hover = ACCENT, oklch_hex(.83, .09, 160)
        success, danger, info, warning = (oklch_hex(.80, .09, 160), oklch_hex(.80, .10, 20),
                                          oklch_hex(.80, .09, 245), oklch_hex(.82, .09, 80))
        card, card_border = neutral(.35), neutral(.48)
        card_red, card_blue, card_green, card_black = (oklch_hex(.86, .065, 20), oklch_hex(.86, .065, 245),
                                                      oklch_hex(.86, .065, 160), neutral(.88))
    else:
        window, base, panel, hover = (neutral(level) for level in (.95, .975, .925, .895))
        text, muted, disabled = (neutral(level) for level in (.29, .46, .60))
        border, control_border = neutral(.78), neutral(.60)
        selection, selection_hover = oklch_hex(.88, .025, 160), oklch_hex(.85, .025, 160)
        accent, accent_hover = oklch_hex(.45, .075, 160), oklch_hex(.40, .075, 160)
        success, danger, info, warning = (oklch_hex(.45, .075, 160), oklch_hex(.45, .11, 20),
                                          oklch_hex(.45, .09, 245), oklch_hex(.45, .07, 80))
        card, card_border = neutral(.91), neutral(.70)
        card_red, card_blue, card_green, card_black = (oklch_hex(.38, .085, 20), oklch_hex(.38, .075, 245),
                                                      oklch_hex(.38, .065, 160), text)
    return dict(window=window, base=base, sidebar=window, sidebar_panel=panel, surface=base,
                surface_panel=base, app_header=window, panel=panel, panel_alt=hover,
                input=panel, input_hover=hover, button=panel, button_hover=hover,
                text=text, window_text=text, muted_text=muted, disabled_text=disabled,
                border=border, control_border=control_border, grid=border,
                accent=accent, accent_soft=selection, accent_hover=accent_hover,
                selection=selection, selection_hover=selection_hover, selection_soft=selection,
                highlighted_text=text, table_header=panel, table_header_hover=hover, table_header_text=muted,
                tooltip=panel, tooltip_border=control_border, on_accent=window if dark else base,
                success=success, danger=danger, info=info, warning=warning,
                graph_up=success, graph_down=danger, graph_showdown=info, graph_nonshowdown=danger,
                graph_ev=warning, graph_no_splash=oklch_hex(.80 if dark else .45, .08, 300),
                graph_hands=muted, graph_purple=info,
                card=card, card_border=card_border, card_red=card_red, card_blue=card_blue,
                card_green=card_green, card_black=card_black,
                result_positive_bg=oklch_hex(.25 if dark else .94, .016, 160),
                result_negative_bg=oklch_hex(.25 if dark else .94, .016, 20))


def semantic_palette(dark: bool = True) -> dict[str, str]:
    return _palette(dark).copy()
