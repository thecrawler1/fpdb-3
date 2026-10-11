"""Compact rank/suit badges for data tables, independent of the replay deck."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap

from fpdb_3_legacy import Card
from fpdb_3_legacy.design_system import current_palette

CARD_WIDTH, CARD_HEIGHT, CARD_GAP = 30, 36, 5
SUITS = {"h": ("♥", "card_red"), "d": ("♦", "card_blue"), "c": ("♣", "card_green"), "s": ("♠", "card_black")}
RANKS = {rank: i for i, rank in enumerate("23456789TJQKA", 2)}


def table_card_icon(image: QPixmap) -> QIcon:
    """Keep card colours stable when Qt highlights the containing table row."""
    icon = QIcon(image)
    for mode in (QIcon.Mode.Selected, QIcon.Mode.Active):
        icon.addPixmap(image, mode)
    return icon


def card_tokens(value) -> list[str]:
    if isinstance(value, str):
        return value.replace("[", "").replace("]", "").replace("'", "").replace(",", " ").split()
    return [code if isinstance(code, str) else Card.valueSuitFromCard(int(code)) if code else "0x" for code in (value or [])]


def card_sort_key(tokens, *, hole=False) -> tuple:
    known = [token for token in card_tokens(tokens) if len(token) >= 2 and token[0] in RANKS and token[-1] in SUITS]
    if hole:
        known.sort(key=lambda token: (RANKS[token[0]], token[-1]), reverse=True)
    ranks = tuple(RANKS[token[0]] for token in known)
    suits = tuple("cdhs".index(token[-1]) for token in known)
    pair = len(ranks) == 2 and ranks[0] == ranks[1]
    return (int(pair), ranks, suits) if hole else (ranks, suits)


def render_table_cards(runs) -> QPixmap:
    colors = current_palette()
    rows = [card_tokens(run) for run in runs if run]
    if not rows:
        image = QPixmap(1, CARD_HEIGHT)
        image.fill(Qt.GlobalColor.transparent)
        return image
    width = max(len(row) for row in rows) * (CARD_WIDTH + CARD_GAP) - CARD_GAP
    image = QPixmap(width, len(rows) * (CARD_HEIGHT + 4) - 4)
    image.fill(Qt.GlobalColor.transparent)
    with QPainter(image) as painter:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for row_index, row in enumerate(rows):
            for column, token in enumerate(row):
                rect = QRectF(column * (CARD_WIDTH + CARD_GAP), row_index * (CARD_HEIGHT + 4), CARD_WIDTH, CARD_HEIGHT)
                symbol, role = SUITS.get(token[-1:] if token else "", ("", "card_black"))
                painter.setPen(QPen(QColor(colors["card_border"]), 1))
                painter.setBrush(QColor(colors["card"]))
                painter.drawRoundedRect(rect.adjusted(.5, .5, -.5, -.5), 3, 3)
                painter.setPen(QColor(colors[role]))
                font = QFont("DejaVu Sans", 10, QFont.Weight.Bold)
                font.setPixelSize(17)
                painter.setFont(font)
                rank = token[0] if token and token[0] in RANKS else "?"
                painter.drawText(rect.adjusted(0, 0, 0, -13), Qt.AlignmentFlag.AlignCenter, rank)
                font.setPixelSize(12)
                painter.setFont(font)
                painter.drawText(rect.adjusted(0, 19, 0, 0), Qt.AlignmentFlag.AlignCenter, symbol)
    return image
