"""
build_ai_input.py

Akochan(mjai-reviewer)のレポートHTMLから、生成AIに渡す「局面ごとの入力JSON」を作る。
  - Akochanの評価値(候補の表)               : HTMLの details.entry
  - 河・副露・他家の状況・他家の手牌・ドラ    : 埋め込み天鳳JSONを復元 (reconstruct_table_state.py)

対応: 複数局 / 自分の席が0以外 / チー・ポン・カン・リーチ

使い方:
    python3 build_ai_input.py report.html [出力先.json] [--lines]

  出力先を省略すると標準出力。--lines を付けると「1局面 = 1行」で書き出す（ダミー用）。
  出力先を指定すると UTF-8・改行LF で書く（Windows PowerShell の「>」はUTF-16になるため、出力先の指定を推奨）。

他家の手牌は hidden_info に分離して入れる(実戦では見えない情報であることを明示するため)。
照合: 自分の手牌・副露が、レポートの表示と一致しない局面があれば、エラーで止まる。
"""
import json
import re
import sys
from bs4 import BeautifulSoup

import reconstruct_table_state as rts

REL_JA = {"self": "自分", "shimocha": "下家", "toimen": "対面", "kamicha": "上家"}
TILE_RE = r"\[([^\]]+)\]"
KYOKU_NAMES = ["東", "南", "西", "北"]


def cell_text_node(n):
    if getattr(n, "name", None) == "svg":
        return "[" + rts._tile_of(n) + "]"
    return re.sub(r"\s+", " ", n.get_text() if hasattr(n, "get_text") else str(n)).strip()


def cell_text(td):
    """td内の牌(svg)を [牌] に置き換えた文字列にする"""
    return " ".join(filter(None, (cell_text_node(n) for n in td.children)))


def parse_action(s, ctx):
    """行動の表記を構造化する。ctx は、その局面の状況（カンの種類の判定に使う）。
    'Discard [2m]' / 'Discard Riichi [4s]' / 'Skip' / 'Ron' / '[c] [c] Pon, cut [9s]' / 'Kan [w]'"""
    tiles = re.findall(TILE_RE, s)
    if s.startswith("Discard"):
        a = dict(type="discard", tile=tiles[0])
        if "Riichi" in s:
            a["riichi"] = True                   # 立直宣言つきの打牌
        return a
    if "Pon" in s:
        return dict(type="pon", with_tiles=tiles[:2], then_discard=tiles[-1])
    if "Chii" in s:
        return dict(type="chi", with_tiles=tiles[:2], then_discard=tiles[-1])
    if s.startswith("Kan"):
        t = tiles[0]
        if ctx["trigger"] == "opponent_discard":
            kind = "daiminkan"                   # 他家の打牌を鳴いてカン
        else:                                    # 自分のツモ番: 既にポンした牌なら加槓、そうでなければ暗槓
            kind = "kakan" if rts.base(t) in ctx["pon_tiles"] else "ankan"
        return dict(type=kind, tile=t)
    return dict(type=s.strip().lower())          # skip / ron / tsumo など


def num(td):
    t = td.get_text("", strip=True)
    try:
        return float(t)
    except ValueError:
        return None                               # 'N/A'


def entry_raw(e):
    """局面1件(details.entry) -> (自分の行動の文字列, AIの行動の文字列, 候補の行[(行動, pt_ev, 放銃率, 放銃後, 通過時)])"""
    ch = list(e.children)
    player = None
    for c in ch:
        if getattr(c, "name", None) == "span" and c.find("span", class_="role", recursive=False):
            r = c.find("span", class_="role")
            player = " ".join(filter(None, (cell_text_node(x) for x in c.children if x is not r)))
    role_idx = [i for i, c in enumerate(ch) if getattr(c, "name", None) == "span" and "role" in (c.get("class") or [])]
    det_idx = [i for i, c in enumerate(ch) if getattr(c, "name", None) == "details"][0]
    ai = " ".join(filter(None, (cell_text_node(x) for x in ch[role_idx[0] + 1:det_idx])))
    rows = []
    for tr in e.select("tbody > tr"):
        tds = tr.find_all("td", recursive=False)
        rows.append((cell_text(tds[0]), num(tds[1]), num(tds[2]), num(tds[3]), num(tds[4])))
    return player, ai, rows


def rel_melds(melds):
    """副露の出し元を『上家・対面・下家』に直す（自分から見た位置）。キー順: type, tiles, called, from"""
    out = []
    for m in melds:
        out.append(dict(type=m["type"], tiles=list(m["tiles"]), called=m["called"],
                        **{"from": REL_JA[m["from_rel"]] if m["from_rel"] is not None else None}))
    return out


def action_key(a):
    return json.dumps(a, sort_keys=True)


