from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

import tenhou_state

# mjai-reviewer のレポートHTMLから、自分の全判断（打牌・鳴き・立直など）を抽出する。
# Mortal（日本語表記: プレイヤー: / N巡目）と Akochan（英語表記: Player: / Turn N）の両方に対応する。

PLAYER_ROLE_LABELS = ("プレイヤー", "Player")
DISCARD_WORDS = {"打", "Discard"}


# --- 牌ID抽出 ---
def get_tile_id(tag: Any) -> str | None:
    if not tag:
        return None
    href = tag.get("href") or tag.get("xlink:href") or ""
    return href.replace("#pai-", "") or None


def _svg_tile(svg: Tag) -> str | None:
    return get_tile_id(svg.find("use"))


# --- アクション（打牌・鳴きなど）の解析 ---
def action_parts(nodes: list[Any]) -> list[dict[str, str]]:
    """ノード列を [{"tile": "5s"}, {"text": "チー"}, ...] の形に変換する。"""
    parts: list[dict[str, str]] = []
    for node in nodes:
        if isinstance(node, NavigableString):
            text = re.sub(r"\s+", " ", str(node)).strip()
            if text:
                parts.append({"text": text})
        elif isinstance(node, Tag):
            if node.name == "svg":
                tile = _svg_tile(node)
                if tile:
                    parts.append({"tile": tile})
            elif "role" in (node.get("class") or []):
                continue
            else:
                parts.extend(action_parts(list(node.children)))
    return parts


def action_label(parts: list[dict[str, str]]) -> str:
    """表示用パーツを比較・JSON用の文字列にする。
    例: 打 5s → "5s" / 7s 8s チー → "7s8sチー" / スルー → "スルー"
    """
    out: list[str] = []
    for p in parts:
        if "tile" in p:
            out.append(p["tile"])
        else:
            words = [w for w in p["text"].split(" ") if w and w not in DISCARD_WORDS]
            out.append("".join(words))
    return "".join(out)


# reviewer のHTMLは </td> </li> を省略しているため、html.parser では
# 後続の要素が入れ子として解釈される。入れ子の同名要素を除いた「自身の子」だけを扱う。
def _own_children(tag: Tag) -> list[Any]:
    return [c for c in tag.children if not (isinstance(c, Tag) and c.name == tag.name)]


def _row_cells(row: Tag) -> list[Tag]:
    return [td for td in row.find_all("td") if td.find_parent("tr") is row]


def _parse_ev(td: Tag | None) -> float | None:
    if td is None:
        return None
    text = "".join(c.get_text() if isinstance(c, Tag) else str(c) for c in _own_children(td))
    try:
        return float(re.sub(r"\s+", "", text))
    except ValueError:
        return None


# --- 手牌の解析 ---
def extract_hand(entry: Tag) -> dict[str, Any]:
    hand: list[str] = []
    tsumo: str | None = None
    tsumo_label = ""
    fuuro: list[list[dict[str, Any]]] = []
    tehai: list[str] = []

    tehai_ul = entry.find("ul", class_="tehai-state")
    if tehai_ul:
        meld_index: dict[int, int] = {}
        for use in tehai_ul.find_all("use"):
            tile = get_tile_id(use)
            if not tile:
                continue
            # JSON用の tehai は、従来どおり手牌・ツモ・副露をHTML順にすべて並べる
            tehai.append(tile)

            nearest_ul = use.find_parent("ul")
            nearest_li = use.find_parent("li")
            li_classes = (nearest_li.get("class") or []) if nearest_li else []
            if nearest_ul is not None and "consumed" in (nearest_ul.get("class") or []):
                key = id(nearest_ul)
                if key not in meld_index:
                    meld_index[key] = len(fuuro)
                    fuuro.append([])
                fuuro[meld_index[key]].append({"tile": tile, "rotated": "rotated" in li_classes})
            elif "tsumo" in li_classes:
                tsumo = tile
                tsumo_label = (nearest_li.get("before") or "").strip()
            else:
                hand.append(tile)

    return {"hand": hand, "tsumo": tsumo, "tsumo_label": tsumo_label, "fuuro": fuuro, "tehai": tehai}


# --- 局と巡目 ---
def get_kyoku_info(section: Tag) -> tuple[str, str, str]:
    kyoku, kyoku_id, end_status = "Unknown", "", ""
    h1 = section.find("h1", class_="kyoku-heading")
    if h1:
        kyoku_id = h1.get("id") or ""
        div = h1.find("div")
        kyoku = (div or h1).get_text(strip=True)
        status = h1.find(class_="end-status")
        if status:
            end_status = status.get_text(strip=True)
    return kyoku, kyoku_id, end_status


