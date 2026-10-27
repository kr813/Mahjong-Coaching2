# 麻雀AIコーチング バックエンド (Mahjong-Coaching)

AI (Akochan / mjai-reviewer) の麻雀牌譜解析結果から卓状況（河・副露・手牌・他家の手牌・評価値候補など）を復元・抽出し、損失期待値（Loss）の大きい局面に対して OCI (Oracle Cloud Infrastructure) の Generative AI Agent によるコーチングアドバイスを付与した構造化 JSON を提供するバックエンド API サーバーです。

本サーバーの出力形式は、フロントエンド（Mahjong-Coaching_FrontEnd v2）の入力仕様（`ai-input-format`）に完全準拠しています。

---

## プロジェクト構成

- **`docs/`**: 詳細仕様書・ドキュメント
  - **`code_detail.md`**: 詳細仕様書（Markdown 版）
  - **`code_detail.pdf`**: 詳細仕様書（PDF 版）
  - **`code_detail.html`**: 仕様書 HTML プレビュー
  - **`generate_pdf.py`**: 仕様書 PDF 自動生成スクリプト
- **`backend/`**: Flask サーバーおよび解析処理スクリプト
  - **`app.py`**: アプリケーションのメインエントリーポイント（Flask）
  - **`utils.py`**: 解析実行およびデータ統合のオーケストレーション
  - **`build_ai_input.py`**: レポートHTMLから各局面の評価値・候補手・卓状況を統合し、新仕様 JSON を生成するモジュール
  - **`build_report.py`**: 新仕様 JSON から画面（`result_manyhands.html`）用ビューモデルへの変換モジュール
  - **`reconstruct_table_state.py`**: 埋め込み天鳳形式ログから自他家の手牌・河・副露・ドラなどの卓状況を完全復元するモジュール
  - **`interactakochan.py`**: Akochan 解析エンジン（mjai-reviewer サーバー）との連携モジュール
  - **`interactllm.py`**: OCI Generative AI Agent と連携してアドバイスを生成するモジュール
  - **`prompt.txt`**: AIコーチ向けのプロンプトテンプレート
  - **`requirements.txt`**: 依存 Python パッケージ定義（Flask, beautifulsoup4, lxml, oci）
  - **`test_app.py`**: 自動テストスクリプト

---

## 前提条件

- Python 3.10 以上
- Akochan 解析サーバー（`mjai-reviewer`）が起動していること（デフォルト: `http://localhost:8000`）
- （任意）OCI のアカウントおよび Generative AI Agent エンドポイント（未設定時はログ警告を出力しアドバイス付与を安全にスキップ）

---

## セットアップと起動手順

### 1. 依存ライブラリのインストール
```bash
cd backend
pip install -r requirements.txt
```

### 2. アプリケーションの起動
```bash
python app.py
```
デフォルトでは `http://0.0.0.0:8080`（環境変数 `PORT` で変更可能）で起動します。

### 3. テストの実行
```bash
python backend/test_app.py
```

---

## API エンドポイント

### `POST /analyze` または `POST /api/analyze`
牌譜解析を実行し、局全体の全局面データおよびAIアドバイスを含む JSON 配列を返却します。

#### リクエストパラメータ
- **クエリパラメータ / フォーム値**:
  - `seat`: 解析対象プレイヤーの席番号 (`0`: 東家, `1`: 南家, `2`: 西家, `3`: 北家。デフォルトは `0`)
  - `source_type`: データソースの種類 (`url` / `file` / `json`。省略時は自動判別)
  - `input_data`: 天鳳ログ URL、または牌譜 JSON テキスト
  - `url`: 天鳳ログの URL (`source_type=url` 時)
  - `format`: 返却形式（デフォルトは `json`。`html` を指定すると従来の HTML 表示を試行）
- **ファイルアップロード**:
  - `file`: 牌譜 JSON ファイル (`source_type=file` 時)

---

## 返却 JSON 仕様 (`ai-input-format`)

1局面が1つのオブジェクトとなった配列（`list[dict]`）形式で返却されます。

```json
[
  {
    "meta": {
      "engine": "Akochan",
      "kyoku": "東1局",
      "honba": 0,
      "kyotaku": 0,
      "dora_indicators": ["e"]
    },
    "situation": {
      "turn": 1,
      "wall_remaining": 69,
      "trigger": "draw",
      "trigger_actor": "自分",
      "trigger_tile": "8m"
    },
    "self": {
      "wind": "east",
      "is_dealer": true,
      "score": 25000,
      "hand_with_trigger_tile": ["1m", "2m", "2m", "3m", "4m", "3s", "4s", "5s", "8s", "9s", "e", "w", "c", "8m"],
      "melds": [],
      "river": []
    },
    "others": {
      "shimocha": {
        "wind": "south",
        "is_dealer": false,
        "score": 25000,
        "river": [],
        "melds": [],
        "riichi": false,
        "genbutsu": []
      },
      "toimen": { ... },
      "kamicha": { ... }
    },
    "hidden_info": {
      "note": "牌譜から復元した他家の手牌。実戦中は見えない情報。",
      "hands": {
        "shimocha": ["3m", "4s", ...],
        "toimen": [...],
        "kamicha": [...]
      }
    },
    "decision": {
      "player_choice": { "type": "discard", "tile": "w" },
      "ai_choice": { "type": "discard", "tile": "e" },
      "loss": 0.02832,
      "player_pt_ev": -0.90394,
      "ai_pt_ev": -0.87562,
      "candidates": [
        {
          "action": { "type": "discard", "tile": "e" },
          "pt_ev": -0.87562,
          "deal_in_pct": 0.00034,
          "post_deal_in_pt_ev": -32.16042,
          "tile_passes_pt_ev": -0.87551
        }
      ]
    },
    "commentary": "（期待値ロスが 0.15 以上の局面に付与される LLM のアドバイス文）"
  }
]
```