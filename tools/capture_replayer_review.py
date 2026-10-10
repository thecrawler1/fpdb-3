#!/usr/bin/env python3
"""Capture real Qt replayer states using a public fixture and no personal database."""

from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def capture_side_pots(replayer, hand, app, output: Path) -> None:
    from fpdb_3_legacy.GuiReplayer import TableState

    # Hero's unmatched 20 is returned; the remaining central pots are 240 + 40.
    state = TableState(hand)
    state.startPhase("PREFLOP")
    state.updateForAction(("Hero", "bets", Decimal(120)))
    state.updateForAction(("Player3", "calls", Decimal(80)))
    state.updateForAction(("Player1", "calls", Decimal(100)))
    before_flop = copy.deepcopy(state)
    state.startPhase("FLOP")
    assert state.computePots() == [("Main pot", Decimal(240)), ("Side pot 1", Decimal(40))]
    replayer.states = [before_flop, state]
    replayer.replay_model.states = replayer.states
    replayer.stateSlider.setMaximum(1)
    replayer.stateSlider.setValue(1)
    replayer.resize(1280, 720)
    for _ in range(3):
        app.processEvents()
    replayer.grab().save(str(output / "side-pots-1280.png"))


def capture_polish_cases(replayer, app, output: Path) -> None:
    replayer.resize(1260, 1380)
    replayer.stateSlider.setValue(0)
    replayer._clear_card_animations()
    app.processEvents()
    replayer.grab().save(str(output / "portrait-1260.png"))
    replayer.resize(1280, 720)
    fold = next(entry for entry in replayer._history_events() if entry.action == "folds")
    replayer.stateSlider.setValue(fold.state_index - 1)
    replayer.next_clicked(False)
    replayer._fold_timer.stop()
    folded = next(player.name for player in replayer.states[fold.state_index].players.values() if player.justacted)
    for name, progress in (("fold-start", 0), ("fold-mid", .5), ("fold-end", 1)):
        replayer._fold_anim = {folded: monotonic() - progress * replayer._FOLD_DURATION}
        replayer.update()
        app.processEvents()
        replayer.grab().save(str(output / f"{name}.png"))
    replayer._clear_card_animations()


def capture_bet_cases(replayer, hand, app, output: Path) -> None:
    """Public five-handed turn reproducing 12 BB facing a raise to 24 BB."""
    from fpdb_3_legacy.GuiReplayer import TableState

    review = copy.copy(hand)
    review.players = review.players[:5]
    review.gametype = dict(review.gametype)
    review.gametype["bb"] = ".01"
    review.bb = Decimal(".01")
    review.board = {"FLOP": ["6d", "2h", "Ts"], "TURN": ["8c"], "RIVER": []}
    state = TableState(review)
    state.startPhase("FLOP")
    state.startPhase("TURN")
    state.pot = state.newpot = Decimal(".17")
    state.players["Player3"].stack -= Decimal(".17")
    state.players["Hero"].holecards = ["7s", "Ks"]
    before = copy.deepcopy(state)
    state.updateForAction(("Hero", "bets", Decimal(".12")))
    state.updateForAction(("Player4", "raises", Decimal(".12")))
    replayer.replay_model.hand = review
    replayer.info = replayer._format_hand_info(review)
    replayer.states = replayer.replay_model.states = [before, state]
    replayer._configure_replay_units(review)
    replayer.stateSlider.setMaximum(1)
    replayer.stateSlider.setValue(1)
    for width, height in ((1280, 720), (1260, 1380)):
        settle_capture(replayer, app, width, height)
        replayer.grab().save(str(output / f"turn-bets-{width}.png"))


