import logging
import os
import oci
from oci.generative_ai_agent_runtime import GenerativeAiAgentRuntimeClient
from oci.generative_ai_agent_runtime.models import ChatDetails, CreateSessionDetails

logger = logging.getLogger(__name__)

# AIエージェントのエンドポイントを入力
AGENT_ENDPOINT_OCID = "ocid1.genaiagentendpoint.oc1.ap-osaka-1.amaaaaaapimhcliaxbtu4ubtsaab7sydtcj4cut2aqdshdhtwpgirrqqqrwq"
REGION = "ap-osaka-1"

_cached_client = None


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


def _choice_to_str(choice: dict | str | None) -> str:
    if isinstance(choice, dict):
        action_type = choice.get("type", "")
        tile = _tile_ja(choice.get("tile", ""))
        acc = choice.get("acceptance")
        acc_str = ""
        if isinstance(acc, dict) and acc.get("remaining_count") is not None:
            sh_desc = acc.get("shanten_desc") or f"{acc.get('shanten', '')}向聴"
            acc_str = f" [{sh_desc} / 受け入れ{acc.get('remaining_count')}枚]"
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
    """新形式レコードまたは旧形式辞書をプロンプト埋め込み用の辞書に正規化する。"""
    if "meta" in rec and "decision" in rec:
        meta = rec.get("meta", {})
        sit = rec.get("situation", {})
        me = rec.get("self", {})
        others = rec.get("others", {})
        dec = rec.get("decision", {})

        kyoku_base = meta.get("kyoku", "不明")
        honba = meta.get("honba", 0)
        kyotaku = meta.get("kyotaku", 0)
        dora_ind = " ".join(_tile_ja(t) for t in meta.get("dora_indicators", [])) or "不明"
        kyoku_str = f"{kyoku_base} {honba}本場 (供託{kyotaku}本 / ドラ表示牌: {dora_ind})"

        turn_num = sit.get("turn", 0)
        trig = sit.get("trigger")
        trig_tile = _tile_ja(sit.get("trigger_tile"))
        if trig == "draw" and trig_tile:
            turn_str = f"{turn_num} (自摸: {trig_tile})"
        elif trig == "opponent_discard" and trig_tile:
            actor = sit.get("trigger_actor", "他家")
            turn_str = f"{turn_num} ({actor}の打牌: {trig_tile})"
        else:
            turn_str = str(turn_num)

        tehai_list = me.get("hand_with_trigger_tile", [])
        closed_str = " ".join(_tile_ja(str(t)) for t in tehai_list) if tehai_list else "不明"
        my_wind = WIND_JA.get(me.get("wind", ""), "")
        my_score = me.get("score")
        my_melds = _melds_to_str(me.get("melds", []))

        riichi_others = [
            f"{ rel_label }リーチ中"
            for rel_key, rel_label in REL_JA.items()
            if isinstance(others.get(rel_key), dict) and others[rel_key].get("riichi")
        ]
        riichi_info = f" / 他家: {', '.join(riichi_others)}" if riichi_others else ""

        tehai_full = f"{closed_str} （自家: {my_wind} {my_score}点 / 副露: {my_melds}{riichi_info}）"

        return {
            "kyoku": kyoku_str,
            "turn": turn_str,
            "tehai": tehai_full,
            "ai_discard": _choice_to_str(dec.get("ai_choice")),
            "ai_ev": dec.get("ai_pt_ev", 0.0) or 0.0,
            "player_discard": _choice_to_str(dec.get("player_choice")),
            "player_ev": dec.get("player_pt_ev", 0.0) or 0.0,
        }

    max_loss_turn = rec.get("max_loss_turn", rec)
    if not isinstance(max_loss_turn, dict):
        max_loss_turn = {}

    tehai_val = max_loss_turn.get("tehai", [])
    tehai_str = " ".join(str(t) for t in tehai_val) if isinstance(tehai_val, list) else str(tehai_val or "不明")

    return {
        "kyoku": max_loss_turn.get("kyoku", "不明"),
        "turn": max_loss_turn.get("turn", 0),
        "tehai": tehai_str,
        "ai_discard": max_loss_turn.get("ai_discard", "不明"),
        "ai_ev": max_loss_turn.get("ai_ev", 0.0),
        "player_discard": max_loss_turn.get("player_discard", "不明"),
        "player_ev": max_loss_turn.get("player_ev", 0.0),
    }


def _get_client_and_signer():
    """OCIクライアントを取得（初回のみ生成してキャッシュ）。InstancePrincipalsを優先し、無ければ ~/.oci/config を試す。"""
    global _cached_client
    if _cached_client is not None:
        return _cached_client

    try:
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        _cached_client = GenerativeAiAgentRuntimeClient(
            config={"region": REGION},
            signer=signer,
            service_endpoint=f"https://agent-runtime.generativeai.{REGION}.oci.oraclecloud.com"
        )
        return _cached_client
    except Exception:
        # ローカル環境の ~/.oci/config を試行
        config = oci.config.from_file()
        _cached_client = GenerativeAiAgentRuntimeClient(
            config=config,
            service_endpoint=f"https://agent-runtime.generativeai.{config.get('region', REGION)}.oci.oraclecloud.com"
        )
        return _cached_client


def _generate_advice(parsed_data=None) -> str | None:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_file_path = os.path.join(current_dir, "prompt.txt")
    with open(prompt_file_path, "r", encoding="utf-8") as f:
        template = f.read()

    fmt_values = _format_record(parsed_data or {})
    text = template.format(**fmt_values)

    try:
        client = _get_client_and_signer()

        # 1. セッション作成を試行（エンドポイント側でセッション無効の場合は session_id なしでチャット実行）
        session_id = None
        try:
            session_response = client.create_session(
                create_session_details=CreateSessionDetails(
                    display_name="mahjong-coaching-session",
                    description="mahjong coaching advice session"
                ),
                agent_endpoint_id=AGENT_ENDPOINT_OCID
            )
            session_id = session_response.data.id
        except Exception as session_err:
            print(f"[interactllm] create_session skipped/failed, trying sessionless chat: {session_err}", flush=True)

        # 2. チャット実行
        chat_kwargs = {"user_message": text}
        if session_id is not None:
            chat_kwargs["session_id"] = session_id

        chat_response = client.chat(
            agent_endpoint_id=AGENT_ENDPOINT_OCID,
            chat_details=ChatDetails(**chat_kwargs)
        )
        msg = getattr(chat_response.data, "message", None)
        content = getattr(msg, "content", None) if msg else None
        advice_text = getattr(content, "text", None) if content else None
        if not advice_text:
            print(f"[interactllm WARNING] Empty response from OCI GenAI: {chat_response.data}", flush=True)
        return advice_text
    except Exception as e:
        print(f"[interactllm ERROR] OCI GenAI advice generation failed: {type(e).__name__}: {e}", flush=True)
        logger.warning("OCI GenAI advice generation skipped or failed: %s", e)
        return None


