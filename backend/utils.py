from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

import extract
import interactakochan
import interactllm

# この値以上の期待値差がある判断だけを「要注意」とし、LLMのコメントを付ける
EV_DIFF_THRESHOLD = 0.15
LOGGER = logging.getLogger(__name__)

def write_temp_file(suffix: str, content: bytes) -> Path:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(content)
        return Path(handle.name)


def remove_file(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except OSError:
        pass


def to_json_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """抽出結果をフロント向けJSONの1件分にする（数値は小数2桁）。"""
    dora_indicators = entry.get("dora_indicators", [])
    return {
        "decision_id": entry["decision_id"],
        "kyoku": entry["kyoku"],
        "kyoku_id": entry["kyoku_id"],
        "turn": entry["turn"],
        "state_available": entry.get("state_available", False),
        "wall_remaining": entry.get("wall_remaining"),
        "dora_indicator": dora_indicators[0] if dora_indicators else None,
        "dora_indicators": dora_indicators,
        "scores": entry.get("scores", []),
        "hand": entry["hand"],
        "draw": entry["tsumo"],
        "melds": entry.get("melds", []),
        "rivers": entry.get("rivers", {}),
        "riichi": entry.get("riichi", []),
        "tehai": entry["tehai"],
        "player_discard": entry["player_discard"],
        "player_ev": round(entry["player_ev"], 2),
        "player_deal_in": round(entry["player_deal_in"], 2) if entry.get("player_deal_in") is not None else None,
        "ai_discard": entry["ai_discard"],
        "ai_ev": round(entry["ai_ev"], 2),
        "ai_deal_in": round(entry["ai_deal_in"], 2) if entry.get("ai_deal_in") is not None else None,
        "loss": round(entry["loss"], 2),
        "commentary": entry.get("commentary"),
    }


def build_view(entries: list[dict[str, Any]], json_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """テンプレート描画用に、局ごとにまとめたデータと集計値を作る。"""
    kyoku_groups: list[dict[str, Any]] = []
    for entry, js in zip(entries, json_entries):
        if not kyoku_groups or kyoku_groups[-1]["kyoku_id"] != entry["kyoku_id"] or kyoku_groups[-1]["kyoku"] != entry["kyoku"]:
            kyoku_groups.append({
                "kyoku": entry["kyoku"],
                "kyoku_id": entry["kyoku_id"] or f"kyoku-{len(kyoku_groups)}",
                "end_status": entry["end_status"],
                "entries": [],
            })
        kyoku_groups[-1]["entries"].append({
            **js,
            "hand": entry["hand"],
            "tsumo": entry["tsumo"],
            "tsumo_label": entry["tsumo_label"],
            "fuuro": entry["fuuro"],
            "player_parts": entry["player_parts"],
            "ai_parts": entry["ai_parts"],
            "is_warning": entry["loss"] >= EV_DIFF_THRESHOLD,
        })

    total = len(entries)
    matched = sum(1 for e in entries if e["player_discard"] == e["ai_discard"])
    warnings = sum(1 for e in entries if e["loss"] >= EV_DIFF_THRESHOLD)
    return {
        "kyoku_groups": kyoku_groups,
        "ai_name": entries[0]["ai_name"] if entries else "AI",
        "ev_threshold": EV_DIFF_THRESHOLD,
        "stats": {
            "total": total,
            "matched": matched,
            "match_rate": round(matched / total * 100, 1) if total else 0.0,
            "warnings": warnings,
            "total_loss": round(sum(max(e["loss"], 0.0) for e in entries), 2),
        },
    }


def run_analysis(
    source_type: str,
    seat: int,
    url: str | None = None,
    file_content: bytes | None = None,
    json_body: bytes | None = None,
    kyokus: list[str] | None = None,
) -> dict[str, Any]:
    html_path = None
    temp_html_path = None
    try:
        if source_type == "url":
            if not url:
                raise ValueError("query parameter 'url' is required for source_type=url")
            report_html = interactakochan.call_report(source_type="url", url=url, seat=seat)
        elif source_type == "file":
            if not file_content:
                raise ValueError("file upload is required for source_type=file")
            html_path = write_temp_file(".json", file_content)
            report_html = interactakochan.call_report(source_type="file", file_path=str(html_path), seat=seat)
        elif source_type == "json":
            if not json_body:
                raise ValueError("JSON body is required for source_type=json")
            html_path = write_temp_file(".json", json_body)
            report_html = interactakochan.call_report(source_type="json", json_path=str(html_path), seat=seat)
        else:
            raise ValueError("source_type must be one of json, file, url")

        temp_html_path = write_temp_file(".html", report_html.encode("utf-8"))
        entries = extract.extract_entries(str(temp_html_path), seat=seat)
        if not entries:
            raise ValueError("No analysable report entries were found.")

        if kyokus:
            requested = list(dict.fromkeys(kyokus))
            available = {entry["kyoku"] for entry in entries} | {entry["kyoku_id"] for entry in entries}
            missing = [kyoku for kyoku in requested if kyoku not in available]
            if missing:
                raise ValueError(f"Requested kyoku was not found: {', '.join(missing)}")
            order = {kyoku: index for index, kyoku in enumerate(requested)}
            entries = [
                entry
                for entry in entries
                if entry["kyoku"] in order or entry["kyoku_id"] in order
            ]
            entries.sort(key=lambda entry: order.get(entry["kyoku_id"], order.get(entry["kyoku"], len(order))))

        # 期待値差がしきい値以上の判断にだけ、OCIのLLMでアドバイスを付ける
        for entry in entries:
            entry["commentary"] = None
            if entry["loss"] >= EV_DIFF_THRESHOLD:
                try:
                    entry["commentary"] = interactllm._generate_advice(to_json_entry(entry))
                except Exception:
                    # 解析データは返却し、外部LLMの一時障害だけを局所化する。
                    LOGGER.exception("Failed to generate commentary for %s", entry["decision_id"])

        json_entries = [to_json_entry(e) for e in entries]

        return {"entries": json_entries, **build_view(entries, json_entries)}

    finally:
        remove_file(html_path)
        remove_file(temp_html_path)

