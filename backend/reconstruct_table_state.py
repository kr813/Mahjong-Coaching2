"""
reconstruct_table_state.py

mjai-reviewer のレポートHTMLに埋め込まれている天鳳形式JSON(tenhou.net/6 JSON log)から、
各局面の「河・副露・他家の状況・他家の手牌」を復元し、レポート内の各エントリ(局面)に紐付ける。

対応:
  * 複数局（局ごとに牌譜JSONが付く。1局ごとに <textarea> が1つ）
  * 自分の席が0以外（メタデータの player id）。席は「自分から見た相対位置」で扱う
  * チー・ポン・大明槓・加槓・暗槓・リーチ
  * カンドラの表示（カンのたびに増える）、リーチ棒（持ち点と供託）

使い方:
    python3 reconstruct_table_state.py report.html > table_state.json   (照合結果は標準エラーに出る)

注意:
  * 復元できるのは「牌譜に残っている事実」。他家の手牌(hands_hidden)は実戦では見えない情報。
  * 未対応: 流局時の処理、ダブロン、抜きドラ（三麻）、包(パオ)。
"""
import json
import re
import sys
from bs4 import BeautifulSoup

REL = {0: "self", 1: "shimocha", 2: "toimen", 3: "kamicha"}   # 視点(自分)から見た相対位置
WINDS = ["east", "south", "west", "north"]
HONORS = {41: "e", 42: "s", 43: "w", 44: "n", 45: "p", 46: "f", 47: "c"}  # 東南西北 白發中
REDS = {51: "5mr", 52: "5pr", 53: "5sr"}
KYOKU_WIND = {"East": 0, "South": 1, "West": 2, "North": 3}


def tile(n):
    """天鳳の牌番号 -> mjai表記 (例: 53 -> '5sr', 47 -> 'c')"""
    n = int(n)
    if n in REDS:
        return REDS[n]
    if n in HONORS:
        return HONORS[n]
    return f"{n % 10}{'mps'[n // 10 - 1]}"


def base(code):
    """赤5を通常の5に揃える ('5pr' -> '5p')"""
    return code[:-1] if len(code) == 3 and code.endswith("r") else code


def parse_meld(s, me):
    """天鳳の鳴き文字列を解釈する。me はその文字列を持つ席。
    例: '4747p47' -> 中のポン(下家から) / '434343m43' -> 大明槓 / '4242k4242' -> 加槓 / 'c262728' -> チー
    戻り値の from_ は「出し元の席(絶対)」。"""
    toks = re.findall(r"[a-z]|\d{2}", s)
    kind = next(t for t in toks if t.isalpha())
    pos = toks.index(kind)
    nums = [int(t) for t in toks if t.isdigit()]
    codes = [tile(x) for x in nums]
    if kind == "c":                       # チー: 先頭が鳴いた牌、常に上家から
        return dict(type="chi", tiles=codes, called=codes[0], from_=(me + 3) % 4)
    if kind == "p":                       # ポン: pの位置で出し元が決まる (0:上家 1:対面 2:下家)
        return dict(type="pon", tiles=codes, called=codes[pos], from_=(me + {0: 3, 1: 2, 2: 1}[pos]) % 4)
    if kind == "m":                       # 大明槓 (0:上家 1:対面 3:下家)
        return dict(type="daiminkan", tiles=codes, called=codes[pos], from_=(me + {0: 3, 1: 2, 3: 1}[pos]) % 4)
    if kind == "k":                       # 加槓: kの位置は元のポンの鳴き位置。最後の牌が加えた牌
        return dict(type="kakan", tiles=codes, called=codes[pos], from_=(me + {0: 3, 1: 2, 2: 1}[pos]) % 4, added=codes[-1])
    if kind == "a":                       # 暗槓
        return dict(type="ankan", tiles=codes, called=None, from_=None)
    raise ValueError(s)


