"""Complete replay faces from the local client, with a bundled SVG fallback."""

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


class ReplayCardFaces:
    """Cache high-resolution faces without distributing client-owned assets."""

    def __init__(self, config):
        site = getattr(config, "supported_sites", {}).get("PokerStars")
        site_path = getattr(site, "site_path", "")
        self.local = Path(site_path) / "Gx/table-view/cards/default/1440/cache" if site_path else None
        self.fallback = Path(config.graphics_path) / "cards/white"
        self.faces: dict[str, QPixmap] = {}

    def face(self, card: str) -> QPixmap:
        if card not in self.faces:
            image = QPixmap(str(self.local / f"{card}.png")) if self.local else QPixmap()
            if image.isNull():
                rank = "10" if card[0] == "T" else card[0].lower()
                renderer = QSvgRenderer(str(self.fallback / f"{card[-1]}_{rank}.svg"))
                image = QPixmap(280, 360)
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                renderer.render(painter, QRectF(image.rect()))
                painter.end()
            self.faces[card] = image
        return self.faces[card]
