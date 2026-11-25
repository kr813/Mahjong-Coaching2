import json
import logging
import os
import re
from functools import lru_cache

import oci
from oci.generative_ai_agent_runtime import GenerativeAiAgentRuntimeClient
from oci.generative_ai_agent_runtime.models import ChatDetails, CreateSessionDetails

logger = logging.getLogger(__name__)

DEFAULT_AGENT_ENDPOINT_OCID = "ocid1.genaiagentendpoint.oc1.ap-osaka-1.amaaaaaapimhcliaxbtu4ubtsaab7sydtcj4cut2aqdshdhtwpgirrqqqrwq"
ADVICE_END_MARKER = "[[ADVICE_COMPLETE]]"


HONOR_JA = {"e": "東", "s": "南", "w": "西", "n": "北", "p": "白", "f": "發", "c": "中"}
SUIT_JA = {"m": "萬", "p": "筒", "s": "索"}
WIND_JA = {"east": "東家", "south": "南家", "west": "西家", "north": "北家"}
REL_JA = {"shimocha": "下家", "toimen": "対面", "kamicha": "上家"}


def _tile_ja(code: str | None) -> str:
    if not code:
        return ""
    if code in HONOR_JA:
        return HONOR_JA[code]
    if len(code) == 3 and code.endswith("r") and code[1] in SUIT_JA:
        return f"赤{code[0]}{SUIT_JA[code[1]]}"
    if len(code) == 2 and code[0].isdigit() and code[1] in SUIT_JA:
        return f"{code[0]}{SUIT_JA[code[1]]}"
    return str(code)


def _acceptance_to_str(acc: dict | None) -> str:
    if not isinstance(acc, dict) or acc.get("remaining_count") is None:
        return "なし"
    sh_desc = acc.get("shanten_desc") or f"{acc.get('shanten', '')}向聴"
    rem_total = acc.get("remaining_count", 0)
    details = acc.get("details", [])
    if details:
        breakdown_parts = [f"{_tile_ja(d['tile'])}:{d.get('remaining', 0)}枚" for d in details]
        breakdown_str = f" [内訳: {', '.join(breakdown_parts)}]"
    elif acc.get("tiles"):
        tiles_str = ", ".join(_tile_ja(t) for t in acc["tiles"])
        breakdown_str = f" [有効牌: {tiles_str}]"
    else:
        breakdown_str = ""
    return f"{sh_desc}（受け入れ: {rem_total}枚{breakdown_str}）"


def _choice_to_str(choice: dict | str | None) -> str:
    if isinstance(choice, dict):
        action_type = choice.get("type", "")
        tile = _tile_ja(choice.get("tile", ""))
        acc = choice.get("acceptance")
        acc_str = ""
        if isinstance(acc, dict) and acc.get("remaining_count") is not None:
            sh_desc = acc.get("shanten_desc") or f"{acc.get('shanten', '')}向聴"
            rem = acc.get("remaining_count", 0)
            details = acc.get("details", [])
            if details:
                parts = [f"{_tile_ja(d['tile'])}:{d.get('remaining', 0)}枚" for d in details]
                acc_str = f" [{sh_desc} / 受け入れ{rem}枚: {', '.join(parts)}]"
            else:
                acc_str = f" [{sh_desc} / 受け入れ{rem}枚]"
        if action_type == "discard":
            riichi = " 立直" if choice.get("riichi") else ""
            res = f"打 {tile}{riichi}" if tile else "打牌"
            return f"{res}{acc_str}"
        if action_type in ("pon", "chi"):
            with_tiles = " ".join(_tile_ja(t) for t in choice.get("with_tiles", []))
            then_cut = f" → 打 {_tile_ja(choice.get('then_discard'))}" if choice.get("then_discard") else ""
            label = "ポン" if action_type == "pon" else "チー"
            return f"{label} ({with_tiles}){then_cut}{acc_str}"
        if action_type in ("daiminkan", "kakan", "ankan"):
            label = {"daiminkan": "大明槓", "kakan": "加槓", "ankan": "暗槓"}[action_type]
            return f"{label} {tile}"
        if action_type == "skip":
            return "スルー (鳴かない)"
        if action_type == "ron":
            return "ロン"
        if action_type == "tsumo":
            return "ツモ"
        return action_type
    return str(choice or "不明")


