from __future__ import annotations

import os

from flask import Flask, Response, jsonify, request, render_template, abort

import utils

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


def _execute_analysis():
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
            if input_data.startswith("http://") or input_data.startswith("https://"):
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

    format_type = (request.args.get("format") or request.form.get("format") or "json").strip().lower()

    try:
        records = utils.run_analysis(
            source_type=source_type,
            seat=int(seat),
            url=url,
            file_content=file_content,
            json_body=json_body
        )

        if format_type == "html":
            return render_template("result.html", records=records)

        return jsonify(records)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        if format_type == "html":
            return render_template(
                "error.html",
                error_code="500",
                error_title="解析エンジンエラー",
                error_message=str(e)
            ), 500
        return jsonify(error=str(e)), 500


@app.route("/analyze", methods=["GET", "POST"])
def analyze() -> str | Response | tuple[str, int]:
    return _execute_analysis()


@app.route("/api/analyze", methods=["GET", "POST"])
def api_analyze() -> str | Response | tuple[str, int]:
    return _execute_analysis()

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
