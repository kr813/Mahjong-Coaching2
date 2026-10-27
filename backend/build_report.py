"""
Mahjong Coaching - レポート生成モジュール
---------------------------------------
バックエンドから渡される新仕様JSON (ai-input-format準拠の局面リスト) を受け取り、
result_manyhands.html テンプレートに渡すデータ辞書を構築します。
Mahjong-Coaching_FrontEnd/apps/v2 の build_report 仕様に完全準拠しています。
"""

from __future__ import annotations

import re
from typing import Any

TILE_MAP = {
    '1m': '🀇', '2m': '🀈', '3m': '🀉', '4m': '🀊', '5m': '🀋', '6m': '🀌', '7m': '🀍', '8m': '🀎', '9m': '🀏',
    '5mr': '🀋', # 赤5萬
    '1p': '🀙', '2p': '🀚', '3p': '🀛', '4p': '🀜', '5p': '🀝', '6p': '🀞', '7p': '🀟', '8p': '🀠', '9p': '🀡',
    '5pr': '🀝', # 赤5筒
    '1s': '🀐', '2s': '🀑', '3s': '🀒', '4s': '🀓', '5s': '🀔', '6s': '🀕', '7s': '🀖', '8s': '🀗', '9s': '🀘',
    '5sr': '🀔', # 赤5索
    'e': '🀀', 's': '🀁', 'w': '🀂', 'n': '🀃',  # 東/南/西/北
    'p': '🀆', 'f': '🀅', 'c': '🀄︎'        # 白/發/中
}
VALID_TILES = set(TILE_MAP)

EV_WARNING_THRESHOLD = 0.15
REPORT_TITLE = "牌譜検討"
AI_LABEL = "AI"

KYOKU_WINDS = "東南西北"

TRIGGER_KINDS = {"draw", "opponent_discard"}
TRIGGER_ACTORS = {"上家", "対面", "下家"}
CHOICE_NO_ARG = {"skip", "ron", "tsumo", "riichi"}
CHOICE_KAN = {"daiminkan", "kakan", "ankan"}
MELD_TYPES = {"chi", "pon", "daiminkan", "kakan", "ankan"}
MELD_FROM = {"上家", "対面", "下家"}
RIVER_OWNERS = (("self", "自分"), ("shimocha", "下家"), ("toimen", "対面"), ("kamicha", "上家"))
RIVER_PER_ROW = 6
CALLED_BY = {"自分", "下家", "対面", "上家"}


def is_tenhou_code(code: Any) -> bool:
    return isinstance(code, int) or (isinstance(code, str) and re.fullmatch(r"\d{2}", code) is not None)


def check_tile(code: Any, path: str) -> None:
    """牌コード1つが mjai 表記か検査する。不正なら ValueError"""
    if isinstance(code, str) and code in VALID_TILES:
        return
    kind = "天鳳形式の数字コード" if is_tenhou_code(code) else "未定義の牌コード"
    raise ValueError(
        f"{path} = {code!r} は{kind}です。牌は 1m〜9m, 1p〜9p, 1s〜9s, 5mr/5pr/5sr, "
        f"e/s/w/n/p/f/c の形式で渡してください"
    )


