from __future__ import annotations

import copy
import json
import re
from typing import Any

from bs4 import Tag

HONOR_TILES = {
    41: "e",
    42: "s",
    43: "w",
    44: "n",
    45: "p",
    46: "f",
    47: "c",
}
RED_FIVES = {51: "5mr", 52: "5pr", 53: "5sr"}
RELATIVE_SEATS = ("self", "shimocha", "toimen", "kamicha")
RELATIVE_SEAT_JA = {"shimocha": "下家", "toimen": "対面", "kamicha": "上家"}


def decode_tile(value: int | str | None) -> str | None:
    """Decode a tenhou.net/6 tile code to the reviewer tile notation."""
    if value is None:
        return None
    if isinstance(value, str):
        if value.isdigit():
            value = int(value)
        else:
            return None
    if value in RED_FIVES:
        return RED_FIVES[value]
    if value in HONOR_TILES:
        return HONOR_TILES[value]
    suit = {1: "m", 2: "p", 3: "s"}.get(value // 10)
    number = value % 10
    if suit and 1 <= number <= 9:
        return f"{number}{suit}"
    return None


def _tile_codes(token: str) -> list[int]:
    return [int(value) for value in re.findall(r"\d{2}", token)]


def _meld_marker(token: str) -> str | None:
    match = re.search(r"[a-z]", token.lower())
    return match.group(0) if match else None


def _marker_index(token: str, marker: str) -> int:
    return len(re.findall(r"\d{2}", token[: token.lower().index(marker)]))


def _absolute_source(caller: int, relative: str) -> int:
    offsets = {"kamicha": -1, "toimen": 2, "shimocha": 1}
    return (caller + offsets[relative]) % 4


def relative_seat(viewer: int, absolute_seat: int) -> str:
    return RELATIVE_SEATS[(absolute_seat - viewer) % 4]


def _call_source(token: str, caller: int) -> int | None:
    marker = _meld_marker(token)
    if marker == "c":
        return _absolute_source(caller, "kamicha")
    if marker == "p":
        index = _marker_index(token, marker)
        relative = ("kamicha", "toimen", "shimocha")[min(index, 2)]
        return _absolute_source(caller, relative)
    if marker == "m":
        index = _marker_index(token, marker)
        if index == 0:
            relative = "kamicha"
        elif index >= 3:
            relative = "shimocha"
        else:
            relative = "toimen"
        return _absolute_source(caller, relative)
    return None


def _meld_from_call(token: str, caller: int) -> dict[str, Any]:
    marker = _meld_marker(token)
    codes = _tile_codes(token)
    tiles = [tile for code in codes if (tile := decode_tile(code)) is not None]
    source = _call_source(token, caller)
    called_index = min(_marker_index(token, marker or ""), max(len(tiles) - 1, 0))
    meld_type = {"c": "chi", "p": "pon", "m": "kan"}.get(marker or "", "unknown")
    return {
        "type": meld_type,
        "tile": tiles[called_index] if tiles else None,
        "tiles": tiles,
        "from": RELATIVE_SEAT_JA.get(relative_seat(caller, source)) if source is not None else None,
    }


def _update_added_kan(melds: list[dict[str, Any]], token: str) -> None:
    tiles = [tile for code in _tile_codes(token) if (tile := decode_tile(code)) is not None]
    tile = tiles[0] if tiles else None
    for meld in melds:
        if meld.get("type") == "pon" and meld.get("tile") == tile:
            meld["type"] = "kan"
            meld["tiles"] = tiles
            return
    melds.append({"type": "kan", "tile": tile, "tiles": tiles, "from": None})


def _extract_round_log(section: Tag) -> list[Any] | None:
    textarea = section.find("textarea")
    if textarea is None:
        return None
    try:
        payload = json.loads(textarea.get_text(strip=True))
        logs = payload.get("log") if isinstance(payload, dict) else None
        if not isinstance(logs, list) or not logs:
            return None
        return logs[0]
    except (json.JSONDecodeError, TypeError):
        return None


def _snapshot(
    *,
    kind: str,
    viewer: int,
    source: int | None,
    tile: str | None,
    wall_remaining: int,
    dora_codes: list[Any],
    visible_dora_count: int,
    scores: list[int],
    rivers: list[list[str]],
    riichi: list[bool],
    melds: list[list[dict[str, Any]]],
) -> dict[str, Any]:
    dora_indicators = [
        tile_name
        for value in dora_codes[:visible_dora_count]
        if (tile_name := decode_tile(value)) is not None
    ]
    return {
        "kind": kind,
        "source": relative_seat(viewer, source) if source is not None else None,
        "tile": tile,
        "wall_remaining": wall_remaining,
        "dora_indicators": dora_indicators,
        "scores": list(scores),
        "rivers": {
            name: list(rivers[(viewer + offset) % 4])
            for offset, name in enumerate(RELATIVE_SEATS)
        },
        "riichi": list(riichi),
        "melds": copy.deepcopy(melds[viewer]),
    }


def _discard_tile(token: Any, drawn_tile: str | None) -> tuple[str | None, bool]:
    if isinstance(token, int):
        if token == 60:
            return drawn_tile, False
        return decode_tile(token), False
    if isinstance(token, str) and token.lower().startswith("r"):
        codes = _tile_codes(token)
        return (decode_tile(codes[0]) if codes else drawn_tile), True
    return None, False


def _is_incoming_call(token: Any) -> bool:
    return isinstance(token, str) and _meld_marker(token) in {"c", "p", "m"}


def build_round_candidates(section: Tag, viewer: int) -> list[dict[str, Any]]:
    """Replay the embedded tenhou.net/6 log and return decision-state candidates."""
    round_log = _extract_round_log(section)
    if round_log is None or len(round_log) < 16:
        return []

    round_info = round_log[0]
    scores = [int(value) for value in round_log[1]]
    dora_codes = list(round_log[2])
    draws = [list(round_log[5 + seat * 3]) for seat in range(4)]
    discards = [list(round_log[6 + seat * 3]) for seat in range(4)]
    indices = [0, 0, 0, 0]
    rivers: list[list[str]] = [[], [], [], []]
    riichi = [False, False, False, False]
    melds: list[list[dict[str, Any]]] = [[], [], [], []]
    visible_dora_count = 1 if dora_codes else 0
    wall_remaining = 70
    actor = int(round_info[0]) % 4
    candidates: list[dict[str, Any]] = []

    def add_candidate(kind: str, source: int | None, tile: str | None) -> None:
        candidates.append(
            _snapshot(
                kind=kind,
                viewer=viewer,
                source=source,
                tile=tile,
                wall_remaining=wall_remaining,
                dora_codes=dora_codes,
                visible_dora_count=visible_dora_count,
                scores=scores,
                rivers=rivers,
                riichi=riichi,
                melds=melds,
            )
        )

    def find_caller(discarder: int, discarded_tile: str | None) -> int | None:
        if discarded_tile is None:
            return None
        for offset in (1, 2, 3):
            caller = (discarder + offset) % 4
            index = indices[caller]
            if index >= len(draws[caller]):
                continue
            token = draws[caller][index]
            if not _is_incoming_call(token):
                continue
            source = _call_source(token, caller)
            tiles = [decode_tile(code) for code in _tile_codes(token)]
            if source == discarder and discarded_tile in tiles:
                return caller
        return None

    max_steps = sum(len(values) for values in draws) + 8
    for _ in range(max_steps):
        index = indices[actor]
        if index >= len(draws[actor]):
            break

        draw_token = draws[actor][index]
        discard_token = discards[actor][index] if index < len(discards[actor]) else None
        indices[actor] += 1
        drawn_tile: str | None = None

        if isinstance(draw_token, int):
            drawn_tile = decode_tile(draw_token)
            wall_remaining -= 1
            if actor == viewer:
                add_candidate("draw", None, drawn_tile)
        elif _is_incoming_call(draw_token):
            source = _call_source(draw_token, actor)
            meld = _meld_from_call(draw_token, actor)
            if source is not None and rivers[source]:
                rivers[source].pop()
            melds[actor].append(meld)
            drawn_tile = meld.get("tile")
        else:
            continue

        if isinstance(discard_token, str) and _meld_marker(discard_token) in {"a", "k", "m"}:
            _update_added_kan(melds[actor], discard_token)
            visible_dora_count = min(visible_dora_count + 1, len(dora_codes))
            continue

        if discard_token in (None, 0):
            if _meld_marker(str(draw_token)) == "m":
                visible_dora_count = min(visible_dora_count + 1, len(dora_codes))
            continue

        discarded_tile, declared_riichi = _discard_tile(discard_token, drawn_tile)
        if discarded_tile is None:
            actor = (actor + 1) % 4
            continue
        rivers[actor].append(discarded_tile)
        if declared_riichi and not riichi[actor]:
            riichi[actor] = True
            scores[actor] -= 1000

        if actor != viewer:
            add_candidate("response", actor, discarded_tile)

        caller = find_caller(actor, discarded_tile)
        actor = caller if caller is not None else (actor + 1) % 4

    return candidates


def _entry_kind(entry: dict[str, Any]) -> str:
    label = str(entry.get("tsumo_label") or "").lower()
    if "draw" in label or "自摸" in label or "ツモ" in label:
        return "draw"
    return "response"


def _entry_source(entry: dict[str, Any]) -> str | None:
    label = str(entry.get("tsumo_label") or "").lower()
    aliases = {
        "shimocha": ("shimocha", "下家"),
        "toimen": ("toimen", "対面"),
        "kamicha": ("kamicha", "上家"),
    }
    for result, values in aliases.items():
        if any(value in label for value in values):
            return result
    return None


def attach_round_states(entries: list[dict[str, Any]], section: Tag, viewer: int) -> None:
    """Attach the closest replay snapshot to each reviewer decision in document order."""
    candidates = build_round_candidates(section, viewer)
    cursor = 0
    for entry in entries:
        kind = _entry_kind(entry)
        source = _entry_source(entry)
        tile = entry.get("tsumo")
        wall_remaining = entry.get("wall_remaining")
        matched_index: int | None = None
        for index in range(cursor, len(candidates)):
            candidate = candidates[index]
            if candidate["kind"] != kind:
                continue
            if wall_remaining is not None and candidate["wall_remaining"] != wall_remaining:
                continue
            if tile is not None and candidate["tile"] != tile:
                continue
            if source is not None and candidate["source"] != source:
                continue
            matched_index = index
            break

        if matched_index is None:
            entry["state_available"] = False
            continue

        state = candidates[matched_index]
        cursor = matched_index + 1
        entry.update(
            {
                "state_available": True,
                "dora_indicators": state["dora_indicators"],
                "scores": state["scores"],
                "melds": state["melds"],
                "rivers": state["rivers"],
                "riichi": state["riichi"],
            }
        )
