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
  - **`shanten_calculator.py`**: 手牌の向聴数（シャンテン数）および有効牌・受け入れ枚数（残り枚数・最大枚数）を高速計算するモジュール
  - **`build_report.py`**: 新仕様 JSON から画面（`result_manyhands.html`）用ビューモデルへの変換モジュール
  - **`reconstruct_table_state.py`**: 埋め込み天鳳形式ログから自他家の手牌・河・副露・ドラなどの卓状況を完全復元するモジュール
  - **`interactakochan.py`**: Akochan 解析エンジン（mjai-reviewer サーバー）との連携モジュール
  - **`interactllm.py`**: OCI Generative AI Agent と連携してアドバイスを生成するモジュール
  - **`prompt.txt`**: OCI 側に登録する AI コーチの指示文
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

## OCI の助言生成を使う場合

アプリをデプロイする前に、対象エンドポイントで実際に助言本文を生成するモデルのカスタム指示に [backend/prompt.txt](backend/prompt.txt) の内容を登録してください。たとえば RAG ツールが回答本文を生成する構成では、生成モデルのカスタム指示（`generationLlmCustomization.instruction`）が設定先です。利用中の構成に本文生成用のカスタム指示があるかを確認し、OCI 側で局面 JSON を試して、回答の最終行に `[[ADVICE_COMPLETE]]` が付くことを確認してください。

検証用エンドポイントに切り替える場合は、バックエンド起動時に `OCI_AGENT_ENDPOINT_OCID` にそのエンドポイントの OCID を指定します。接続リージョンは OCID から取得します。未設定または空白の場合は従来の大阪リージョンのエンドポイントを使用します。

```bash
OCI_AGENT_ENDPOINT_OCID='<検証用エンドポイントの OCID>' python app.py
```

アプリは局面データと回答形式を示す `response_profile` を JSON で送信します。初回は `standard`、応答が空か完了マーカーを欠く場合は同じ局面を `compact` で一度だけ再生成します。完了マーカーは表示前に除去されます。短縮版でも完了を確認できない場合や短縮版の取得に失敗した場合は、取得済みの本文を初回優先で返します。両方とも本文がなければ、助言は `null` になります。

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
      "player_choice": {
        "type": "discard",
        "tile": "w",
        "acceptance": {
          "shanten": 1,
          "shanten_desc": "一向聴",
          "tiles": ["1m", "4m", "3s", "6s"],
          "remaining_count": 11,
          "max_count": 14,
          "details": [
            {"tile": "1m", "remaining": 3, "max": 4},
            {"tile": "4m", "remaining": 2, "max": 4},
            {"tile": "3s", "remaining": 3, "max": 3},
            {"tile": "6s", "remaining": 3, "max": 3}
          ]
        }
      },
      "ai_choice": {
        "type": "discard",
        "tile": "e",
        "acceptance": {
          "shanten": 1,
          "shanten_desc": "一向聴",
          "tiles": ["1m", "4m", "2s", "3s", "6s"],
          "remaining_count": 15,
          "max_count": 18
        }
      },
      "loss": 0.02832,
      "player_pt_ev": -0.90394,
      "ai_pt_ev": -0.87562,
      "candidates": [
        {
          "action": {
            "type": "discard",
            "tile": "e",
            "acceptance": {
              "shanten": 1,
              "shanten_desc": "一向聴",
              "tiles": ["1m", "4m", "2s", "3s", "6s"],
              "remaining_count": 15,
              "max_count": 18
            }
          },
          "pt_ev": -0.87562,
          "deal_in_pct": 0.00034,
          "post_deal_in_pt_ev": -32.16042,
          "tile_passes_pt_ev": -0.87551
        }
      ]
    },
    "commentary": "（期待値ロスが大きい順ワースト5の局面に付与される LLM のアドバイス文）"
  }
]
```