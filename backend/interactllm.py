import logging
import os
import oci
from oci.generative_ai_agent_runtime import GenerativeAiAgentRuntimeClient
from oci.generative_ai_agent_runtime.models import ChatDetails, CreateSessionDetails

logger = logging.getLogger(__name__)

# AIエージェントのエンドポイントを入力
AGENT_ENDPOINT_OCID = os.environ.get(
    "OCI_GENAI_AGENT_ENDPOINT_OCID",
    "ocid1.genaiagentendpoint.oc1.ap-osaka-1.amaaaaaapimhcliabtyh3wlwiyf7izkcn566uq6djbevsgryad5xd62y3kqq"
)
REGION = os.environ.get("OCI_REGION", "ap-osaka-1")


def _choice_to_str(choice: dict | str | None) -> str:
    if isinstance(choice, dict):
        action_type = choice.get("type", "")
        tile = choice.get("tile", "")
        if action_type == "discard":
            riichi = " 立直" if choice.get("riichi") else ""
            return f"打 {tile}{riichi}" if tile else "打牌"
        if action_type in ("pon", "chi"):
            with_tiles = "".join(choice.get("with_tiles", []))
            then_cut = f" 切 {choice.get('then_discard')}" if choice.get("then_discard") else ""
            return f"{action_type.capitalize()} ({with_tiles}){then_cut}"
        if action_type in ("daiminkan", "kakan", "ankan"):
            return f"{action_type} {tile}"
        return action_type
    return str(choice or "不明")


def _format_record(rec: dict) -> dict:
    """新形式レコードまたは旧形式辞書をプロンプト埋め込み用の辞書に正規化する。"""
    if "meta" in rec and "decision" in rec:
        meta = rec.get("meta", {})
        sit = rec.get("situation", {})
        me = rec.get("self", {})
        dec = rec.get("decision", {})

        tehai_list = me.get("hand_with_trigger_tile", [])
        tehai_str = " ".join(str(t) for t in tehai_list) if tehai_list else "不明"

        return {
            "kyoku": meta.get("kyoku", "不明"),
            "turn": sit.get("turn", 0),
            "tehai": tehai_str,
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