def _melds_to_str(melds: list[dict]) -> str:
    if not melds:
        return "なし(門前)"
    parts = []
    for m in melds:
        tiles = " ".join(_tile_ja(t) for t in m.get("tiles", []))
        mtype = {"pon": "ポン", "chi": "チー", "daiminkan": "大明槓", "kakan": "加槓", "ankan": "暗槓"}.get(
            m.get("type", ""), m.get("type", "副露")
        )
        parts.append(f"{mtype}[{tiles}]")
    return " / ".join(parts)


def _format_record(rec: dict) -> dict:
    """新形式レコードまたは旧形式辞書をOCI に送信する局面データに正規化する。"""
    if "meta" in rec and "decision" in rec:
        meta = rec.get("meta", {})
        sit = rec.get("situation", {})
        me = rec.get("self", {})
        others = rec.get("others", {})
        dec = rec.get("decision", {})

        kyoku_base = meta.get("kyoku", "不明")
        honba = meta.get("honba", 0)
        kyotaku = meta.get("kyotaku", 0)
        kyoku_str = f"{kyoku_base} {honba}本場 (供託{kyotaku}本)"
        dora_str = " ".join(_tile_ja(t) for t in meta.get("dora_indicators", [])) or "不明"

        turn_num = sit.get("turn", 0)
        wall_rem = sit.get("wall_remaining")
        wall_str = f"{wall_rem}枚" if wall_rem is not None else "不明"
        trig = sit.get("trigger")
        trig_tile = _tile_ja(sit.get("trigger_tile"))
        if trig == "draw" and trig_tile:
            trig_str = f"自摸: {trig_tile}"
        elif trig == "opponent_discard" and trig_tile:
            actor = sit.get("trigger_actor", "他家")
            trig_str = f"{actor}の打牌: {trig_tile}"
        else:
            trig_str = "なし"

        # 自家情報
        my_wind = WIND_JA.get(me.get("wind", ""), "不明")
        dealer_str = "親" if me.get("is_dealer") else "子"
        my_score = me.get("score")
        score_str = f"{my_score}点" if my_score is not None else ""
        self_info_str = f"{my_wind}({dealer_str}) {score_str}".strip()

        # 手牌・副露
        tehai_list = me.get("hand_with_trigger_tile", [])
        closed_str = " ".join(_tile_ja(str(t)) for t in tehai_list) if tehai_list else "不明"
        my_melds_str = _melds_to_str(me.get("melds", []))

        # 他家の状況
        others_parts = []
        for rel_k, rel_label in REL_JA.items():
            if isinstance(others.get(rel_k), dict):
                op = others[rel_k]
                o_wind = WIND_JA.get(op.get("wind", ""), "")
                o_score = f"{op.get('score')}点" if op.get("score") is not None else ""
                o_riichi = " [立直中]" if op.get("riichi") else ""
                o_melds = _melds_to_str(op.get("melds", []))
                others_parts.append(f"{rel_label}({o_wind} {o_score}{o_riichi} / 副露: {o_melds})")
        others_str = " / ".join(others_parts) if others_parts else "情報なし"

        pl_choice_str = _choice_to_str(dec.get("player_choice"))
        pl_ev = dec.get("player_pt_ev")
        pl_ev_str = f"{pl_ev:.5f}" if isinstance(pl_ev, (int, float)) else "算出不可"

        ai_choice_str = _choice_to_str(dec.get("ai_choice"))
        ai_ev = dec.get("ai_pt_ev")
        ai_ev_str = f"{ai_ev:.5f}" if isinstance(ai_ev, (int, float)) else "算出不可"

        loss_val = dec.get("loss")
        loss_str = f"{abs(loss_val):.5f}" if isinstance(loss_val, (int, float)) else "算出不可"

        pl_acc_str = _acceptance_to_str(dec.get("player_choice", {}).get("acceptance") if isinstance(dec.get("player_choice"), dict) else None)
        ai_acc_str = _acceptance_to_str(dec.get("ai_choice", {}).get("acceptance") if isinstance(dec.get("ai_choice"), dict) else None)

        return {
            "kyoku": kyoku_str,
            "dora": dora_str,
            "turn": str(turn_num),
            "wall_remaining": wall_str,
            "trigger_info": trig_str,
            "self_info": self_info_str,
            "tehai": closed_str,
            "my_melds": my_melds_str,
            "others_info": others_str,
            "ai_discard": ai_choice_str,
            "ai_ev": ai_ev_str,
            "ai_acceptance": ai_acc_str,
            "player_discard": pl_choice_str,
            "player_ev": pl_ev_str,
            "player_acceptance": pl_acc_str,
            "loss": loss_str,
        }

    max_loss_turn = rec.get("max_loss_turn", rec)
    if not isinstance(max_loss_turn, dict):
        max_loss_turn = {}

    tehai_val = max_loss_turn.get("tehai", [])
    tehai_str = " ".join(str(t) for t in tehai_val) if isinstance(tehai_val, list) else str(tehai_val or "不明")

    return {
        "kyoku": max_loss_turn.get("kyoku", "不明"),
        "dora": "不明",
        "turn": str(max_loss_turn.get("turn", 0)),
        "wall_remaining": "不明",
        "trigger_info": "不明",
        "self_info": "不明",
        "tehai": tehai_str,
        "my_melds": "なし",
        "others_info": "情報なし",
        "ai_discard": max_loss_turn.get("ai_discard", "不明"),
        "ai_ev": str(max_loss_turn.get("ai_ev", 0.0)),
        "ai_acceptance": "なし",
        "player_discard": max_loss_turn.get("player_discard", "不明"),
        "player_ev": str(max_loss_turn.get("player_ev", 0.0)),
        "player_acceptance": "なし",
        "loss": "不明",
    }


