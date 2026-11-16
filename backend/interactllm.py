import logging
import os
import oci
from oci.generative_ai_agent_runtime import GenerativeAiAgentRuntimeClient
from oci.generative_ai_agent_runtime.models import ChatDetails, CreateSessionDetails

logger = logging.getLogger(__name__)

# AIエージェントのエンドポイントを入力
AGENT_ENDPOINT_OCID = os.environ.get(
    "OCI_GENAI_AGENT_ENDPOINT_OCID",
    "ocid1.genaiagentendpoint.oc1.ap-osaka-1.amaaaaaapimhcliaxbtu4ubtsaab7sydtcj4cut2aqdshdhtwpgirrqqqrwq"
)
REGION = os.environ.get("OCI_REGION", "ap-osaka-1")


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
        if action_type == "discard":
            riichi = " 立直" if choice.get("riichi") else ""
            return f"打 {tile}{riichi}" if tile else "打牌"
        if action_type in ("pon", "chi"):
            with_tiles = " ".join(_tile_ja(t) for t in choice.get("with_tiles", []))
            then_cut = f" → 打 {_tile_ja(choice.get('then_discard'))}" if choice.get("then_discard") else ""
            label = "ポン" if action_type == "pon" else "チー"
            return f"{label} ({with_tiles}){then_cut}"
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
        my_river = " ".join(_tile_ja(r.get("tile")) for r in me.get("river", [])) or "なし"

        other_lines = []
        for rel_key, rel_label in REL_JA.items():
            o = others.get(rel_key)
            if not isinstance(o, dict):
                continue
            riichi_str = "【リーチ中】" if o.get("riichi") else "非リーチ"
            o_melds = _melds_to_str(o.get("melds", []))
            o_river = " ".join(_tile_ja(r.get("tile")) for r in o.get("river", [])) or "なし"
            other_lines.append(
                f"{rel_label}({o.get('score', '?')}点, {riichi_str}, 副露: {o_melds}, 河: {o_river})"
            )

        tehai_full = (
            f"{closed_str} "
            f"（自家: {my_wind} {my_score}点 / 自分の副露: {my_melds} / 自分の河: {my_river}"
            + (f" / 他家状況: {' | '.join(other_lines)}" if other_lines else "")
            + "）"
        )

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
    """OCIクライアントを取得。InstancePrincipalsを優先し、無ければ ~/.oci/config を試す。"""
    try:
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        client = GenerativeAiAgentRuntimeClient(
            config={"region": REGION},
            signer=signer,
            service_endpoint=f"https://agent-runtime.generativeai.{REGION}.oci.oraclecloud.com"
        )
        return client
    except Exception:
        # ローカル環境の ~/.oci/config を試行
        config = oci.config.from_file()
        client = GenerativeAiAgentRuntimeClient(
            config=config,
            service_endpoint=f"https://agent-runtime.generativeai.{config.get('region', REGION)}.oci.oraclecloud.com"
        )
        return client


def _generate_advice(parsed_data=None) -> str | None:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_file_path = os.path.join(current_dir, "prompt.txt")
    with open(prompt_file_path, "r", encoding="utf-8") as f:
        template = f.read()

    fmt_values = _format_record(parsed_data or {})
    text = template.format(**fmt_values)

    try:
        client = _get_client_and_signer()

        # 1. セッション作成
        session_response = client.create_session(
            create_session_details=CreateSessionDetails(
                display_name="mahjong-coaching-session",
                description="mahjong coaching advice session"
            ),
            agent_endpoint_id=AGENT_ENDPOINT_OCID
        )
        session_id = session_response.data.id

        # 2. チャット実行
        chat_response = client.chat(
            agent_endpoint_id=AGENT_ENDPOINT_OCID,
            chat_details=ChatDetails(
                user_message=text,
                session_id=session_id
            )
        )
        return chat_response.data.message.content.text
    except Exception as e:
        logger.warning("OCI GenAI advice generation skipped or failed: %s", e)
        return None