# ---------------- レポートHTMLの読み取り ----------------
def get_meta(soup):
    """メタデータ欄 -> {'AI engine': 'Akochan', 'player id': '2', ...}"""
    for summary in soup.find_all("summary"):
        if summary.get_text(strip=True) in ("Metadata", "メタデータ"):
            dl = summary.parent.find("dl")
            if dl is not None:
                return {dt.get_text(strip=True): dd.get_text(strip=True) for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd"))}
    return {}


def load_kyoku_logs(soup):
    """全 <textarea> の天鳳JSONから、局ごとの記録(log[i])を出現順に集める"""
    logs = []
    for ta in soup.find_all("textarea"):
        game = json.loads(ta.get_text())
        logs.extend(game["log"])
    return logs


def load_log(html):
    """(先頭の牌譜JSON, soup)。単独局向けの旧インターフェース"""
    soup = BeautifulSoup(html, "lxml")
    return json.loads(soup.find("textarea").get_text()), soup


def check_heading(heading, k):
    """局見出し(例 'East 2-1 Tsumo by ...')が、牌譜の局・本場と一致するか確認する"""
    m = re.match(r"(East|South|West|North)\s+(\d)(?:-(\d+))?", heading.replace("\xa0", " "))
    if not m:
        raise ValueError(f"局見出しを解釈できません: {heading!r}")
    kyoku_no = KYOKU_WIND[m.group(1)] * 4 + int(m.group(2)) - 1
    honba = int(m.group(3) or 0)
    if [kyoku_no, honba] != [k[0][0], k[0][1]]:
        raise ValueError(f"局見出し {heading!r} と牌譜の局 {k[0]} が一致しません")


def _tile_of(svg):
    return svg.find("use").get("href").replace("#pai-", "")


def _parse_entry(e):
    m = re.match(r"Turn (\d+) \(×(\d+)\)\s*(.*)", e.find("summary").get_text(" ", strip=True))
    lis = e.find("ul", class_="tehai-state").find_all("li", recursive=False)
    closed, trig, fuuro = [], None, []
    for li in lis:
        cls = li.get("class") or []
        if "fuuro" in cls:
            fuuro.append([_tile_of(s) for s in li.find_all("svg")])
        else:
            closed.append(_tile_of(li.find("svg")))
            if "tsumo" in cls:
                trig = (_tile_of(li.find("svg")), (li.get("before") or "").strip())
    return dict(tag=e, turn=int(m.group(1)), wall=int(m.group(2)), mark=m.group(3) or None,
                closed=closed, fuuro=fuuro, focus_tile=trig[0] if trig else None, before=trig[1] if trig else None,
                mark_red=e.has_attr("data-mark-red"))


def report_groups(soup):
    """レポートの局面を、局見出しごとにまとめる -> [(見出し, [entry, ...]), ...]（出現順）"""
    groups = []
    for el in soup.find_all(["h1", "details"]):
        classes = el.get("class") or []
        if el.name == "h1" and "kyoku-heading" in classes:
            groups.append((el.get_text(" ", strip=True), []))
        elif el.name == "details" and "entry" in classes:
            if not groups:
                raise ValueError("局見出しより前に局面があります")
            groups[-1][1].append(_parse_entry(el))
    return groups


BEFORE_TO_REL = {"Draw": 0, "Shimocha👉 cuts": 1, "Toimen👆 cuts": 2, "Kamicha👈 cuts": 3}   # 自分から見た相対位置


# ---------------- 1局の再現 ----------------
def simulate(k, viewer=0):
    """1局分の牌譜 k = game["log"][i] を1手ずつ進めて、viewer(自分の席)の判断局面ごとの卓の状況を返す。
    戻り値: (snaps, final)  final は終局時の状態(照合用)"""
    kyoku_no, honba, kyotaku = k[0]
    scores, dora_all = list(k[1]), k[2]
    dealer = kyoku_no % 4
    hands = {p: [int(x) for x in k[4 + 3 * p]] for p in range(4)}
    draws = {p: k[5 + 3 * p] for p in range(4)}
    discs = {p: k[6 + 3 * p] for p in range(4)}
    dp = {p: 0 for p in range(4)}
    xp = {p: 0 for p in range(4)}
    rivers = {p: [] for p in range(4)}
    melds = {p: [] for p in range(4)}
    riichi = {p: None for p in range(4)}       # リーチ宣言牌が自分の河の何枚目か
    riichi_paid = set()                        # リーチ棒を払い終えた席（宣言牌が通ったあと）
    wall = 70                                  # 136 - 配牌52 - 王牌14
    dora_n, pending_dora = 1, 0                # 表示中のドラ表示牌の数 / 大明槓・加槓で次の打牌後に増える分
    pending_riichi = None
    snaps = []
    rel = lambda seat: REL[(seat - viewer) % 4]

    def snapshot(kind, actor, t):
        players = []
        for p in range(4):
            players.append(dict(
                seat=p, rel=rel(p), wind=WINDS[(p - dealer) % 4], is_dealer=(p == dealer),
                score=scores[p] - (1000 if p in riichi_paid else 0),
                river=[dict(r, called_by_rel=(rel(r["called_by"]) if r["called_by"] is not None else None)) for r in rivers[p]],
                melds=[dict(m, from_rel=(rel(m["from_"]) if m["from_"] is not None else None)) for m in melds[p]],
                riichi=riichi[p] is not None,
                genbutsu=sorted({r["tile"] for r in rivers[p]}),
                closed_hand_count=len(hands[p]),
            ))
        snaps.append(dict(
            kind=kind, actor=actor, tile=tile(t), wall_remaining=wall, viewer=viewer,
            kyoku_no=kyoku_no, honba=honba, kyotaku=kyotaku + len(riichi_paid),
            dora_indicators=[tile(x) for x in dora_all[:dora_n]],
            players=players,
            hands_hidden={p: sorted(tile(x) for x in hands[p]) for p in range(4)},
        ))

    def remove_tiles(seat, codes):
        for c in codes:
            hands[seat].remove(next(x for x in hands[seat] if tile(x) == c))

    cur, need_draw = dealer, True
    while True:
        if need_draw:
            if dp[cur] >= len(draws[cur]):
                break
            item = draws[cur][dp[cur]]
            if isinstance(item, str):
                raise ValueError("想定外: 手番の頭に鳴き文字列")
            dp[cur] += 1
            wall -= 1                                        # 嶺上牌も、生牌山の残りを1枚減らす
            hands[cur].append(item)
            drawn = item
            if cur == viewer:
                snapshot("draw", cur, item)
        else:
            drawn = None
        need_draw = True

        if xp[cur] >= len(discs[cur]):
            break                                            # ツモ和了など
        d = discs[cur][xp[cur]]
        xp[cur] += 1
        is_riichi = False
        if isinstance(d, str):
            m = re.fullmatch(r"r(\d+)", d)
            if m:                                            # リーチ宣言牌
                is_riichi, d = True, int(m.group(1))
            else:                                            # 暗槓 / 加槓（打牌の欄に出る）→ 次に嶺上牌をツモる
                meld = parse_meld(d, cur)
                if meld["type"] == "ankan":
                    remove_tiles(cur, meld["tiles"])
                    melds[cur].append(meld)
                    dora_n += 1                              # 暗槓のカンドラは、すぐに表示される
                else:                                        # 加槓: 元のポンを4枚の面子にする
                    pon = next(x for x in melds[cur] if x["type"] == "pon" and base(x["tiles"][0]) == base(meld["called"]))
                    remove_tiles(cur, [meld["added"]])
                    pon.update(type="kakan", tiles=meld["tiles"], added=meld["added"])
                    pending_dora += 1                        # 加槓のカンドラは、次の打牌のあとに表示される
                continue
        tsumogiri = (d == 60)
        t = drawn if tsumogiri else d
        hands[cur].remove(t)
        rivers[cur].append(dict(tile=tile(t), tsumogiri=tsumogiri, riichi=is_riichi, called_by=None))
        if is_riichi and riichi[cur] is None:
            riichi[cur] = len(rivers[cur])
            pending_riichi = cur
        if cur != viewer:
            snapshot("cut", cur, t)                          # 自分の鳴き/ロン判断の局面

        caller = None
        for off in (1, 2, 3):                                # 次の誰かの「ツモ欄」が鳴き文字列なら鳴き成立
            c = (cur + off) % 4
            if dp[c] < len(draws[c]) and isinstance(draws[c][dp[c]], str):
                mm = parse_meld(draws[c][dp[c]], c)
                if mm["from_"] == cur and mm["called"] == tile(t):
                    caller, meld = c, mm
                    break
        if pending_riichi is not None:                       # リーチ宣言牌が通った → リーチ棒を払う
            riichi_paid.add(pending_riichi)
            pending_riichi = None
        dora_n += pending_dora                               # 大明槓・加槓のカンドラ（打牌のあとに表示）
        pending_dora = 0
        if caller is None:
            cur = (cur + 1) % 4
            continue
        dp[caller] += 1
        rivers[cur][-1]["called_by"] = caller
        used = list(meld["tiles"])
        used.remove(meld["called"])                          # 手牌から抜くのは「鳴いた牌以外」
        remove_tiles(caller, used)
        melds[caller].append(meld)
        if meld["type"] == "daiminkan":                      # 大明槓: 打牌欄の0を読み飛ばし、嶺上牌をツモる
            if xp[caller] < len(discs[caller]) and discs[caller][xp[caller]] == 0:
                xp[caller] += 1
            pending_dora += 1
            cur, need_draw = caller, True
        else:                                                # チー・ポン: ツモらずに打牌する
            cur, need_draw = caller, False

    final = dict(hands={p: sorted(tile(x) for x in hands[p]) for p in range(4)}, melds=melds,
                 dp=dp, xp=xp, draws={p: len(draws[p]) for p in range(4)}, discs={p: len(discs[p]) for p in range(4)},
                 dora_shown=dora_n + pending_dora, dora_in_log=len(dora_all), wall=wall, rivers=rivers)
    return snaps, final


def match_snapshot(snaps, ent, viewer):
    """レポートの局面(ent)に対応する、復元した卓の状況を1つ選ぶ（山の残り枚数・誰の牌か・その牌）"""
    actor = (viewer + BEFORE_TO_REL[ent["before"]]) % 4
    cand = [s for s in snaps if s["wall_remaining"] == ent["wall"] and s["actor"] == actor and s["tile"] == ent["focus_tile"]]
    if len(cand) != 1:
        raise ValueError(f"局面 Turn {ent['turn']} (×{ent['wall']}) に対応する卓の状況が{len(cand)}件あります")
    return cand[0]


def main(path):
    html = open(path, encoding="utf-8").read()
    soup = BeautifulSoup(html, "lxml")
    meta = get_meta(soup)
    viewer = int(meta.get("player id", 0))
    logs, groups = load_kyoku_logs(soup), report_groups(soup)
    if len(logs) != len(groups):
        raise ValueError(f"牌譜の局数({len(logs)})と、レポートの局見出し({len(groups)})が違います")
    out, bad = [], 0
    for (heading, ents), k in zip(groups, logs):
        check_heading(heading, k)
        snaps, final = simulate(k, viewer)
        for ent in ents:
            snap = match_snapshot(snaps, ent, viewer)
            mine = snap["hands_hidden"][viewer] + ([snap["tile"]] if snap["kind"] == "cut" else [])
            ok = sorted(mine) == sorted(ent["closed"])
            bad += (not ok)
            out.append(dict(kyoku=heading, entry={k2: v for k2, v in ent.items() if k2 != "tag"}, table=snap))
    print(f"[check] 局{len(groups)}・局面{len(out)}件中 手牌の不一致 {bad}件（自分の席: {viewer}）", file=sys.stderr)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main(sys.argv[1])
