import os
import oci
from oci.generative_ai_agent_runtime import GenerativeAiAgentRuntimeClient
from oci.generative_ai_agent_runtime.models import ChatDetails, CreateSessionDetails

# AIエージェントのエンドポイントを入力
AGENT_ENDPOINT_OCID = "ocid1.genaiagentendpoint.oc1.ap-osaka-1.amaaaaaapimhcliabtyh3wlwiyf7izkcn566uq6djbevsgryad5x62y3kqq"
REGION = "ap-osaka-1"

def _generate_advice(parsed_data=None) -> str:
    # プロンプトはprompt.txtで受け取る
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_file_path = os.path.join(current_dir, "prompt.txt")
    with open(prompt_file_path, "r", encoding="utf-8") as f:
        template = f.read()

    if parsed_data is None:
        parsed_data = {}

    max_loss_turn = parsed_data.get("max_loss_turn") if isinstance(parsed_data, dict) else None
    if max_loss_turn is None and isinstance(parsed_data, dict):
        max_loss_turn = parsed_data

    if not isinstance(max_loss_turn, dict):
        max_loss_turn = {}

    tehai_val = max_loss_turn.get("tehai", [])
    if isinstance(tehai_val, list):
        tehai_str = " ".join(str(t) for t in tehai_val) if tehai_val else "不明"
    else:
        tehai_str = str(tehai_val) if tehai_val else "不明"

    fmt_values = {
        "kyoku": max_loss_turn.get("kyoku", "不明"),
        "turn": max_loss_turn.get("turn", 0),
        "tehai": tehai_str,
        "ai_discard": max_loss_turn.get("ai_discard", "不明"),
        "ai_ev": max_loss_turn.get("ai_ev", 0.0),
        "player_discard": max_loss_turn.get("player_discard", "不明"),
        "player_ev": max_loss_turn.get("player_ev", 0.0),
    }

    text = template.format(**fmt_values)

    signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()

    client = GenerativeAiAgentRuntimeClient(
        config={"region": REGION},
        signer=signer,
        service_endpoint=f"https://agent-runtime.generativeai.{REGION}.oci.oraclecloud.com"
    )

    # 1. セッション作成
    session_response = client.create_session(
        create_session_details=CreateSessionDetails(
            display_name="test-session",
            description="python sdk test session"
        ),
        agent_endpoint_id=AGENT_ENDPOINT_OCID
    )

    # Session モデルの id を利用
    session_id = session_response.data.id

    # 2. チャット実行
    chat_response = client.chat(
        agent_endpoint_id=AGENT_ENDPOINT_OCID,
        chat_details=ChatDetails(
            user_message=text,
            session_id=session_id
        )
    )

    # AIエージェントのアドバイス
    return chat_response.data.message.content.text


