from __future__ import annotations
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

import build_ai_input
from build_report import worst_ranks
import interactakochan
import interactllm

logger = logging.getLogger(__name__)

# この値以上の期待値差がある判断だけを「要注意」とし、LLMのコメントを付ける
EV_DIFF_THRESHOLD = 0.15


def write_temp_file(suffix: str, content: bytes) -> Path:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        tf.write(content)
        return Path(tf.name)


def remove_file(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except OSError:
        pass


def run_analysis(
    source_type: str,
    seat: int = 0,
    url: str | None = None,
    file_content: bytes | None = None,
    json_body: bytes | None = None,
    generate_advice: bool = True,
) -> list[dict[str, Any]]:
    """牌譜解析を実行し、指定された新形式JSON（局面オブジェクトの配列）を返す。"""
    temp_input_path = None
    try:
        if source_type == "url":
            if not url:
                raise ValueError("query parameter 'url' is required for source_type=url")
            report_html = interactakochan.call_report(source_type="url", url=url, seat=seat)
        elif source_type == "file":
            if not file_content:
                raise ValueError("file upload is required for source_type=file")
            try:
                json.loads(file_content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise ValueError("アップロードされたファイルが正しいJSON形式ではありません。") from e
            temp_input_path = write_temp_file(".json", file_content)
            report_html = interactakochan.call_report(source_type="file", file_path=str(temp_input_path), seat=seat)
        elif source_type == "json":
            if not json_body:
                raise ValueError("JSON body is required for source_type=json")
            try:
                json.loads(json_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise ValueError("入力されたデータが正しいJSON形式ではありません。") from e
            temp_input_path = write_temp_file(".json", json_body)
            report_html = interactakochan.call_report(source_type="json", json_path=str(temp_input_path), seat=seat)
        else:
            raise ValueError("source_type must be one of json, file, url")

        # HTML レポートから新形式の局面一覧（ai-input-format仕様）を生成
        records = build_ai_input.build(report_html, viewer=seat)
        if not records:
            raise ValueError("No analysable report entries were found.")

        # 期待値差が大きい順ワースト5の判断にのみLLMアドバイスを生成してcommentaryに付与
        if generate_advice:
            ranks = worst_ranks([rec.get("decision", {}).get("loss") for rec in records])
            for i in ranks:
                advice = interactllm._generate_advice(records[i])
                records[i]["commentary"] = advice

        # デバッグ・ログ確認用に data.json に保存
        try:
            data_file = Path(__file__).resolve().parent / "data.json"
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Failed to save data.json: %s", e)

        return records

    finally:
        remove_file(temp_input_path)

