from __future__ import annotations

import json
import os

from flask import Flask, Response, abort, jsonify, render_template, request

import utils

app = Flask(__name__)


def _api_error(message: str, status: int = 400) -> tuple[Response, int]:
    return jsonify(error=message), status


@app.route("/analyze", methods=["GET", "POST"])
def analyze() -> str | Response | tuple[str, int]:
    # seat: フォーム (request.form) → クエリパラメータ (request.args) の順で取得
    seat = (request.form.get("seat") or request.args.get("seat") or "0").strip()
    if seat not in {"0", "1", "2", "3"}:
        return jsonify(error="seat must be 0, 1, 2, or 3"), 400

    # source_type: 明示指定 → 自動判定
    source_type = (
        request.form.get("source_type")
        or request.args.get("source_type")
        or ""
    ).strip().lower()

    # フォームの input_data フィールド (URL or JSONテキスト)
    input_data = (request.form.get("input_data") or "").strip()

    if not source_type:
        # 自動判定: input_data の内容、ファイル、クエリパラメータから推定
        if request.args.get("url", "").strip():
            source_type = "url"
        elif input_data:
            # input_data がURL風なら "url"、そうでなければ "json" テキストとみなす
            if input_data.startswith(("http://", "https://")):
                source_type = "url"
            else:
                source_type = "json"
        elif "file" in request.files and request.files["file"].filename:
            source_type = "file"
        elif request.is_json:
            source_type = "json"
        else:
            return jsonify(error="source_type is required when url/file/json is not provided"), 400

    url = None
    file_content = None
    json_body = None

    if source_type == "url":
        # フォームの input_data → クエリパラメータ url の順で取得
        url = input_data or (request.args.get("url") or "").strip()
        if not url:
            return jsonify(error="URL が指定されていません"), 400
    elif source_type == "file":
        uploaded_file = request.files.get("file")
        if uploaded_file is None or uploaded_file.filename == "":
            return jsonify(error="ファイルが選択されていません"), 400
        file_content = uploaded_file.read()
    elif source_type == "json":
        # フォームの input_data → リクエストボディの順で取得
        if input_data:
            json_body = input_data.encode("utf-8")
        elif request.is_json:
            json_body = request.get_data()
        if not json_body:
            return jsonify(error="JSON データが空です"), 400

    try:
        data = utils.run_analysis(
            source_type=source_type,
            seat=int(seat),
            url=url,
            file_content=file_content,
            json_body=json_body
        )
        return render_template("result.html", **data)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return render_template(
            "error.html",
            error_code="500",
            error_title="解析エンジンエラー",
            error_message=str(e)
        ), 500


@app.route("/api/v1/analyze", methods=["POST"])
def analyze_api() -> Response | tuple[Response, int]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _api_error("JSON object body is required")

    try:
        seat = int(payload.get("seat", 0))
    except (TypeError, ValueError):
        return _api_error("seat must be 0, 1, 2, or 3")
    if seat not in {0, 1, 2, 3}:
        return _api_error("seat must be 0, 1, 2, or 3")

    source = payload.get("source")
    if not isinstance(source, dict):
        return _api_error("source must be an object")
    source_type = str(source.get("type", "")).strip().lower()
    source_data = source.get("data")
    if source_type not in {"url", "json"}:
        return _api_error("source.type must be url or json")

    kyokus_value = payload.get("kyokus")
    kyokus: list[str] | None = None
    if kyokus_value is not None:
        if not isinstance(kyokus_value, list) or not kyokus_value:
            return _api_error("kyokus must be a non-empty array when specified")
        if not all(isinstance(value, str) and value.strip() for value in kyokus_value):
            return _api_error("each kyokus item must be a non-empty string")
        kyokus = [value.strip() for value in kyokus_value]

    url = None
    json_body = None
    if source_type == "url":
        if not isinstance(source_data, str) or not source_data.strip():
            return _api_error("source.data must contain a URL")
        url = source_data.strip()
    else:
        if source_data is None:
            return _api_error("source.data must contain replay JSON")
        if isinstance(source_data, str):
            json_body = source_data.encode("utf-8")
        else:
            json_body = json.dumps(source_data, ensure_ascii=False).encode("utf-8")

    try:
        data = utils.run_analysis(
            source_type=source_type,
            seat=seat,
            url=url,
            json_body=json_body,
            kyokus=kyokus,
        )
        return jsonify(data["entries"])
    except ValueError as error:
        return _api_error(str(error))
    except Exception:
        app.logger.exception("analysis API failed")
        return _api_error("analysis failed", 500)

@app.route("/", methods=["GET"])
def index() -> str:
    return render_template("index.html")


@app.route("/error", methods=["GET", "POST"])
def error() -> Response | tuple[str, int]:
    abort(500)


@app.errorhandler(404)
def page_not_found(e):
    return render_template(
        "error.html",
        error_code="404",
        error_title="ページが見つかりません",
        error_message="お探しのページは移動または削除されたか、URLが間違っている可能性があります。"
    ), 404


@app.errorhandler(400)
def bad_request(e):
    return render_template(
        "error.html",
        error_code="400",
        error_title="不正なリクエストです",
        error_message="送信されたデータに誤りがあるか、処理できない形式のリクエストです。"
    ), 400


@app.errorhandler(500)
def internal_server_error(e):
    return render_template(
        "error.html",
        error_code="500",
        error_title="サーバーエラーが発生しました",
        error_message="バックエンド側で問題が発生しました。しばらく時間を置いてから再度お試しください。"
    ), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