def capture_decision_cases(replayer, hand, app, output: Path) -> None:
    """Heads-up turn: 10 BB pot, 95 BB effective, facing/betting half pot."""
    from fpdb_3_legacy.GuiReplayer import TableState

    review = copy.copy(hand)
    review.players = [[p[0], p[1], str(Decimal(p[2]) / 100), *p[3:]] for p in hand.players]
    review.gametype = dict(hand.gametype, bb=".01")
    review.bb = Decimal(".01")
    review.board = {"FLOP": ["6d", "2h", "Ts"], "TURN": ["8c"], "RIVER": []}
    initial = TableState(review)
    initial.startPhase("FLOP")
    initial.startPhase("TURN")
    for name, player in initial.players.items():
        if name in {"Hero", "Player4"}:
            player.stack -= Decimal(".05")
        else:
            player.folded, player.action = True, "folds"
    initial.pot = initial.newpot = Decimal(".10")
    bet = copy.deepcopy(initial)
    bet.updateForAction(("Hero", "bets", Decimal(".05")))
    call = copy.deepcopy(initial)
    call.updateForAction(("Player4", "bets", Decimal(".05")))
    replayer.replay_model.hand = review
    replayer._configure_replay_units(review)
    for label, current in (("spr-turn", initial), ("mdf-turn", bet), ("pot-odds-turn", call)):
        replayer.states = replayer.replay_model.states = [initial, current]
        replayer.stateSlider.setMaximum(1)
        replayer.stateSlider.setValue(1)
        settle_capture(replayer, app, 1280, 720)
        replayer.grab().save(str(output / f"{label}.png"))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--big-blinds", action="store_true", help="capture BB mode without changing saved preferences")
    parser.add_argument("--side-pots", action="store_true", help="include a synthetic, conserved two-pot scenario")
    parser.add_argument("--polish-cases", action="store_true", help="include portrait and controlled fold frames")
    parser.add_argument("--bet-cases", action="store_true", help="include the five-handed turn with 12 BB facing 24 BB")
    parser.add_argument("--decision-cases", action="store_true", help="include HU turn SPR, half-pot MDF and call odds")
    parser.add_argument("--pokerstars-path", type=Path, help="read complete card faces from this local client installation")
    return parser.parse_args(argv)


def configure_capture_units(replayer, enabled: bool) -> None:
    replayer.bigBlindCheck.blockSignals(True)
    replayer.bigBlindCheck.setChecked(enabled)
    replayer.bigBlindCheck.blockSignals(False)


def configure_capture_client(config, path: Path | None) -> None:
    if path:
        config.supported_sites["PokerStars"].site_path = str(path.expanduser().resolve())


def settle_capture(replayer, app, width: int, height: int) -> None:
    replayer.audio.stop()
    replayer.show()
    app.processEvents()
    # Let queued window geometry restoration finish before setting the size.
    replayer.resize(width, height)
    deadline = monotonic() + 0.6
    while replayer._fold_timer.isActive() and monotonic() < deadline:
        app.processEvents()
        sleep(0.01)
    for _ in range(3):
        app.processEvents()


def main(argv=None) -> int:
    args = parse_args(argv)
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
        configure_capture_client(config, args.pokerstars_path)
        fixture = root / "tests/fixtures/hands/pokerstars/review/nl_3bet_6max.txt"
        hand = PokerStars(config=config, in_path=str(fixture), autostart=True).getProcessedHands()[0]
        # Only reconstruction is replaced: the widgets, model, layout and paint
        # handlers are the production implementation. No database is opened.
        with patch("fpdb_3_legacy.GuiReplayer.Hand.hand_factory", return_value=hand):
            replayer = GuiReplayer(config, None, None, [1], db=object())
            replayer.play_hand(0)
        replayer.audio.stop()
        configure_capture_units(replayer, args.big_blinds)
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
            settle_capture(replayer, app, width, height)
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
                    "units": "BB" if args.big_blinds else "original",
                }
            )
        if args.polish_cases:
            capture_polish_cases(replayer, app, output)
        if args.side_pots:
            capture_side_pots(replayer, hand, app, output)
        if args.bet_cases:
            capture_bet_cases(replayer, hand, app, output)
        if args.decision_cases:
            capture_decision_cases(replayer, hand, app, output)
        replayer.close()
        app.processEvents()
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
