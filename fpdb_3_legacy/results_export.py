"""Lossless numeric calendar-results CSV, independent of display locale."""

import csv
from collections.abc import Callable, Iterable
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from fpdb_3_legacy.period_results import PeriodResult

HEADERS = ("Period", "Start", "End", "Hands", "VPIP (%)", "PFR (%)", "Profit (USD)",
           "bb/100", "EV (USD)", "EV bb/100", "Hands with valid BB")


def results_csv(periods: Iterable[PeriodResult], total: PeriodResult,
                label: Callable[[PeriodResult], str]) -> str:
    def number(value):
        return "" if value is None else format(Decimal(str(value)), "f")

    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(HEADERS)
    for result in (*periods, total):
        writer.writerow((label(result), result.start.isoformat() if result.start else "",
                         (result.end - timedelta(days=1)).isoformat() if result.end else "",
                         len(result.hands), number(result.vpip), number(result.pfr),
                         number(result.profit / 100), number(result.bb_per_100),
                         number(result.ev / 100), number(result.ev_bb_per_100), result.bb_hands))
    return output.getvalue()
