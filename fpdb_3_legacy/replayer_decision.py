"""Hero-facing replay arithmetic using only the states already displayed."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

ZERO = Decimal(0)
HUNDRED = Decimal(100)


@dataclass(frozen=True)
class HeroDecision:
    street: str = ""
    mode: str = "neutral"
    action: str = ""
    call_amount: Decimal = ZERO
    bet_amount: Decimal = ZERO
    bet_pct: Decimal | None = None
    pot_odds_pct: Decimal | None = None
    mdf_pct: Decimal | None = None
    fold_equity_pct: Decimal | None = None
    street_pot: Decimal = ZERO
    effective: tuple[tuple[str, Decimal], ...] = ()

    @property
    def spr(self) -> tuple[Decimal, ...]:
        return tuple(stack / self.street_pot for _, stack in self.effective) if self.street_pot > 0 else ()


def _live(player: Any) -> bool:
    return not getattr(player, "folded", False) and player.action != "folds"


def _pot(state: Any) -> Decimal:
    # startPhase may return an unmatched bet without updating newpot. Actual
    # contributions respect that return and include all folded dead money.
    if all(hasattr(p, "startStack") for p in state.players.values()):
        return sum((max(ZERO, p.startStack - p.stack) for p in state.players.values()), ZERO)
    return max(ZERO, getattr(state, "newpot", getattr(state, "pot", ZERO)))


def _aggression(states: list[Any], index: int, start: int, name: str) -> tuple[Any, Any] | None:
    for i in range(index, start, -1):
        player = states[i].players.get(name)
        if player and player.justacted and player.action in {"bets", "raises"}:
            previous = states[i - 1]
            # Phase copies can retain justacted; require a real investment.
            if player.chips > previous.players[name].chips:
                return previous, states[i]
    return None


def _sizing(previous: Any, current: Any, name: str) -> tuple[Decimal, Decimal | None]:
    investment = current.players[name].chips - previous.players[name].chips
    pot = _pot(previous)
    return investment, investment / pot * HUNDRED if pot > 0 else None


def _call_odds(state: Any, hero: Any, amount: Decimal) -> Decimal | None:
    if all(hasattr(p, "startStack") for p in state.players.values()):
        cap = hero.startStack - hero.stack + amount
        final_pot = sum((min(max(ZERO, p.startStack - p.stack), cap) for p in state.players.values()), ZERO) + amount
    else:
        final_pot = _pot(state) + amount
    return amount / final_pot * HUNDRED if final_pot > 0 else None


def hero_decision(states: list[Any], index: int, hero_name: str) -> HeroDecision:
    """Street-start SPR, current call odds and pure HU defence/bluff thresholds.

    Multiway SPR is a per-opponent range. MDF is not assigned to individual
    opponents in multiway. A raise risks the new investment in that action,
    measured against the pot immediately before it; uncallable excess is capped.
    """
    if not states or not 0 <= index < len(states):
        return HeroDecision()
    state = states[index]
    start = index
    while start > 0 and states[start - 1].street == state.street:
        start -= 1
    initial = states[start]
    initial_hero = initial.players.get(hero_name)
    effective = tuple(
        (name, min(initial_hero.stack, player.stack))
        for name, player in initial.players.items()
        if initial_hero and _live(initial_hero) and name != hero_name and _live(player)
    )
    base: dict[str, Any] = {"street": state.street or "", "street_pot": _pot(initial), "effective": effective}
    hero = state.players.get(hero_name)
    opponents = [p for name, p in state.players.items() if name != hero_name and _live(p)]
    if hero is None or not _live(hero) or getattr(state, "ended", False) or not opponents:
        return HeroDecision(**base)
    highest = max(p.chips for p in opponents)
    call = min(hero.stack, max(ZERO, highest - hero.chips))
    if call > 0:
        aggressor = next(p for p in opponents if p.chips == highest)
        event = _aggression(states, index, start, aggressor.name)
        sizing = _sizing(*event, aggressor.name)[1] if event else None
        return HeroDecision(**base, mode="call", call_amount=call, pot_odds_pct=_call_odds(state, hero, call), bet_pct=sizing)
    event = _aggression(states, index, start, hero_name) if hero.chips > 0 and hero.action in {"bets", "raises"} and highest <= hero.chips else None
    if event is None:
        return HeroDecision(**base)
    previous, current = event
    amount, sizing = _sizing(previous, current, hero_name)
    prior_opponents = [p for name, p in previous.players.items() if name != hero_name and _live(p)]
    mdf = fe = None
    if len(prior_opponents) == 1:
        opponent = prior_opponents[0]
        risk = max(ZERO, min(current.players[hero_name].chips, opponent.stack + opponent.chips) - previous.players[hero_name].chips)
        pot = _pot(previous)
        if risk > 0 and pot > 0:
            mdf, fe = pot / (pot + risk) * HUNDRED, risk / (pot + risk) * HUNDRED
    return HeroDecision(**base, mode="bet", action=current.players[hero_name].action, bet_amount=amount,
                        bet_pct=sizing, mdf_pct=mdf, fold_equity_pct=fe)
