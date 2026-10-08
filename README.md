# 麻雀AIコーチング (Mahjong-Coaching)

AI (Akochan) の麻雀牌譜解析結果から最も損失期待値（Loss）の大きかった打牌を抽出し、OCI (Oracle Cloud Infrastructure) の Generative AI Agent を通じて人間にわかりやすいアドバイス（麻雀コーチング）を提供するWebアプリケーションです。

## プロジェクト構成

- **`backend/`**: Flaskサーバーおよび各種解析処理スクリプト
  - **`app.py`**: アプリケーションのメインエントリーポイント（Flask）
  - **`interactllm.py`**: OCI Generative AI Agentとの連携モジュール
  - **`interactakochan.py`**: Akochanの解析エンジンと連携するモジュール
  - **`extract.py`**: 解析レポート（HTML/JSON）からデータをパース・抽出するモジュール
  - **`frontend.html`**: 解析の実行とアドバイスの表示を行うリッチなWeb UI（3D麻雀牌表示、マークダウン対応アドバイス）
  - **`prompt.txt`**: AIコーチ向けのシステムプロンプト設定ファイル
  - **`requirements.txt`**: 依存Pythonパッケージ定義

## 前提条件

- Python 3.10以上
- OCI (Oracle Cloud Infrastructure) のアカウントおよび Generative AI Agent のエンドポイント
- ローカル環境またはOCI環境での認証情報の設定（インスタンス・プリンシパルまたは `~/.oci/config`）

## セットアップと起動手順

### 1. 依存ライブラリのインストール
`backend` ディレクトリへ移動し、必要なパッケージをインストールします。

```bash
cd backend
pip install -r requirements.txt
```

### 2. アプリケーションの起動
Flaskサーバーを起動します。

```bash
python app.py
```
サーバーは `http://localhost:8000` で起動します。

### 3. フロントエンドの利用
ブラウザで `http://localhost:8000` にアクセスすると、Web UIが表示されます。
ここから以下の方法で麻雀の打牌解析とアドバイス生成を実行できます：
- **ファイル**: Akochanの解析レポート（JSON/HTML形式）をアップロード
- **URL**: 天鳳のログURLを入力して解析
- **JSON入力**: 解析済みのJSONデータを直接入力

## API エンドポイント

### `POST /analyze`
牌譜解析とLLMアドバイスを実行し、結果をHTML形式で返却します。

- **クエリパラメータ**:
  - `seat`: プレイヤーの席番号 (0: 東家, 1: 南家, 2: 西家, 3: 北家)
  - `source_type`: データソースの種類 (`file` / `url` / `json`)
  - `url`: 天鳳ログのURL (source_type=url時のみ必須)
- **リクエストボディ**:
  - `file` (Multipart/form-data, source_type=file時)
  - JSONデータ (raw body, source_type=json時)

### `POST /api/v1/analyze`

牌譜解析結果をJSON配列で返却します。`kyokus`には局名（例: `East 1`）または
HTML内の局ID（例: `kyoku-0-0`）を複数指定できます。省略時は全局を返します。

```json
{
  "seat": 2,
  "source": {
    "type": "url",
    "data": "https://tenhou.net/0/?log=..."
  },
  "kyokus": ["kyoku-0-0", "kyoku-1-0"]
}
```

レスポンスの各判断には、次の情報が含まれます。

- `decision_id`, `kyoku`, `kyoku_id`, `turn`, `wall_remaining`
- `dora_indicator`, `dora_indicators`, `scores`
- `hand`, `draw`, `melds`
- `rivers`（`self`, `shimocha`, `toimen`, `kamicha`）
- `riichi`（東家・南家・西家・北家の順）
- `player_discard`, `player_ev`, `player_deal_in`
- `ai_discard`, `ai_ev`, `ai_deal_in`, `loss`, `commentary`

`player_deal_in`と`ai_deal_in`の単位はパーセントです。カンがある場合に備え、
ドラ表示牌は単数の`dora_indicator`に加えて`dora_indicators`でも返します。
