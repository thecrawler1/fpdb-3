"""Lightweight database keys for sorting the full hand list before pagination."""

from typing import Any

from fpdb_3_legacy.table_cards import card_sort_key

FIELDS = {
    "Date": "h.startTime",
    "Players": "(SELECT COUNT(*) FROM HandsPlayers players WHERE players.handId = h.id)",
    "Pos": "hp.position",
    "Won": "hp.winnings",
    "Bet": "hp.committed",
    "Net": "hp.totalProfit",
    "HandId": "h.id",
    "Total Pot": "h.finalPot",
    "Rake": "(SELECT SUM(players.rake) FROM HandsPlayers players WHERE players.handId = h.id)",
    "SiteHandNo": "h.siteHandNo",
    "Splash": "h.splashPot",
    "Game": "gt.category",
    "Stakes": "gt.bigBlind",
    "Street0": ", ".join(f"hp.card{i}" for i in range(1, 8)),
    "Street1-4": ", ".join(f"h.boardcard{i}" for i in range(1, 6)),
}


def _site_aliases(site, heroes):
    aliases = heroes.get(site)
    if aliases is None:
        normalized = site.lower().replace(" ", "").replace(".", "").replace("-", "")
        for parent, names in heroes.items():
            base = parent.lower().replace(" ", "").replace(".", "").replace("-", "")
            if normalized.startswith(base) or base.startswith(normalized):
                aliases = names
                break
    return [aliases] if isinstance(aliases, str) else aliases


def load_sort_keys(db, handids, column, heroes):
    """Return keys for every requested ID; None means a reconstructed column."""
    fields = FIELDS.get(column)
    if fields is None:
        return None
    placeholder = db.sql.query.get("placeholder", "%s")
    keys: dict[int, Any] = {}
    priorities: dict[int, int] = {}
    cursor = db.get_cursor()
    for start in range(0, len(handids), 400):
        chunk = handids[start:start + 400]
        query = f"""SELECT h.id, s.name, p.name, hp.seatNo, h.heroSeat, {fields}
                    FROM Hands h JOIN Gametypes gt ON gt.id = h.gametypeId
                    JOIN Sites s ON s.id = gt.siteId
                    LEFT JOIN HandsPlayers hp ON hp.handId = h.id
                    LEFT JOIN Players p ON p.id = hp.playerId
                    WHERE h.id IN ({', '.join([placeholder] * len(chunk))})"""
        cursor.execute(query, chunk)
        for handid, site, player, seat, hero_seat, *values in cursor.fetchall():
            aliases = _site_aliases(site, heroes)
            if (aliases and player not in aliases) or (not aliases and seat != hero_seat):
                continue
            priority = aliases.index(player) if aliases else 0
            if handid in priorities and priorities[handid] <= priority:
                continue
            priorities[handid] = priority
            value: Any
            if column in ("Street0", "Street1-4"):
                value = card_sort_key(values, hole=column == "Street0")
            elif column in ("Date", "Pos", "Game"):
                value = str(values[0] or "")
            else:
                value = values[0] or 0
            keys[handid] = value
    default = card_sort_key([], hole=column == "Street0") if column.startswith("Street") else "" if column in ("Date", "Pos", "Game") else 0
    return {handid: keys.get(handid, default) for handid in handids}
