"""
shanten_calculator.py

麻雀の手牌に対する向聴数（シャンテン数）および有効牌・受け入れ枚数計算モジュール。
外部ライブラリ非依存（Pure Python）で高速に動作します。
"""
from collections import Counter
from typing import Any

ALL_TILES_34 = (
    [f"{i}m" for i in range(1, 10)]
    + [f"{i}p" for i in range(1, 10)]
    + [f"{i}s" for i in range(1, 10)]
    + ["e", "s", "w", "n", "p", "f", "c"]
)

SHANTEN_NAMES = {
    -1: "和了",
    0: "テンパイ",
    1: "一向聴",
    2: "二向聴",
    3: "三向聴",
    4: "四向聴",
    5: "五向聴",
    6: "六向聴",
}

YAOCHU_IDS = (0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33)


def tile_base(code: str | None) -> str:
    """赤ドラ('5mr')を通常牌('5m')に変換する"""
    if not code:
        return ""
    if len(code) == 3 and code.endswith("r"):
        return code[:-1]
    return code


def tile_to_id(tile: str) -> int:
    """牌コード -> 0〜33 のインデックス"""
    t = tile_base(tile)
    if t in ("e", "s", "w", "n", "p", "f", "c"):
        return 27 + ("e", "s", "w", "n", "p", "f", "c").index(t)
    num = int(t[0]) - 1
    suit_idx = {"m": 0, "p": 1, "s": 2}[t[1]]
    return suit_idx * 9 + num


def calculate_shanten(hand_tiles: list[str], meld_count: int = 0) -> int:
    """手牌リストと副露面子数からシャンテン数を計算する。
    13枚/10枚/7枚/4枚/1枚: 0=テンパイ, 1=一向聴...
    14枚/11枚/8枚/5枚/2枚: -1=和了, 0=テンパイ...
    """
    counts = [0] * 34
    for t in hand_tiles:
        counts[tile_to_id(t)] += 1
    total = sum(counts)
    req_mentsu = 4 - meld_count

    # 1. 国士無双（門前のみ）
    kokushi = 99
    if meld_count == 0 and total in (13, 14):
        kinds = sum(1 for y in YAOCHU_IDS if counts[y] > 0)
        has_pair = any(counts[y] >= 2 for y in YAOCHU_IDS)
        if total == 14:
            kokushi = -1 if (kinds == 13 and has_pair) else (13 - kinds - (1 if has_pair else 0))
        else:
            kokushi = 13 - kinds - (1 if has_pair else 0)

    # 2. 七対子（門前のみ）
    chitoi = 99
    if meld_count == 0 and total in (13, 14):
        pairs = sum(1 for c in counts if c >= 2)
        kinds_all = sum(1 for c in counts if c > 0)
        if total == 14 and pairs == 7:
            chitoi = -1
        else:
            chitoi = 6 - pairs + max(0, 7 - kinds_all)

    # 3. 一般手（面子手）
    best_shanten = [8]

    def search_mentsu(counts_cur: list[int], idx: int, m: int, t: int, has_head: bool) -> None:
        while idx < 34 and counts_cur[idx] == 0:
            idx += 1
        if idx == 34:
            usable_t = min(t, req_mentsu - m)
            cur_s = (req_mentsu - m) * 2 - usable_t - (1 if has_head else 0)
            if total % 3 == 2 and m == req_mentsu and has_head:
                cur_s = -1
            if cur_s < best_shanten[0]:
                best_shanten[0] = cur_s
            return

        # 刻子
        if counts_cur[idx] >= 3:
            counts_cur[idx] -= 3
            search_mentsu(counts_cur, idx, m + 1, t, has_head)
            counts_cur[idx] += 3

        # 順子（数牌のみ、各スートの7番目まで）
        if idx < 27 and idx % 9 <= 6:
            if counts_cur[idx + 1] > 0 and counts_cur[idx + 2] > 0:
                counts_cur[idx] -= 1
                counts_cur[idx + 1] -= 1
                counts_cur[idx + 2] -= 1
                search_mentsu(counts_cur, idx, m + 1, t, has_head)
                counts_cur[idx] += 1
                counts_cur[idx + 1] += 1
                counts_cur[idx + 2] += 1

        # 対子（塔子扱い）
        if counts_cur[idx] >= 2:
            counts_cur[idx] -= 2
            search_mentsu(counts_cur, idx, m, t + 1, has_head)
            counts_cur[idx] += 2

        # 塔子（両面・カンチャン）
        if idx < 27:
            if idx % 9 <= 7 and counts_cur[idx + 1] > 0:
                counts_cur[idx] -= 1
                counts_cur[idx + 1] -= 1
                search_mentsu(counts_cur, idx, m, t + 1, has_head)
                counts_cur[idx] += 1
                counts_cur[idx + 1] += 1
            if idx % 9 <= 6 and counts_cur[idx + 2] > 0:
                counts_cur[idx] -= 1
                counts_cur[idx + 2] -= 1
                search_mentsu(counts_cur, idx, m, t + 1, has_head)
                counts_cur[idx] += 1
                counts_cur[idx + 2] += 1

        # 孤立牌としてスキップ
        search_mentsu(counts_cur, idx + 1, m, t, has_head)

    # 雀頭ありの探索
    for i in range(34):
        if counts[i] >= 2:
            counts[i] -= 2
            search_mentsu(counts, 0, 0, 0, True)
            counts[i] += 2

    # 雀頭なしの探索
    search_mentsu(counts, 0, 0, 0, False)

    return min(best_shanten[0], chitoi, kokushi)