def require_dict(parent: dict[str, Any], key: str, path: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{path}.{key} がありません（オブジェクトで渡してください）")
    return value


def parse_choice(choice: Any, path: str) -> dict[str, Any]:
    """行動 {"type": ...} → 画面用の辞書（検査つき）。不正なら ValueError"""
    if not isinstance(choice, dict) or "type" not in choice:
        raise ValueError(f'{path} は {{"type": ...}} のオブジェクトで渡してください: {choice!r}')
    kind = choice["type"]
    if kind == "discard":
        check_tile(choice.get("tile"), f"{path}.tile")
        out = {"type": "discard", "tile": choice["tile"]}
        riichi = choice.get("riichi")
        if riichi is not None and not isinstance(riichi, bool):
            raise ValueError(f"{path}.riichi は true / false にしてください: {riichi!r}")
        if riichi:
            out["riichi"] = True
        return out
    if kind in CHOICE_KAN:
        check_tile(choice.get("tile"), f"{path}.tile")
        return {"type": kind, "tile": choice["tile"]}
    if kind in ("pon", "chi"):
        tiles = choice.get("with_tiles")
        if not isinstance(tiles, list) or len(tiles) != 2:
            raise ValueError(f"{path}.with_tiles は手牌の2枚の配列にしてください: {tiles!r}")
        for j, code in enumerate(tiles):
            check_tile(code, f"{path}.with_tiles[{j}]")
        out = {"type": kind, "with_tiles": list(tiles)}
        if choice.get("then_discard") is not None:
            check_tile(choice["then_discard"], f"{path}.then_discard")
            out["then_discard"] = choice["then_discard"]
        return out
    if kind in CHOICE_NO_ARG:
        return {"type": kind}
    raise ValueError(
        f"{path}.type = {kind!r} は不正です。"
        f"discard / pon / chi / daiminkan / kakan / ankan / skip / ron / tsumo / riichi のどれかにしてください"
    )


def validate_meld(meld: Any, path: str) -> None:
    if not isinstance(meld, dict):
        raise ValueError(f"{path} がオブジェクトではありません")
    if meld.get("type") is not None and meld["type"] not in MELD_TYPES:
        raise ValueError(f"{path}.type は {sorted(MELD_TYPES)} のどれかにしてください: {meld['type']!r}")
    tiles = meld.get("tiles")
    if not isinstance(tiles, list) or not 3 <= len(tiles) <= 4:
        raise ValueError(f"{path}.tiles は3〜4枚の配列にしてください: {tiles!r}")
    for j, code in enumerate(tiles):
        check_tile(code, f"{path}.tiles[{j}]")
    if meld.get("called") is not None:
        check_tile(meld["called"], f"{path}.called")
    if meld.get("from") is not None and meld["from"] not in MELD_FROM:
        raise ValueError(f"{path}.from は {sorted(MELD_FROM)} のどれかにしてください: {meld['from']!r}")


def validate_river(river: Any, path: str) -> None:
    """河（古い順の配列）。1枚ごとに {"tile", "tsumogiri", "riichi", "called_by"}。tile 以外は省略可"""
    if not isinstance(river, list):
        raise ValueError(f"{path} は配列にしてください: {river!r}")
    for j, item in enumerate(river):
        if not isinstance(item, dict):
            raise ValueError(f"{path}[{j}] がオブジェクトではありません: {item!r}")
        check_tile(item.get("tile"), f"{path}[{j}].tile")
        for key in ("tsumogiri", "riichi"):
            if item.get(key) is not None and not isinstance(item[key], bool):
                raise ValueError(f"{path}[{j}].{key} は true / false にしてください: {item[key]!r}")
        if item.get("called_by") is not None and item["called_by"] not in CALLED_BY:
            raise ValueError(f"{path}[{j}].called_by は {sorted(CALLED_BY)} か null にしてください: {item['called_by']!r}")


def validate_record(rec: Any, i: int) -> None:
    """局面1件のうち、画面で使う項目を検査する。不正なら ValueError"""
    path = f"[{i}]"
    if not isinstance(rec, dict):
        raise ValueError(f"{path} がオブジェクトではありません")

    # --- meta: 局 ---
    meta = require_dict(rec, "meta", path)
    if not isinstance(meta.get("kyoku"), str) or not meta["kyoku"].strip():
        raise ValueError(f"{path}.meta.kyoku は空でない文字列にしてください: {meta.get('kyoku')!r}")
    honba = meta.get("honba")
    if honba is not None and (not isinstance(honba, int) or isinstance(honba, bool) or honba < 0):
        raise ValueError(f"{path}.meta.honba は0以上の整数にしてください: {honba!r}")

    # --- situation: 巡目ときっかけ ---
    sit = require_dict(rec, "situation", path)
    if not isinstance(sit.get("turn"), int) or isinstance(sit["turn"], bool):
        raise ValueError(f"{path}.situation.turn は整数にしてください: {sit.get('turn')!r}")
    for key in ("trigger", "trigger_tile"):
        if key not in sit:
            raise ValueError(f"{path}.situation に必須キー '{key}' がありません（ツモ牌なしの局面は null）")
    trigger = sit["trigger"]
    if trigger is None:
        if sit["trigger_tile"] is not None:
            raise ValueError(f"{path}.situation.trigger が null のとき、trigger_tile も null にしてください")
    else:
        if trigger not in TRIGGER_KINDS:
            raise ValueError(f"{path}.situation.trigger は {sorted(TRIGGER_KINDS)} か null にしてください: {trigger!r}")
        check_tile(sit["trigger_tile"], f"{path}.situation.trigger_tile")
        if trigger == "opponent_discard" and sit.get("trigger_actor") not in TRIGGER_ACTORS:
            raise ValueError(f"{path}.situation.trigger_actor は {sorted(TRIGGER_ACTORS)} のどれかにしてください: "
                             f"{sit.get('trigger_actor')!r}")

    # --- self: 手牌・副露 ---
    me = require_dict(rec, "self", path)
    hand = me.get("hand_with_trigger_tile")
    if not isinstance(hand, list) or not 2 <= len(hand) <= 14:
        raise ValueError(f"{path}.self.hand_with_trigger_tile は2〜14枚の配列にしてください: {hand!r}")
    for j, code in enumerate(hand):
        check_tile(code, f"{path}.self.hand_with_trigger_tile[{j}]")
    if trigger is not None and sit["trigger_tile"] not in hand:
        raise ValueError(f"{path}.situation.trigger_tile = {sit['trigger_tile']!r} が "
                         f"self.hand_with_trigger_tile に含まれていません")
    melds = me.get("melds", [])
    if not isinstance(melds, list):
        raise ValueError(f"{path}.self.melds は配列にしてください: {melds!r}")
    for j, meld in enumerate(melds):
        validate_meld(meld, f"{path}.self.melds[{j}]")

    # --- 河（任意。あれば検査して、画面に出す） ---
    for owner, _ in RIVER_OWNERS:
        holder = me if owner == "self" else (rec.get("others") or {}).get(owner)
        if isinstance(holder, dict) and holder.get("river") is not None:
            validate_river(holder["river"], f"{path}.{'self' if owner == 'self' else 'others.' + owner}.river")

    # --- decision: 行動と期待値差 ---
    dec = require_dict(rec, "decision", path)
    parse_choice(dec.get("player_choice"), f"{path}.decision.player_choice")
    parse_choice(dec.get("ai_choice"), f"{path}.decision.ai_choice")
    if "loss" not in dec:
        raise ValueError(f"{path}.decision に必須キー 'loss' がありません")
    loss = dec["loss"]
    if loss is not None and (not isinstance(loss, (int, float)) or isinstance(loss, bool)):
        raise ValueError(f"{path}.decision.loss は数値か null にしてください: {loss!r}")

    # --- commentary ---
    if rec.get("commentary") is not None and not isinstance(rec["commentary"], str):
        raise ValueError(f"{path}.commentary は文字列か null にしてください: {rec['commentary']!r}")


def normalize_backend_response(obj: Any) -> list[dict[str, Any]]:
    """バックエンドの返り値 → 局面のリスト（検査つき）。単独のオブジェクトはリストにする"""
    records = [obj] if isinstance(obj, dict) else obj
    if not isinstance(records, list) or not records:
        raise ValueError("バックエンドの返り値が、局面のオブジェクト（またはそのリスト）ではありません")
    for i, rec in enumerate(records):
        validate_record(rec, i)
    return records


def kyoku_title(meta: dict[str, Any]) -> str:
    """meta → 局の表示名。『東1局』、本場があれば『東2局 1本場』"""
    honba = meta.get("honba") or 0
    return meta["kyoku"].strip() + (f" {honba}本場" if honba else "")


def kyoku_anchor(title: str, fallback: int) -> str:
    """『東2局 1本場』→ 'kyoku-1-1'（目次のアンカー kyoku-<局の番号>-<本場> 用）"""
    m = re.match(rf"^([{KYOKU_WINDS}])(\d)局", title)
    idx = KYOKU_WINDS.index(m.group(1)) * 4 + int(m.group(2)) - 1 if m else fallback
    honba = re.search(r"(\d+)本場", title)
    return f"kyoku-{idx}-{honba.group(1) if honba else 0}"


def meld_view(m: dict[str, Any]) -> dict[str, Any]:
    """副露 → 表示用の牌リスト。鳴いた牌だけ横向き(rotated)にする（位置は from で決まる。type は使わない）"""
    tiles = list(m.get("tiles", []))
    called, src = m.get("called"), m.get("from")
    added = None
    if m.get("type") == "kakan" and len(tiles) == 4 and called in tiles[:3]:
        added, tiles = tiles[3], tiles[:3]
    pos = None
    if called in tiles and src:
        pos = {"上家": 0, "対面": 1, "下家": len(tiles) - 1}.get(src)
    if pos is None:
        return {"from": src, "tiles": [{"code": t, "rotated": False, "added": None} for t in tiles + ([added] if added else [])]}
    rest = list(tiles)
    rest.remove(called)
    ordered = rest[:pos] + [called] + rest[pos:]
    return {"from": src,
            "tiles": [{"code": t, "rotated": i == pos, "added": added if i == pos else None} for i, t in enumerate(ordered)]}


def river_note(tile: dict[str, Any]) -> str:
    """河の牌1枚に付ける説明（マウスを重ねたときに出る）"""
    parts = []
    if tile.get("riichi"):
        parts.append("立直宣言牌")
    if tile.get("tsumogiri"):
        parts.append("ツモ切り")
    if tile.get("called_by"):
        parts.append(f'{tile["called_by"]}に鳴かれた')
    return "・".join(parts)


def rivers_view(rec: dict[str, Any]) -> list[dict[str, Any]]:
    """4人の河 → 表示用。1段に RIVER_PER_ROW 枚。河が無い人は出さない"""
    out = []
    for owner, label in RIVER_OWNERS:
        holder = rec["self"] if owner == "self" else (rec.get("others") or {}).get(owner)
        river = holder.get("river") if isinstance(holder, dict) else None
        if river is None:
            continue
        tiles = []
        for r in river:
            t = {
                "code": r["tile"],
                "tsumogiri": bool(r.get("tsumogiri")),
                "riichi": bool(r.get("riichi")),
                "called_by": r.get("called_by")
            }
            t["note"] = river_note(t)
            tiles.append(t)
        out.append({
            "owner": owner,
            "label": f"{label}の河",
            "count": len(tiles),
            "rows": [tiles[i:i + RIVER_PER_ROW] for i in range(0, len(tiles), RIVER_PER_ROW)]
        })
    return out


def entry_view(rec: dict[str, Any], threshold: float) -> dict[str, Any]:
    """局面1件（新形式）→ 画面用の辞書。画面に必要な項目だけを、JSONから抽出する"""
    sit, me, dec = rec["situation"], rec["self"], rec["decision"]

    hand = list(me["hand_with_trigger_tile"])
    if sit["trigger"] is None:
        trigger, trigger_tile = None, None
    else:
        trigger_tile = sit["trigger_tile"]
        trigger = "自摸" if sit["trigger"] == "draw" else f'{sit["trigger_actor"]}打'
        hand.pop(len(hand) - 1 - hand[::-1].index(trigger_tile))

    player_choice = parse_choice(dec["player_choice"], "decision.player_choice")
    ai_choice = parse_choice(dec["ai_choice"], "decision.ai_choice")
    loss = dec["loss"]

    return {
        "turn": sit["turn"],
        "wall_remaining": None,
        "trigger": trigger,
        "trigger_label": f"{trigger} " if trigger else "",
        "trigger_tile": trigger_tile,
        "hand": hand,
        "melds": [meld_view(m) for m in reversed(me.get("melds", []))],
        "rivers": rivers_view(rec),
        "player_choice": player_choice,
        "ai_choice": ai_choice,
        "loss": loss,
        "is_match": player_choice == ai_choice,
        "is_warning": loss is not None and abs(loss) >= threshold,
        "commentary": rec.get("commentary"),
    }


def build_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    """画面 (result_manyhands.html) に渡すJSON全体を作る"""
    kyokus: dict[str, dict[str, Any]] = {}
    for rec in records:
        title = kyoku_title(rec["meta"])
        if title not in kyokus:
            kyokus[title] = {
                "anchor": kyoku_anchor(title, 100 + len(kyokus)),
                "name": title,
                "end_status": "",
                "entries": [],
            }
        kyokus[title]["entries"].append(entry_view(rec, EV_WARNING_THRESHOLD))

    entries = [e for k in kyokus.values() for e in k["entries"]]
    total = len(entries)
    matched = sum(e["is_match"] for e in entries)
    warned = sum(e["is_warning"] for e in entries)

    match_rate = f"{matched / total * 100:.3f}%" if total > 0 else "0.000%"

    return {
        "title": REPORT_TITLE,
        "engine": AI_LABEL,
        "warning_threshold": EV_WARNING_THRESHOLD,
        "meta_items": [
            ["局数", len(kyokus)],
            ["局面数", total],
            ["AI一致率", f"{matched}/{total} = {match_rate}"],
            ["注意局面", f"{warned}/{total}（期待値差 {EV_WARNING_THRESHOLD} 以上）"],
        ],
        "has_rivers": any(e["rivers"] for e in entries),
        "kyokus": list(kyokus.values()),
    }
