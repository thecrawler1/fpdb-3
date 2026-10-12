"""Cooperative parser batches preserve public parse results and error accounting."""

from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest

from fpdb_3_legacy.Configuration import Config
from fpdb_3_legacy.HandHistoryConverter import HandHistoryConverter
from fpdb_3_legacy.PokerStarsToFpdb import PokerStars
from tests.helpers.parser_regression import file_snapshot

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "regression-test-files/cash/Stars/Flop/NLHE-FR-USD-0.01-0.02-201004.4betPF.txt"


@pytest.fixture
def hand_text():
    return SAMPLE.read_text(encoding="utf-8").strip()


def make_parser(tmp_path, texts):
    history = tmp_path / "cooperation.txt"
    history.write_text("\n\n".join(texts) + "\n", encoding="utf-8")
    parser = PokerStars(Config(), in_path=str(history), autostart=False)
    # Exercise real filtering, not a mocked processHand exception.
    parser.import_parameters["importFilters"] = ["omahahi"]
    return parser


def counts(parser):
    return (len(parser.getProcessedHands()), parser.numPartial, parser.numErrors, parser.numSkipped)


@pytest.mark.parametrize("kind", ["valid", "partial", "malformed", "skipped"])
def test_public_parse_yields_after_every_eight_attempts(tmp_path, hand_text, kind):
    texts = {
        "valid": hand_text,
        "partial": hand_text.split("*** SUMMARY ***")[0].rstrip(),
        "malformed": hand_text.replace("Hold'em No Limit", "Unknown Game No Limit"),
        "skipped": hand_text.replace("Hold'em No Limit", "Omaha Pot Limit"),
    }
    parser = make_parser(tmp_path, [texts[kind]] * 25)
    assert parser.cooperative_callback is None
    events = []
    parser.cooperative_callback = lambda: events.append(counts(parser))
    parser.start()

    column = ["valid", "partial", "malformed", "skipped"].index(kind)
    expected = []
    for completed in (8, 16, 24):
        row = [0, 0, 0, 0]
        row[column] = completed
        expected.append(tuple(row))
    # Cleaning yields independently, before any hand has been parsed.
    assert events == [(0, 0, 0, 0)] * 3 + expected
    assert parser.numHands == 25
    final = [0, 0, 0, 0]
    final[column] = 25
    assert counts(parser) == tuple(final)


@pytest.mark.parametrize("hand_count", [0, 1, 8, 9, 16, 17, 25])
def test_callback_preserves_exact_hand_counts_and_financial_results(tmp_path, hand_text, hand_count):
    baseline = make_parser(tmp_path, [hand_text] * hand_count)
    baseline.start()
    parser = make_parser(tmp_path, [hand_text] * hand_count)
    callback = Mock(return_value=False)
    parser.cooperative_callback = callback
    parser.start()

    assert callback.call_count == 2 * max(0, (hand_count - 1) // 8)
    assert parser.numHands == hand_count
    assert counts(parser) == (hand_count, 0, 0, 0)
    assert file_snapshot(parser.getProcessedHands()) == file_snapshot(baseline.getProcessedHands())
    for hand in parser.getProcessedHands():
        assert str(hand.handid) == "42738187409"
        assert hand.totalpot == Decimal("2.89")
        assert hand.rake == Decimal("0.10")
        assert hand.collectees == {"Player4": Decimal("2.79")}


def test_cleanup_yields_even_when_batch_boundary_is_empty(tmp_path, hand_text, monkeypatch):
    parser = make_parser(tmp_path, [])
    texts = [hand_text] * 25
    texts[8] = "  "
    texts[16] = "********** archive delimiter\n" + "\n".join(" " + line for line in hand_text.splitlines())
    texts[24] = hand_text + "\n" + hand_text
    monkeypatch.setattr(HandHistoryConverter, "allHandsAsList", lambda self: texts)
    callback = Mock()
    parser.cooperative_callback = callback

    cleaned = parser.allHandsAsList()

    assert callback.call_count == 3
    assert cleaned == [hand_text] * 25


def test_disabled_debug_does_not_render_full_hand_list(tmp_path, monkeypatch):
    class UnrenderableHands(list):
        def __repr__(self):
            raise AssertionError("hand list rendered with debug logging disabled")

    parser = make_parser(tmp_path, [])
    monkeypatch.setattr(parser, "allHandsAsList", lambda: UnrenderableHands())
    logger = Mock()
    monkeypatch.setattr("fpdb_3_legacy.HandHistoryConverter.log", logger)
    parser.start()

    assert parser.numHands == 0
    logger.debug.assert_called_once_with("Hands list is: %s", [])