def calculate_acceptance(
    post_hand_tiles: list[str],
    meld_count: int = 0,
    visible_tiles: list[str] | None = None
) -> dict[str, Any]:
    """打牌後の手牌からシャンテン数、有効牌リスト、受け入れ枚数を計算する。"""
    current_shanten = calculate_shanten(post_hand_tiles, meld_count=meld_count)

    hand_base_counts = Counter(tile_base(t) for t in post_hand_tiles)
    vis_base_counts = Counter(tile_base(t) for t in (visible_tiles or []))

    effective_tiles: list[str] = []
    details: list[dict[str, Any]] = []
    remaining_count = 0
    max_count = 0

    for t in ALL_TILES_34:
        # 1牌加えたときのシャンテン数を判定
        shanten_after = calculate_shanten(post_hand_tiles + [t], meld_count=meld_count)
        if shanten_after < current_shanten:
            effective_tiles.append(t)
            t_base = tile_base(t)
            # 手牌外からの最大枚数: 4 - (打牌後手牌内の枚数)
            in_hand = hand_base_counts.get(t_base, 0)
            tile_max = max(0, 4 - in_hand)
            # 残り枚数: 4 - (場見え枚数)
            visible = vis_base_counts.get(t_base, 0)
            tile_rem = max(0, 4 - visible)

            details.append({
                "tile": t,
                "remaining": tile_rem,
                "max": tile_max,
            })
            max_count += tile_max
            remaining_count += tile_rem

    return {
        "shanten": current_shanten,
        "shanten_desc": SHANTEN_NAMES.get(current_shanten, f"{current_shanten}向聴"),
        "tiles": effective_tiles,
        "remaining_count": remaining_count,
        "max_count": max_count,
        "details": details,
    }


def compute_choice_acceptance(
    choice: dict[str, Any] | None,
    hand_with_trigger_tile: list[str],
    melds: list[dict[str, Any]] | None = None,
    visible_tiles: list[str] | None = None
) -> dict[str, Any] | None:
    """行動情報から打牌後の手牌を作成し、受け入れ情報を算出する。打牌がない行動は None。"""
    if not isinstance(choice, dict):
        return None

    action_type = choice.get("type")
    melds = melds or []
    meld_count = len(melds)

    post_hand = list(hand_with_trigger_tile)

    def remove_one(target_tile: str) -> bool:
        if target_tile in post_hand:
            post_hand.remove(target_tile)
            return True
        tb = tile_base(target_tile)
        for i, t in enumerate(post_hand):
            if tile_base(t) == tb:
                post_hand.pop(i)
                return True
        return False

    if action_type == "discard":
        discard_tile = choice.get("tile")
        if not discard_tile:
            return None
        remove_one(discard_tile)
        return calculate_acceptance(post_hand, meld_count=meld_count, visible_tiles=visible_tiles)

    if action_type in ("pon", "chi") and choice.get("then_discard"):
        with_tiles = choice.get("with_tiles", [])
        for wt in with_tiles:
            remove_one(wt)
        then_discard = choice.get("then_discard")
        remove_one(then_discard)
        return calculate_acceptance(post_hand, meld_count=meld_count + 1, visible_tiles=visible_tiles)

    return None