@lru_cache(maxsize=1)
def _get_client_and_signer(region: str):
    """Instance Principals を優先し、認証できなければ ~/.oci/config を使う。"""
    try:
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    except Exception:
        config = {**oci.config.from_file(), "region": region}
        return GenerativeAiAgentRuntimeClient(config=config)
    return GenerativeAiAgentRuntimeClient(config={"region": region}, signer=signer)


def _request_advice(client, endpoint_id: str, situation: dict, response_profile: str) -> tuple[str, bool]:
    user_message = json.dumps(
        {"situation": situation, "response_profile": response_profile},
        ensure_ascii=False,
    )
    chat_kwargs = {"user_message": user_message, "should_stream": False}
    # 各試行を独立させ、前の応答が再生成に混ざらないようにする。
    try:
        session = client.create_session(
            create_session_details=CreateSessionDetails(
                display_name="mahjong-coaching-session",
                description="mahjong coaching advice session",
            ),
            agent_endpoint_id=endpoint_id,
        )
        if session.data.id:
            chat_kwargs["session_id"] = session.data.id
    except Exception as exc:
        logger.info("OCI session creation failed; using sessionless chat (%s)", type(exc).__name__)

    response = client.chat(
        agent_endpoint_id=endpoint_id,
        chat_details=ChatDetails(**chat_kwargs),
    )
    message = getattr(response.data, "message", None)
    content = getattr(message, "content", None)
    advice = getattr(content, "text", None) or ""
    body, separator, last_line = advice.rstrip().rpartition("\n")
    has_marker = last_line.strip() == ADVICE_END_MARKER
    text = (body if has_marker else advice).strip()
    if separator and has_marker and text:
        return text, True

    logger.warning(
        "OCI advice missing a completed body (profile=%s, chars=%d, request_id=%s)",
        response_profile,
        len(advice),
        response.headers.get("opc-request-id") if response.headers else None,
    )
    return text, False


def _generate_advice(parsed_data=None) -> str | None:
    standard = ""
    try:
        situation = _format_record(parsed_data or {})
        endpoint_id = os.getenv("OCI_AGENT_ENDPOINT_OCID", "").strip() or DEFAULT_AGENT_ENDPOINT_OCID
        version, resource, _realm, region, identifier = endpoint_id.split(".", 4)
        if (
            version != "ocid1"
            or resource != "genaiagentendpoint"
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", region)
            or not identifier
        ):
            raise ValueError("Invalid OCI_AGENT_ENDPOINT_OCID")
        client = _get_client_and_signer(region)
        standard, complete = _request_advice(client, endpoint_id, situation, "standard")
        if complete:
            return standard
        compact, complete = _request_advice(client, endpoint_id, situation, "compact")
        if complete:
            return compact
        return standard or compact or None
    except Exception as exc:
        logger.warning(
            "OCI advice generation failed (type=%s, status=%s, request_id=%s)",
            type(exc).__name__,
            getattr(exc, "status", None),
            getattr(exc, "request_id", None),
        )
        return standard or None
