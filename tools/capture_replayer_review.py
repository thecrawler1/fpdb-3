#!/usr/bin/env python3
"""Capture real Qt replayer states using a public fixture and no personal database."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    output = args.out.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    from PySide6.QtWidgets import QApplication

    from fpdb_3_legacy import Configuration
    from fpdb_3_legacy.GuiReplayer import GuiReplayer
    from fpdb_3_legacy.PokerStarsToFpdb import PokerStars
    from fpdb_3_legacy.ThemeManager import ThemeManager

    app = QApplication.instance() or QApplication([])
    ThemeManager().set_qt_material_theme("dark_purple.xml", save=False, apply_to_ui=True)
    with tempfile.TemporaryDirectory(prefix="fpdb-replayer-review-") as temporary:
        config = Configuration.Config(file=str(root / "HUD_config.xml.example"), custom_log_dir=temporary)
        fixture = root / "tests/fixtures/hands/pokerstars/review/nl_3bet_6max.txt"
        hand = PokerStars(config=config, in_path=str(fixture), autostart=True).getProcessedHands()[0]
        # Only reconstruction is replaced: the widgets, model, layout and paint
        # handlers are the production implementation. No database is opened.
        with patch("fpdb_3_legacy.GuiReplayer.Hand.hand_factory", return_value=hand):
            replayer = GuiReplayer(config, None, None, [1], db=object())
            replayer.play_hand(0)
        replayer.audio.stop()
        manifest = []
        scenarios = (
            ("preflop-1280.png", 1280, 720, "PREFLOP"),
            ("actor-1280.png", 1280, 720, "ACTOR"),
            ("flop-1600.png", 1600, 900, "FLOP"),
            ("result-1280.png", 1280, 720, "RESULT"),
        )
        for filename, width, height, street in scenarios:
            replayer.resize(width, height)
            if street == "RESULT":
                index = len(replayer.states) - 1
            elif street == "ACTOR":
                index = next(
                    i
                    for i, state in enumerate(replayer.states)
                    if state.street == "PREFLOP"
                    and any(
                        player.name == hand.hero and player.justacted and player.action == "raises"
                        for player in state.players.values()
                    )
                )
            else:
                index = next(i for i, state in enumerate(replayer.states) if state.street == street)
            replayer.stateSlider.setValue(index)
            replayer.audio.stop()
            replayer.show()
            # Capture settled frames, not transient folding/discard animation.
            deadline = monotonic() + 0.6
            while replayer._fold_timer.isActive() and monotonic() < deadline:
                app.processEvents()
                sleep(0.01)
            for _ in range(3):
                app.processEvents()
            pixmap = replayer.grab()
            if not pixmap.save(str(output / filename)):
                raise RuntimeError(f"Could not save {filename}")
            manifest.append(
                {
                    "image": filename,
                    "requested": [width, height],
                    "actual": [replayer.width(), replayer.height()],
                    "pixels": [pixmap.width(), pixmap.height()],
                    "state": index,
                    "street": street,
                }
            )
        replayer.close()
        app.processEvents()
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