def get_turn(entry: Tag) -> int:
    summary = entry.find("summary")
    text = summary.get_text(" ", strip=True) if summary else ""
    m = re.search(r"(\d+)\s*巡目", text) or re.search(r"Turn\s+(\d+)", text, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def get_wall_remaining(entry: Tag) -> int | None:
    summary = entry.find("summary")
    text = summary.get_text(" ", strip=True) if summary else ""
    match = re.search(r"[×x]\s*(\d+)", text, re.IGNORECASE)
    if match is None:
        match = re.search(r"(?:remaining|残り)\s*(\d+)", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


# --- 1判断分の解析 ---
def parse_entry(entry: Tag) -> dict[str, Any] | None:
    player_parts: list[dict[str, str]] | None = None
    ai_name = "AI"
    ai_nodes: list[Any] = []
    collecting_ai = False
    table_details: Tag | None = None

    for node in entry.children:
        if isinstance(node, Tag):
            classes = node.get("class") or []
            if node.name == "span" and "role" in classes:
                # AI 側のラベル（例: "Mortal: "）。以降のノードが AI のアクション
                ai_name = node.get_text(strip=True).rstrip(":： ")
                collecting_ai = True
                continue
            if node.name == "span" and player_parts is None:
                role = node.find("span", class_="role", recursive=False)
                if role and any(lbl in role.get_text() for lbl in PLAYER_ROLE_LABELS):
                    player_parts = action_parts(list(node.children))
                    continue
            if node.name == "details":
                table_details = node
                break
        if collecting_ai:
            ai_nodes.append(node)

    if player_parts is None or table_details is None:
        return None
    table = table_details.find("table", class_="data")
    rows = table.find("tbody").find_all("tr") if table and table.find("tbody") else []
    if not rows:
        return None

    ai_parts = action_parts(ai_nodes)
    player_label = action_label(player_parts)
    ai_label = action_label(ai_parts)

    player_ev: float | None = None
    player_deal_in: float | None = None
    ai_ev: float | None = None
    ai_deal_in: float | None = None
    for row in rows:
        tds = _row_cells(row)
        if len(tds) < 2:
            continue
        row_label = action_label(action_parts(_own_children(tds[0])))
        if player_ev is None and row_label == player_label:
            player_ev = _parse_ev(tds[1])
            player_deal_in = _parse_ev(tds[2]) if len(tds) >= 3 else None
        if ai_ev is None and row_label == ai_label:
            ai_ev = _parse_ev(tds[1])
            ai_deal_in = _parse_ev(tds[2]) if len(tds) >= 3 else None

    if ai_ev is None:
        first_tds = _row_cells(rows[0])
        ai_ev = _parse_ev(first_tds[1]) if len(first_tds) >= 2 else 0.0
        ai_ev = ai_ev or 0.0
        ai_deal_in = _parse_ev(first_tds[2]) if len(first_tds) >= 3 else None
    if player_ev is None:
        # 候補表にプレイヤーの選択が無い場合は差なしとして扱う（従来の挙動）
        player_ev = ai_ev
        player_deal_in = ai_deal_in

    return {
        "turn": get_turn(entry),
        "wall_remaining": get_wall_remaining(entry),
        **extract_hand(entry),
        "player_discard": player_label,
        "player_parts": player_parts,
        "player_ev": player_ev,
        "player_deal_in": player_deal_in,
        "ai_name": ai_name,
        "ai_discard": ai_label,
        "ai_parts": ai_parts,
        "ai_ev": ai_ev,
        "ai_deal_in": ai_deal_in,
        "loss": ai_ev - player_ev,
    }


def _load_soup(html_path: str) -> BeautifulSoup:
    for enc in ["utf-8", "utf-16", "cp932", "utf-8-sig"]:
        try:
            with open(html_path, "r", encoding=enc) as f:
                return BeautifulSoup(f.read(), "html.parser")
        except UnicodeDecodeError:
            continue
    raise Exception("どのエンコーディングでもファイルを読み込めませんでした。")


def get_player_id(soup: BeautifulSoup) -> int | None:
    metadata_text = " ".join(soup.stripped_strings)
    match = re.search(r"(?:player[ _]?id|プレイヤー\s*id)\s*[:：]?\s*([0-3])", metadata_text, re.IGNORECASE)
    if match:
        return int(match.group(1))

    for dt in soup.find_all("dt"):
        label = dt.get_text(" ", strip=True).lower()
        if label not in {"player id", "player_id", "プレイヤーid", "プレイヤー id"}:
            continue
        # reviewer HTML omits some closing tags, so html.parser may nest the
        # following dd instead of treating it as a sibling.
        dd = dt.find_next("dd")
        if dd is None:
            continue
        try:
            player_id = int(dd.get_text(strip=True))
        except ValueError:
            continue
        if 0 <= player_id <= 3:
            return player_id
    return None


def _empty_state() -> dict[str, Any]:
    return {
        "state_available": False,
        "dora_indicators": [],
        "scores": [],
        "melds": [],
        "rivers": {"self": [], "shimocha": [], "toimen": [], "kamicha": []},
        "riichi": [],
    }


def extract_entries(html_path: str, seat: int | None = None) -> list[dict[str, Any]]:
    """レポート内の全判断を出現順に返す。値は丸めていない生の値。"""
    soup = _load_soup(html_path)
    viewer = seat if seat is not None else get_player_id(soup)
    entries: list[dict[str, Any]] = []
    for section in soup.find_all("section"):
        kyoku, kyoku_id, end_status = get_kyoku_info(section)
        section_entries: list[dict[str, Any]] = []
        for entry in section.find_all("details", class_="entry"):
            data = parse_entry(entry)
            if data is None:
                continue
            decision_id = f"{kyoku_id or 'kyoku'}-{len(section_entries):03d}"
            section_entries.append(
                {
                    "decision_id": decision_id,
                    "kyoku": kyoku,
                    "kyoku_id": kyoku_id,
                    "end_status": end_status,
                    **_empty_state(),
                    **data,
                }
            )
        if viewer is not None:
            tenhou_state.attach_round_states(section_entries, section, viewer)
        entries.extend(section_entries)
    return entries


def extract_report(html_path: str) -> dict[str, Any]:
    entries = extract_entries(html_path)
    if not entries:
        return {"error": "No analysable report entries were found."}
    return {"entries": entries}