def build(html, viewer=None):
    soup = BeautifulSoup(html, "lxml")
    meta_h = rts.get_meta(soup)
    if viewer is None:
        viewer = int(meta_h.get("player id", 0))              # 自分の席（0〜3）
    engine = meta_h.get("AI engine", "Akochan")
    logs, groups = rts.load_kyoku_logs(soup), rts.report_groups(soup)
    if len(logs) != len(groups):
        raise ValueError(f"牌譜の局数({len(logs)})と、レポートの局見出し({len(groups)})が違います")

    result = []
    for (heading, ents), k in zip(groups, logs):
        rts.check_heading(heading, k)
        snaps, _ = rts.simulate(k, viewer)
        for ent in ents:
            where = f"{heading} Turn {ent['turn']} (×{ent['wall']})"
            snap = rts.match_snapshot(snaps, ent, viewer)
            by_rel = {p["rel"]: p for p in snap["players"]}
            me = by_rel["self"]

            # --- 照合: 復元した自分の手牌・副露が、レポートの表示と一致するか ---
            mine = snap["hands_hidden"][viewer] + ([snap["tile"]] if snap["kind"] == "cut" else [])
            if sorted(mine) != sorted(ent["closed"]):
                raise ValueError(f"{where}: 手牌が一致しません 復元={sorted(mine)} レポート={sorted(ent['closed'])}")
            if sorted(tuple(sorted(m["tiles"])) for m in me["melds"]) != sorted(tuple(sorted(f)) for f in ent["fuuro"]):
                raise ValueError(f"{where}: 副露が一致しません 復元={me['melds']} レポート={ent['fuuro']}")

            ctx = dict(trigger="draw" if snap["kind"] == "draw" else "opponent_discard",
                       pon_tiles={rts.base(m["tiles"][0]) for m in me["melds"] if m["type"] == "pon"})
            player_t, ai_t, rows = entry_raw(ent["tag"])
            player, ai = parse_action(player_t, ctx), parse_action(ai_t, ctx)
            cands = [dict(action=parse_action(a, ctx), pt_ev=pe, deal_in_pct=di, post_deal_in_pt_ev=pd, tile_passes_pt_ev=tp)
                     for a, pe, di, pd, tp in rows]
            if action_key(cands[0]["action"]) != action_key(ai):
                raise ValueError(f"{where}: AIの行動と、候補の1行目が一致しません {ai} / {cands[0]['action']}")
            ai_ev = cands[0]
            pl_ev = next((c for c in cands if action_key(c["action"]) == action_key(player)), None)
            pt_player = pl_ev["pt_ev"] if pl_ev else None        # Akochanが評価できなかった局面（表が N/A だけ）は null
            pt_ai = ai_ev["pt_ev"]
            if pl_ev is None and ai_ev["pt_ev"] is not None:
                raise ValueError(f"{where}: 自分の行動 {player} が候補にありません")

            others = {}
            for rel in ("shimocha", "toimen", "kamicha"):
                p = by_rel[rel]
                others[rel] = dict(
                    wind=p["wind"], is_dealer=p["is_dealer"], score=p["score"],
                    river=[dict(tile=r["tile"], tsumogiri=r["tsumogiri"], riichi=r["riichi"],
                                called_by=(REL_JA[r["called_by_rel"]] if r["called_by_rel"] is not None else None))
                           for r in p["river"]],
                    melds=rel_melds(p["melds"]), riichi=p["riichi"], genbutsu=p["genbutsu"],
                )
            kyoku_no = snap["kyoku_no"]
            result.append(dict(
                meta=dict(engine=engine, kyoku=f"{KYOKU_NAMES[kyoku_no // 4]}{kyoku_no % 4 + 1}局",
                          honba=snap["honba"], kyotaku=snap["kyotaku"], dora_indicators=snap["dora_indicators"]),
                situation=dict(turn=ent["turn"], wall_remaining=ent["wall"],
                               trigger=ctx["trigger"],
                               trigger_actor=REL_JA[rts.REL[rts.BEFORE_TO_REL[ent["before"]]]], trigger_tile=ent["focus_tile"]),
                self=dict(wind=me["wind"], is_dealer=me["is_dealer"], score=me["score"],
                          hand_with_trigger_tile=ent["closed"], melds=rel_melds(me["melds"]),
                          river=[dict(tile=r["tile"], tsumogiri=r["tsumogiri"], riichi=r["riichi"],
                                      called_by=(REL_JA[r["called_by_rel"]] if r["called_by_rel"] is not None else None))
                                 for r in me["river"]]),
                others=others,
                hidden_info=dict(
                    note="牌譜から復元した他家の手牌。実戦中は見えない情報。助言の根拠にする場合は『結果から見ると』と明示すること。",
                    hands={rel: snap["hands_hidden"][by_rel[rel]["seat"]] for rel in ("shimocha", "toimen", "kamicha")}),
                decision=dict(player_choice=player, ai_choice=ai,
                              loss=round(pt_ai - pt_player, 5) if pt_ai is not None and pt_player is not None else None,
                              player_pt_ev=pt_player, ai_pt_ev=pt_ai,
                              candidates=cands),
                commentary=None,
            ))
        print(f"[ok] {heading}: {len(ents)}局面", file=sys.stderr)
    return result


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    lines = "--lines" in sys.argv
    if not args:
        sys.exit("使い方: python build_ai_input.py <レポートHTML> [<出力先.json>] [--lines]")
    data = build(open(args[0], encoding="utf-8").read())
    if lines:      # 1局面 = 1行
        text = "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in data) + "\n]\n"
    else:
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if len(args) >= 2:
        with open(args[1], "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"{len(data)}局面を {args[1]} に書き出しました", file=sys.stderr)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(text)
