"""Calendar results and four profit curves over the same cash hand population."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from decimal import Decimal
from typing import Any

from fpdb_3_legacy.cooperative_work import checkpoint

ZERO = Decimal(0)
HUNDRED = Decimal(100)


@dataclass(frozen=True)
class ResultHand:
    hand_id: int
    timestamp: datetime
    profit: Decimal  # database minor units, not displayed dollars
    ev: Decimal
    big_blind: Decimal
    vpip: int
    vpip_chance: int
    pfr: int
    pfr_chance: int
    showdown: bool
    game: str
    limit_type: str

    @property
    def stake_key(self) -> str:
        return f"{self.limit_type}:{self.big_blind.normalize()}"


@dataclass(frozen=True)
class PeriodResult:
    start: date | None
    end: date | None  # exclusive
    hands: tuple[ResultHand, ...]
    profit: Decimal
    ev: Decimal
    vpip: Decimal | None
    pfr: Decimal | None
    bb_per_100: Decimal | None
    ev_bb_per_100: Decimal | None
    bb_hands: int


def parse_result_rows(rows: Iterable[tuple[Any, ...]], *, cooperative: bool = False) -> tuple[ResultHand, ...]:
    parsed = []
    for index, row in enumerate(rows):
        if cooperative and index % 2048 == 0:
            checkpoint()
        timestamp = row[1] if isinstance(row[1], datetime) else datetime.fromisoformat(str(row[1]))
        timestamp = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp
        profit = Decimal(str(row[2] or 0))
        parsed.append(ResultHand(
            int(row[0]), timestamp.astimezone(timezone.utc), profit,
            Decimal(str(row[3])) if row[3] is not None else profit,
            Decimal(str(row[4] or 0)), int(row[5] or 0), int(row[6] or 0), int(row[7] or 0), int(row[8] or 0),
            bool(row[9]), str(row[10]), str(row[11]),
        ))
    return tuple(sorted(parsed, key=lambda hand: (hand.timestamp, hand.hand_id)))


def period_start(day: date, grouping: str) -> date:
    if grouping == "day":
        return day
    if grouping == "week":
        return day - timedelta(days=day.weekday())
    if grouping == "month":
        return day.replace(day=1)
    if grouping == "year":
        return day.replace(month=1, day=1)
    raise ValueError(f"Unknown calendar grouping: {grouping}")


def period_end(start: date, grouping: str) -> date:
    if grouping == "day":
        return start + timedelta(days=1)
    if grouping == "week":
        return start + timedelta(days=7)
    if grouping == "month":
        return date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    if grouping == "year":
        return date(start.year + 1, 1, 1)
    raise ValueError(f"Unknown calendar grouping: {grouping}")


def summarize_results(hands: Iterable[ResultHand], start: date | None = None, end: date | None = None,
                      *, cooperative: bool = False) -> PeriodResult:
    ordered = tuple(sorted(hands, key=lambda hand: (hand.timestamp, hand.hand_id)))
    profit = ev = bb_profit = bb_ev = ZERO
    vpip = pfr = vpip_chances = pfr_chances = bb_hands = 0
    for index, hand in enumerate(ordered):
        if cooperative and index % 2048 == 0:
            checkpoint()
        profit += hand.profit
        ev += hand.ev
        vpip += hand.vpip
        pfr += hand.pfr
        vpip_chances += hand.vpip_chance
        pfr_chances += hand.pfr_chance
        if hand.big_blind > 0:
            bb_hands += 1
            bb_profit += hand.profit / hand.big_blind
            bb_ev += hand.ev / hand.big_blind
    return PeriodResult(
        start, end, ordered, profit, ev,
        HUNDRED * vpip / vpip_chances if vpip_chances else None,
        HUNDRED * pfr / pfr_chances if pfr_chances else None,
        HUNDRED * bb_profit / bb_hands if bb_hands else None,
        HUNDRED * bb_ev / bb_hands if bb_hands else None,
        bb_hands,
    )


def group_results(hands: Iterable[ResultHand], grouping: str, zone: tzinfo, *, cooperative: bool = False) -> list[PeriodResult]:
    groups: dict[date, list[ResultHand]] = defaultdict(list)
    for index, hand in enumerate(hands):
        if cooperative and index % 2048 == 0:
            checkpoint()
        groups[period_start(hand.timestamp.astimezone(zone).date(), grouping)].append(hand)
    return [summarize_results(groups[start], start, period_end(start, grouping), cooperative=cooperative)
            for start in sorted(groups, reverse=True)]


def profit_curves(hands: Iterable[ResultHand], *, in_bb: bool = False, cooperative: bool = False) -> tuple[list[float], ...]:
    """All curves start at zero, ordered by time/id; SD + NSD always equals net."""
    ordered = sorted(hands, key=lambda hand: (hand.timestamp, hand.hand_id))
    if in_bb and any(hand.big_blind <= 0 for hand in ordered):
        raise ValueError("BB graph requires a usable big blind for every hand")
    values = [ZERO, ZERO, ZERO, ZERO]
    curves = [[0.0] for _ in values]
    for index, hand in enumerate(ordered):
        if cooperative and index % 2048 == 0:
            checkpoint()
        unit = hand.big_blind if in_bb else HUNDRED
        net, ev = hand.profit / unit, hand.ev / unit
        increments = (net, net if hand.showdown else ZERO, ZERO if hand.showdown else net, ev)
        for i, increment in enumerate(increments):
            values[i] += increment
            curves[i].append(float(values[i]))
    return tuple(curves)


def preset_dates(today: date, preset: str) -> tuple[date | None, date | None]:
    """Return inclusive UI dates; SQL uses the next local midnight exclusively."""
    if preset == "today":
        return today, today
    if preset == "yesterday":
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    if preset == "seven":
        return today - timedelta(days=6), today
    if preset == "month":
        start = today.replace(day=1)
        return start, period_end(start, "month") - timedelta(days=1)
    if preset == "year":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    if preset == "all":
        return None, None
    raise ValueError(f"Unknown interval preset: {preset}")


def results_query(player_id: int, start: date | None, end: date | None, zone: tzinfo,
                  placeholder: str = "?") -> tuple[str, tuple[Any, ...]]:
    """Parameterized USD cash query, with half-open UTC bounds derived locally."""
    conditions = [f"hp.playerId = {placeholder}", "gt.type = 'ring'", "gt.currency = 'USD'", "hp.tourneysPlayersId IS NULL"]
    params: list[Any] = [player_id]
    if start is not None and end is not None:
        if start > end:
            raise ValueError("Start date must not be after end date")
        bounds = (start, end + timedelta(days=1))
        for operator, day in zip((">=", "<"), bounds):
            conditions.append(f"h.startTime {operator} {placeholder}")
            params.append(datetime.combine(day, time.min, zone).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    sql = """SELECT h.id, h.startTime, hp.totalProfit, hp.allInEV, gt.bigBlind,
             hp.street0VPI, hp.street0VPIChance, hp.street0Aggr, hp.street0AggrChance,
             hp.sawShowdown, gt.category, gt.limitType
             FROM HandsPlayers hp JOIN Hands h ON h.id = hp.handId
             JOIN Gametypes gt ON gt.id = h.gametypeId WHERE """ + " AND ".join(conditions)
    return sql + " ORDER BY h.startTime, h.id", tuple(params)
