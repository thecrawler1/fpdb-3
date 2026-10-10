"""Local presentation tokens for the Qt hand replayer."""

from PySide6.QtGui import QFont

FONT_SCALE = 1.5


def replay_font(family: str, size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(family)
    font.setPointSizeF(size * FONT_SCALE)
    font.setWeight(weight)
    return font

REPLAYER_STYLE = """
QWidget { background: #101216; color: #eef1f5; font-family: 'DejaVu Sans'; font-size: 18px; font-style: normal; }
QPushButton { background: #22262e; border: 1px solid #303640; border-radius: 6px;
    padding: 0px 12px; padding-top: 0px; padding-bottom: 0px; min-height: 40px; max-height: 40px; font-weight: 600; }
QPushButton:hover { background: #303640; }
QPushButton:pressed { background: #3b434e; }
QPushButton:focus { border-color: #78d9a0; }
QPushButton:disabled { color: #707986; background: #181b21; border-color: #252a32; }
QPushButton[transport="true"] { min-height: 0px; max-height: 80px; padding: 0px; border-radius: 10px; background: #29313b; }
QPushButton[transport="true"]:hover { background: #3e4956; border-color: #8793a1; }
QPushButton[transport="true"]:pressed { background: #192029; border-color: #c5cdd6; }
QPushButton[primary="true"] { background: #a94752; border-color: #ba5964; }
QPushButton[primary="true"]:hover { background: #bb5560; border-color: #dd8991; }
QPushButton[primary="true"]:pressed { background: #823741; border-color: #efafb5; }
QPushButton[transport="true"]:disabled { background: #181e25; border-color: #252a32; }
QPushButton[primary="true"]:disabled { background: #181e25; border-color: #252a32; }
QPushButton[streetActive="true"] { background: #30313b; color: #eef1f5; border-color: #96616a; }
QCheckBox { spacing: 7px; color: #a6afbc; }
QCheckBox::indicator { width: 21px; height: 21px; border: 1px solid #596372; border-radius: 3px; background: #22262e; }
QCheckBox::indicator:unchecked, QCheckBox::indicator:unchecked:enabled { border-color: #596372; background: #22262e; image: none; }
QCheckBox::indicator:checked, QCheckBox::indicator:checked:enabled { background: #78d9a0; border-color: #78d9a0; image: none; }
QComboBox { background: #22262e; border: 1px solid #303640; border-radius: 5px; padding: 0px 8px; min-height: 40px; max-height: 40px; }
QComboBox QAbstractItemView { background: #22262e; color: #eef1f5; selection-background-color: #435e50; }
QSlider:horizontal { min-height: 16px; max-height: 16px; }
QSlider::groove:horizontal { height: 4px; background: #303640; border-radius: 2px; }
QSlider::handle:horizontal, QSlider::handle:horizontal:enabled { image: none; background: #98e5b7; background-color: #98e5b7; border: none; width: 12px; margin: -4px 0; border-radius: 6px; }
QSlider::sub-page:horizontal { background: #78d9a0; border-radius: 2px; }
QListWidget { background: #181b21; border: 1px solid #303640; border-radius: 6px; }
QListWidget::item { padding: 8px; min-height: 24px; max-height: 24px; border-bottom: 1px solid #252a32; }
QListWidget::item:selected { background: #293b32; color: #eef1f5; }
QListWidget::item:hover { background: #252c32; }
QListWidget::item:selected:hover { background: #293b32; }
"""
