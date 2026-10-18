## 背景・前提

現状の `src/app/__init__.py` は挨拶を表示し、`pyproject.toml` は `python-template` CLI を公開している。
画像処理、Ollama 接続、`config/setting.ini`、`data/src` と `data/dest` は存在せず、既存の正式仕様もない。
この変更では一つの `driving-scene-annotation` capability を `src/app/driving_scene_annotation/` に対応させる。
Python パッケージ `app` は維持し、配布名と公開 CLI を `demo-vlm-dom` と `demo` に変更する。

Ollama サーバーと `qwen2.5vl:7b`、`tev1` は実行者が用意する。
ローカル Ollama 0.40.4 では、VLM の空の `/api/generate` と画像付き構造化出力、および DOM の短い `/v1/systemone` 質問への応答を確認した。DOM は `/api/generate` に HTTP 400 を返す。実走行画像での座標品質と三段階の判定は後述の受け入れ検証で確認する。
これは設計した契約の実機検証であり、別方式を無断採用するための余地ではない。

## 目標・対象外

### 目標

- `uv run --locked demo` で `data/src` の静止画像を縮小して推論し、`data/dest` に元画像と同じ寸法・形式の結果を保存する。
- 画像解析、判定、描画、保存を分け、各段階の失敗を画像単位で報告する。
- 成功時だけ同名出力を置換し、失敗時は旧出力を維持する。
- 初回ロード用と実推論用のタイムアウトを分け、設定を反映する。

### 対象外

- 動画、複数フレーム、速度・距離の測定、将来の危険予測は入力仕様の対象外とする。
- 常駐サービス、画像の永続的な判定履歴、モデルの自動ダウンロードは設けない。
- 実際の道路運行に使う安全判定はデモの目的に含めない。

## 要件トレーサビリティ

| 要件ID | 対応する設計節 | 責務・境界 | 実装タスク | 試験ケース | 検証方法 |
| --- | --- | --- | --- | --- | --- |
| REQ-001 | 業務フローと責務 | CLI・画像列挙 | 3.1 | TC-001 | 複数画像の CLI 自動試験 |
| REQ-002 | データ契約と状態 | 推論用画像・VLM 応答・座標換算 | 2.1、2.2、2.5 | TC-002、TC-003、TC-004、TC-018 | 縮小、構造・車線・座標換算・重複 ID の契約試験 |
| REQ-003 | データ契約と状態 | DOM 判定 | 2.3、2.5 | TC-005、TC-006、TC-007、TC-020 | 選択肢と判定不能、別車線を高にしない契約試験 |
| REQ-004 | インターフェースと失敗時の結果 | 元寸法での描画・同形式出力 | 2.1 | TC-008、TC-009、TC-019 | 実画像のピクセル・寸法・形式試験 |
| REQ-005 | 境界条件と失敗モード | 画像別失敗・旧出力保護 | 3.1 | TC-010、TC-011 | CLI と保存失敗の自動試験 |
| REQ-006 | データ契約と状態 | 成功時の同名置換 | 2.1 | TC-012 | 出力置換の自動試験 |
| REQ-007 | 処理フロー | 初回ロード・再試行 | 2.4 | TC-013、TC-014 | HTTP 契約と順序の自動試験 |
| REQ-008 | 技術判断 | 推論画像の上限を含む INI 設定 | 1.2 | TC-015 | 設定読込と反映の自動試験 |
| REQ-009 | インターフェースと失敗時の結果 | CLI 集計・処理時間 | 3.1 | TC-016 | 標準出力の自動試験 |
| NREQ-001 | セキュリティ・性能・運用 | 対象 OS・Python | 1.1 | TC-017 | 対象 OS の CLI 自動試験と実機確認 |

## 業務フローと責務

### 責務一覧

| 責務 / 境界 | 変更種別 | 入力 | 出力・副作用 | 依存先 | 実装候補・確定状況 |
| --- | --- | --- | --- | --- | --- |
| CLI と一括処理 | 追加 | `data/src` の直下のファイル、設定 | 画像別結果、終了集計 | 画像 I/O、モデル呼出 | `src/app/driving_scene_annotation/cli.py`、確定 |
| 設定読込 | 追加 | `config/setting.ini` | 検証済み設定 | 標準ライブラリ | `src/app/driving_scene_annotation/config.py`、確定 |
| 画像 I/O と描画 | 追加 | 静止画像、推論画像の最大寸法、元画像座標の矩形、優先度 | 縮小した推論用画像、元寸法・同形式の一時画像と成功時の出力置換 | Pillow | `src/app/driving_scene_annotation/images.py`、確定 |
| Ollama 呼出 | 追加 | モデル名、画像または判定材料 | VLM・DOM の応答 | HTTPX、Ollama | `src/app/driving_scene_annotation/ollama_client.py`、確定 |
| 応答検証と判定契約 | 追加 | JSON 応答、推論用・元画像の寸法 | 元画像座標の車両情報と区分 | 標準ライブラリ | `src/app/driving_scene_annotation/analysis.py`、確定 |

`common/` は作らない。
共有契約は同一能力内で受け渡し、他能力への直接 import はない。
CLI とテストの境界は `app.driving_scene_annotation` で閉じる。

### 処理フロー

1. CLI が INI を読み、値と入力・出力場所を確認する。設定自体が読めない場合は画像単位の処理を開始せず、設定エラーを表示する。
2. `data/src` 直下の通常ファイルを名前順に処理する。画像の読取に失敗したファイルも失敗件数に含める。
3. 各画像を完全に読み込み、形式と元の画素寸法を保持する。設定した最大幅・最大高さに収まるよう縦横比を保って必要な場合だけ縮小し、推論用の実寸法を記録して PNG バイト列を VLM に渡す。元画像の画素は出力用に保持する。
4. VLM を初めて使う直前にモデル名だけの空要求で事前ロードする。ロード失敗ならその画像を失敗とし、次の画像で再試行する。成功後、画像と英語の指示・JSON Schema を付けて解析する。
5. 応答本文を `json.loads()` で読み、構造、一意な ID、自車線、各車両の位置関係、推論用画像の座標を検証する。自車線は見える同方向の `left/center/right/single/unknown` とし、一意に表せない配置は `unknown` とする。無効な矩形は車両単位で除外し、有効な矩形だけ元画像の座標に換算する。形式不正や重複 ID は画像全体を失敗とする。
6. 有効な矩形の見かけの高さが元画像の高さの 8% 未満、または同じ画像で最大の有効な車両矩形の高さの 40% 未満なら、画像上で離れて見える車両として低にする。これは実距離の推定ではなくデモ用の相対的な画像寸法判定である。遠方の車両について車線が不明でも、矩形の見かけの小ささを根拠に低とする。それ以外で位置関係または自車線が不明なら判定不能にする。他の車両を初めて DOM で判定する直前に、固定の短い `state` と `ready/other` の `choice` 質問を `/v1/systemone` に送り、応答構造を確認する。この選択結果を車両判定には使わない。失敗時は次の画像で再試行する。成功後、自車線・対象車両の車線を含む位置関係・根拠と、見かけの近さ `near` を一車両ごとの短い `state` と一つの `choice` 質問で DOM に渡す。
7. `answers` の該当質問の `choice` を ID に結び付け、高・中・低・判定不能を検証する。高・中・低だけを元画像上に色付き枠で描画する。車両がいない場合は DOM を呼ばず、元寸法の無枠画像を作る。
8. 元画像の形式で出力先と同じディレクトリ内の一時ファイルへ保存し、保存成功後に同名出力へ置換する。途中で失敗した画像は旧出力を更新しない。
9. 画像別の結果をコンソールへ出し、全画像の成功・失敗件数、失敗したファイル名、全体の処理時間を表示する。失敗が一つでもあれば終了コード 1、全件成功または入力 0 件なら 0 とする。

### データ契約と状態

| データ / 契約 | 変更 | フィールド・型・必須性 | 制約・既定値 | 生成・更新主体 | 互換性 / 移行 |
| --- | --- | --- | --- | --- | --- |
| 設定 `setting.ini` | 追加 | `ollama_url: str`、`preload_timeout_seconds: float`、`inference_timeout_seconds: float`、`keep_alive: str`、`inference_max_width: int`、`inference_max_height: int`、`line_width: int`、`high_color/medium_color/low_color: str` (すべて必須) | URL は HTTP(S)、秒数・画像上限・線幅は正、保持時間は Ollama の duration、色は `#RRGGBB`。既定例は `http://127.0.0.1:11434`、600 秒、300 秒、`10m`、1280×720 px、3 px、赤 `#FF0000`、黄 `#FFFF00`、青 `#0000FF` | 実行者 / 設定読込 | 新規設定であり移行なし |
| 推論用画像 | 追加 | 元画像の寸法 `W,H`、送信画像の寸法 `w,h` と PNG バイト列 | `w ≤ inference_max_width`、`h ≤ inference_max_height`。縦横比は整数画素への丸めを除いて維持し、拡大しない | 画像 I/O | 元画像の画素は描画まで保持 |
| VLM 応答 | 追加 | `scene_description: str`、`camera_lane: left/center/right/single/unknown`、`vehicles: array`。各要素は `id: str`、`bbox: int[4]`、`path_relation: str`、`evidence: str` (必須) | `bbox` は送信した推論用画像の絶対ピクセル座標。`id` は画像内一意。自車線は見える同方向の車線を区別し、同方向が一車線なら `single`、一意に表せなければ `unknown`。各車両の車線は `path_relation` と `evidence` に記述する。既知の `path_relation` には非空の根拠。`0 ≤ xmin < xmax ≤ w`、`0 ≤ ymin < ymax ≤ h`。空配列は無検出 | VLM / 応答検証 | 新規契約 |
| 優先度の前処理 | 追加 | 元画像の高さ、各有効な車両矩形の高さ | 画像高さの 8% 未満、または最大車両矩形の高さの 40% 未満なら低。小さな遠方車両は車線が不明でも低 | 応答検証 | デモ用の見かけの大きさによる判定 |
| DOM 質問と応答 | 追加 | `state` に場面説明、自車線、一車両の ID・矩形・車線を含む位置関係・根拠。質問 ID は車両 ID に対応し、`choice` は `high/medium/low/undetermined` | 前処理で低にならない車両で位置関係または自車線が不明なら判定不能。異なる車線で進路重複の根拠がなければ高を許さず、隣接車線なら中。反対車線は低。欠落や指定外値は画像失敗 | DOM / 応答検証 | 新規契約 |
| 出力画像 | 追加 | 入力と同じファイル名・画素寸法・画像形式 | 元画像の画素に換算後の矩形を描画。成功時に同名を置換。失敗時は既存出力を保持。無検出は無枠で成功 | 画像 I/O | 既存ファイルは成功時に上書き |
| 実行結果 | 追加 | 画像別の成功・失敗と原因、全体の件数、処理時間 | 生画像、モデルの生応答、秘密情報はログに含めない | CLI | 新規契約 |

矩形は右端・下端を含まない半開区間として扱い、まず推論用画像の `w,h` に対して検証する。
有効な矩形の元画像座標は `xmin=floor(xmin'×W/w)`、`ymin=floor(ymin'×H/h)`、`xmax=ceil(xmax'×W/w)`、`ymax=ceil(ymax'×H/h)` とし、元画像の幅・高さちょうどの `xmax`・`ymax` を有効とする。
縮小寸法は `s=min(1, inference_max_width/W, inference_max_height/H)` とし、`w=max(1, floor(W×s))`、`h=max(1, floor(H×s))` で決める。
描画時は終点を画素内に変換する。
推論用画像の外側にある矩形は切り詰めず除外する。

### インターフェースと失敗時の結果

| 境界 / 操作 | 呼び出し元 → 呼び出し先 | 入力 | 成功結果 | 失敗条件 → 結果 | 冪等性・再試行・タイムアウト |
| --- | --- | --- | --- | --- | --- |
| `demo` CLI | 実行者 → アプリ | `data/src` と INI | `data/dest` と集計表示 | 設定不正 → 起動を停止して設定項目を表示 | 再実行可能。成功出力は置換 |
| 画像読取・保存 | アプリ → ファイルシステム | 一枚の静止画像 | 同形式の出力 | 破損・未対応形式・保存失敗 → 画像失敗、旧出力保持 | 保存は一時ファイル後に置換。次画像へ進む |
| VLM 事前ロード | アプリ → `/api/generate` | VLM 名、`keep_alive`、空の `prompt` | `done: true` | 接続・HTTP・タイムアウト・不正応答 → 画像失敗、後続画像で再試行 | 初回画像解析直前。専用タイムアウト |
| DOM 事前ロード | アプリ → `/v1/systemone` | DOM 名、`keep_alive`、固定の短い `state` と `ready/other` の `choice` 質問 | `answers.warmup.choice` が指定選択肢のいずれか | 接続・HTTP・タイムアウト・不正応答 → 画像失敗、後続画像で再試行 | 初回車両判定直前。専用タイムアウト。選択結果は車両の優先度に使わない |
| VLM 解析 | アプリ → `/api/chat` | 上限寸法内の base64 画像、推論画像の座標を求める英語指示、JSON Schema、`stream: false` | 推論用画像の座標を含む構造化応答 | HTTP・タイムアウト・形式不正 → 画像失敗 | 画像単位。通常推論タイムアウト |
| DOM 判定 | アプリ → `/v1/systemone` | 一車両の短い `state`、英語の選択肢 | `answers` 内の `choice` | HTTP・タイムアウト・選択肢欠落 → 画像失敗 | 一車両一質問。通常推論タイムアウト |

## 技術判断

### 判断・候補: Ollama への接続方法

- **状態**: 確定
- **採用内容 / 候補**: HTTPX による JSON/HTTP 呼出を使い、VLM の実推論は `/api/chat`、事前ロードは空の `/api/generate` とする。DOM の事前ロードは固定の短い `/v1/systemone` 質問、車両判定も `/v1/systemone` とする。
- **根拠**: エンドポイントごとに別タイムアウトと応答検証を設けられる。Ollama の[画像入力](https://docs.ollama.com/capabilities/vision)、[構造化出力](https://docs.ollama.com/capabilities/structured-outputs)、[事前ロード](https://github.com/ollama/ollama/blob/main/docs/faq.mdx)、[tev1 の API](https://ollama.com/library/tev1) に沿う。
- **代替案**: Ollama Python SDK と TypeSafe SDK の併用は二種類のクライアントと例外型を増やすため採らない。
- **実装規則 / 不変条件**: VLM は画像と JSON Schema を渡し、自車線を独立した項目、対象車両の車線を位置関係と根拠で求める。DOM には画像を直接渡さず、前方という語だけで高を選ばせない。事前ロードの成功を実推論成功と扱わず、DOM の事前ロードの選択結果を優先度に流用しない。接続と応答は画像単位で失敗へ変換する。
- **影響**: HTTPX を実行依存に追加し、Ollama の必要版とモデルの存在を README に示す。

### 判断・候補: 画像形式と失敗時の旧出力保護

- **状態**: 確定
- **採用内容 / 候補**: Pillow で単一フレーム画像を読み、元の画像形式・寸法で一時ファイルへ保存した後 `os.replace` する。VLM 入力は設定した上限寸法内に縮小した PNG に変換する。
- **根拠**: 画像形式の判別、矩形描画、同形式のエンコードを一つのライブラリで扱える。ファイルへの保存時には形式を明示できる ([Pillow](https://pillow.readthedocs.io/en/stable/reference/Image.html))。
- **代替案**: OpenCV は今回の静止画描画に対して依存と入出力変換が増える。直接同名へ保存すると失敗時に旧出力を壊すため採らない。
- **実装規則 / 不変条件**: 保存できない形式はその画像の失敗とする。描画に伴う色モード変換後も形式と元寸法は維持する。無検出は枠を描かずに出力する。失敗時は一時ファイルを消し、既存出力を置換しない。
- **影響**: Pillow を実行依存に追加する。サポートできる実画像形式は対象環境で確認する。

### 判断・候補: 構成と設定

- **状態**: 確定
- **採用内容 / 候補**: 一能力パッケージ内に CLI、設定、画像 I/O、Ollama 呼出、応答検証を置く。設定は標準ライブラリで INI を読み、明示した値を検証する。
- **根拠**: 既存の `app` パッケージを維持し、デモ規模でも外部 I/O と判定契約を独立して試験できる。
- **代替案**: `common/` への先行分割は実際の共有先がない。単一巨大ファイルは外部境界のテストを難しくする。
- **実装規則 / 不変条件**: モデルの応答と設定は信頼せず検証する。モデルへの指示とキーは英語、利用者向けの説明は日本語にする。
- **影響**: `pyproject.toml` の CLI と配布名、README の起動手順・用語、テンプレート用の挨拶テストを更新する。

## 境界条件と失敗モード

| 事象 / 境界条件 | 検知する責務 | 処理・状態変更 | 利用者 / 呼び出し元への結果 | 記録・監視 | 復旧 |
| --- | --- | --- | --- | --- | --- |
| 入力 0 件 | CLI | 出力変更なし | 成功 0 件・失敗 0 件 | 全体時間 | 画像を配置して再実行 |
| 破損・読めない画像 | 画像 I/O | 当該画像を失敗、旧出力保持 | ファイル名と読取理由 | 失敗件数 | 入力を修正して再実行 |
| 推論画像の最大寸法が 0 以下・整数以外 | 設定読込 | 全画像の処理開始前に停止 | 不正な設定項目を表示 | 設定エラー | 正の整数へ修正して再実行 |
| JSON 不正・必須項目欠落・ID 重複 | 応答検証 | 当該画像を失敗、旧出力保持 | モデルと検証理由 | 失敗件数 | モデル条件を確認して再実行 |
| 無効矩形 | 応答検証 | 当該車両だけ除外 | 除外件数と座標理由 | 除外件数 | 必要なら画像や指示を見直す |
| 前方進路が読めない | 応答検証 | 当該車両は判定不能 | 描画なし、件数と理由 | 判定不能件数 | 別の画像で再実行 |
| Ollama 接続・ロード・推論失敗 | Ollama 呼出 | 当該画像を失敗、旧出力保持 | モデル名・段階・原因 | 失敗件数 | 後続画像でロード再試行、接続を確認 |
| 出力エンコード・置換失敗 | 画像 I/O | 当該画像を失敗、旧出力保持 | ファイル名と保存理由 | 失敗件数 | 形式・権限・容量を確認して再実行 |

## セキュリティ・性能・運用

| 観点 | 設計上の対応 | 判定基準 / 監視方法 |
| --- | --- | --- |
| 入力検証 | 画像を完全に読取り、JSON の型・項目数・ID・推論画像の座標、INI の値を検証する | 不正な画像・応答・設定の試験と画像別の理由表示 |
| 秘密情報 | 設定に認証情報を置かず、ログに画像内容・モデルの生応答を出さない | リポジトリ検査とログレビュー |
| 性能 | 事前ロードと推論で別タイムアウトを適用し、モデル保持時間と推論画像の最大寸法を設定する | 送信画像の寸法が上限内か確認する。精度・処理時間の数値目標はデモの対象外。縮小に伴う小さい車両の見落としは実静止画で確認する |
| 運用 | Mac または Ubuntu で Python 3.13 と Ollama・指定モデルを準備する | 自動テストと、対象 OS・実モデル・実静止画を明記したスモーク記録 |

## 移行とロールバック

1. 既存の永続データはなく、データ移行は不要である。配布名と CLI はテンプレート名から変わるため、README の手順と `pyproject.toml` を同時に更新する。
2. `data/dest` の既存画像は成功時に上書きされる。実行前に旧結果を残したい利用者は別の場所へ退避する。
3. ロールバックは変更前のコード・設定・ロックファイルへ戻す。出力画像の内容は自動復元されないため、必要なら退避した画像を戻す。

## 試験設計

| TC ID | 要件ID | Scenario ID | テスト層 | 前提・操作 | 期待値 | pytest 実装 | 自動化 | 検証範囲 | 残る検証 | 証跡 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TC-001 | REQ-001 | REQ-001-S01 | CLI 統合 | 複数画像で CLI 起動 | 全画像の結果が得られる | `tests/test_demo_cli.py::test_processes_all_images` | はい | テスト用モデル応答と CLI | 5.2 実モデル | `evidence/quality.md` |
| TC-002 | REQ-002 | REQ-002-S01 | 単体 | 有効な車両 JSON を解析 | ID・矩形・説明・根拠を保持 | `tests/test_vehicle_analysis.py::test_accepts_vehicle_coordinates_and_evidence` | はい | JSON 契約 | 5.2 実 VLM の座標 | `evidence/quality.md` |
| TC-003 | REQ-002 | REQ-002-S02 | 単体 | 推論用画像の逆転・画像外・境界座標を入力 | 不正だけ除外し理由を返す | `tests/test_vehicle_analysis.py::test_drops_invalid_box` | はい | 送信画像の座標境界 | 5.2 実 VLM の座標 | `evidence/quality.md` |
| TC-004 | REQ-002 | REQ-002-S03 | 単体 | JSON 破損・欠落・ID 重複 | 画像失敗を返す | `tests/test_vehicle_analysis.py::test_rejects_invalid_vlm_result` | はい | 応答検証 | なし | `evidence/quality.md` |
| TC-005 | REQ-003 | REQ-003-S01 | 単体 | 高・中・低の車両と選択結果 | 区分と高優先を保持 | `tests/test_vehicle_analysis.py::test_maps_priority_choices` | はい | DOM 応答契約 | 5.2 実 DOM の判断 | `evidence/quality.md` |
| TC-006 | REQ-003 | REQ-003-S02 | 単体 | 位置関係不明の車両 | 判定不能で描画対象外 | `tests/test_vehicle_analysis.py::test_marks_unknown_without_choice` | はい | 根拠不足の契約 | 5.2 実画像の不明例 | `evidence/quality.md` |
| TC-007 | REQ-003 | REQ-003-S03 | 単体 | 選択肢欠落・未知値 | 画像失敗を返す | `tests/test_vehicle_analysis.py::test_rejects_invalid_dom_choice` | はい | DOM 応答検証 | なし | `evidence/quality.md` |
| TC-008 | REQ-004 | REQ-004-S01 | 画像統合 | PNG/JPEG と三段階の矩形 | 同形式で設定色・太さを反映 | `tests/test_image_output.py::test_draws_configured_boxes_in_same_format` | はい | 実 Pillow と実ファイル | 5.2 実画像 | `evidence/quality.md` |
| TC-009 | REQ-004 | REQ-004-S02 | 画像統合 | 車両 0 件 | 無枠の元寸法・同形式画像と成功 | `tests/test_image_output.py::test_writes_unchanged_scene_when_no_vehicles` | はい | 実 Pillow と実ファイル | なし | `evidence/quality.md` |
| TC-010 | REQ-005 | REQ-005-S01 | CLI 統合 | 破損画像の後に有効画像 | エラーを記録し後続を保存 | `tests/test_demo_cli.py::test_continues_after_corrupt_image` | はい | 画像 I/O・CLI、モデル応答は代替 | 5.2 実モデル | `evidence/quality.md` |
| TC-011 | REQ-005 | REQ-005-S02 | 画像統合 | 旧出力あり、保存失敗 | 旧内容を保持 | `tests/test_image_output.py::test_failed_write_preserves_existing_output` | はい | 保存失敗時の状態 | なし | `evidence/quality.md` |
| TC-012 | REQ-006 | REQ-006-S01 | 画像統合 | 旧出力あり、保存成功 | 新内容で置換 | `tests/test_image_output.py::test_success_replaces_existing_output` | はい | 実ファイルの上書き | なし | `evidence/quality.md` |
| TC-013 | REQ-007 | REQ-007-S01 | HTTP 契約 | 未ロードで VLM・DOM を使用 | VLM 空要求と DOM 固定質問の後に各実 API 呼出。DOM の固定質問は優先度へ流用しない | `tests/test_ollama_client.py::test_preloads_each_model_before_first_inference` | はい | 模擬 HTTP の順序と応答分離 | 5.2 実 Ollama | `evidence/quality.md` |
| TC-014 | REQ-007 | REQ-007-S02 | HTTP 契約 | VLM または DOM の最初のロード失敗、次は成功 | 後続で該当モデルのロード再試行 | `tests/test_ollama_client.py::test_retries_preload_for_later_image` | はい | 模擬 HTTP の再試行 | 5.2 実 Ollama | `evidence/quality.md` |
| TC-015 | REQ-008 | REQ-008-S01 | 設定統合 | INI 値を変更して起動 | URL・各時間・保持時間・画像寸法上限・描画値を反映。不正な寸法は起動前に拒否 | `tests/test_demo_config.py::test_applies_ini_settings` | はい | 設定と呼出引数 | なし | `evidence/quality.md` |
| TC-016 | REQ-009 | REQ-009-S01 | CLI 統合 | 成功・失敗を混在 | 件数・ファイル名・時間を表示 | `tests/test_demo_cli.py::test_reports_counts_files_and_duration` | はい | CLI 出力 | 5.2 実行表示 | `evidence/quality.md` |
| TC-017 | NREQ-001 | NREQ-001-S01 | CLI 統合 | 対象 OS と Python 3.13 で CLI 起動 | 同形式画像と結果を取得 | `tests/test_demo_cli.py::test_cli_runs_on_supported_platform` | はい | 試験実行 OS と模擬モデル | 5.2 実 Ollama・対象 OS | `evidence/quality.md` |
| TC-018 | REQ-002 | REQ-002-S04 | 画像・座標統合 | 上限より大きい画像と上限内の画像で推論入力を作り、境界に接する VLM 矩形を換算 | 大画像だけ縦横比を維持して縮小、小画像は拡大せず、送信寸法で検証した矩形を元画像の位置へ外向きに換算 | `tests/test_vehicle_analysis.py::test_resizes_and_maps_box_to_source` | はい | 実 Pillow と座標換算。モデル応答は代替 | 5.2 実 VLM の位置精度 | `evidence/quality.md` |
| TC-019 | REQ-004 | REQ-004-S03 | 画像統合 | 大画像の縮小推論結果を元画像に描画・保存 | 枠が元画像の対応位置にあり、出力寸法・形式が元画像と一致 | `tests/test_image_output.py::test_resized_inference_keeps_source_dimensions` | はい | 実 Pillow と実ファイル | 5.2 実画像での枠位置 | `evidence/quality.md` |
| TC-020 | REQ-003 | REQ-003-S04 | HTTP 契約 | 自車線 `center`、対象の位置関係は左車線の前方、進路重複の根拠なし | DOM に自車線と対象の位置関係を渡し、「前方」だけを高の根拠としない。実モデルの対象画像では中を確認 | `tests/test_ollama_client.py::test_supplies_distinct_lanes_to_dom` | はい | 模擬 HTTP の入力契約 | 5.2 の対象画像で実 DOM の選択 | 未作成 |
| TC-021 | REQ-003 | REQ-003-S05 | 単体・実画像 | 同じ画像で大きい前方車と小さい遠方車、遠方車の車線は不明 | 画像高さと最大車両矩形に対する見かけの高さから遠方車を低にし、DOM を呼ばない。5 枚では近い同車線を赤、近い左右を黄、遠方を青にする | `tests/test_vehicle_analysis.py::test_marks_visually_distant_vehicle_low` | はい | 相対寸法と判定順序 | 5.2 の五枚の実画像 | 未作成 |

## 網羅性確認

| 要件ID | Scenario数 | 対応TC数 | 未対応Scenario | 状態 |
| --- | --- | --- | --- | --- |
| REQ-001 | 1 | 1 | なし | 網羅 |
| REQ-002 | 4 | 4 | なし | 網羅 |
| REQ-003 | 5 | 5 | なし | 網羅 |
| REQ-004 | 3 | 3 | なし | 網羅 |
| REQ-005 | 2 | 2 | なし | 網羅 |
| REQ-006 | 1 | 1 | なし | 網羅 |
| REQ-007 | 2 | 2 | なし | 網羅 |
| REQ-008 | 1 | 1 | なし | 網羅 |
| REQ-009 | 1 | 1 | なし | 網羅 |
| NREQ-001 | 1 | 1 | なし | 網羅 |

## 受け入れ検証

| 受け入れID | 検証範囲・条件 | 検証方法 | 残る検証 | 状態 | 証跡 |
| --- | --- | --- | --- | --- | --- |
| AC-001 | Mac または Ubuntu、推論上限を超える実静止画と実 Ollama・三段階 | `uv run --locked demo` の枠位置・出力色・寸法・形式を原画と照合 | PNG 5 枚で期待色と元寸法を確認。画像来歴の確認、旧 JPEG・AVIF・WebP の再試験、遠方小矩形の過剰検出の確認が残る | 未検証 | `openspec/changes/archive/2026-10-19-demo-vlm-dom/evidence/acceptance.md` |
| AC-002 | 無検出、無効矩形、根拠不足を含む画像と模擬応答 | pytest と実静止画で枠の有無・理由を確認 | 5.4 の無検出・根拠不足の実画像確認 | 未検証 | `openspec/changes/archive/2026-10-19-demo-vlm-dom/evidence/acceptance.md` |
| AC-003 | 一枚失敗・後続成功・旧出力ありの条件 | pytest と CLI 実行で継続と上書き状態を確認 | 5.5 の失敗後の実モデル処理と旧出力保持 | 未検証 | `openspec/changes/archive/2026-10-19-demo-vlm-dom/evidence/acceptance.md` |
| AC-004 | 推論画像の最大幅・最大高さ等の設定を変えた模擬 HTTP と実 Ollama の VLM 空要求・DOM 固定質問 | pytest と実行ログで各ロード・実推論の分離、送信寸法・設定反映を確認 | 5.6 の設定変更時の実モデル確認 | 未検証 | `openspec/changes/archive/2026-10-19-demo-vlm-dom/evidence/acceptance.md` |
| AC-005 | Mac または Ubuntu、Python 3.13、指定モデル、実静止画 | CLI 実行・対象環境・版・結果・処理時間を記録 | なし | 検証済み | `openspec/changes/archive/2026-10-19-demo-vlm-dom/evidence/acceptance.md` |

## 未決事項

実装を止める未決事項はない。
PNG 5 枚の最終出力では、すぐ前方の同車線車両、左右の近い車両、遠方の車両の色分けを目視し、利用者が現状を了承した。
4db の遠方小矩形には過剰列挙・重なりの疑いが残る。
旧 JPEG の前方車両の判定不一致、AVIF の全矩形除外、WebP の JSON 切断は最新のプロンプトでは再試験していない。
無検出・根拠不足、設定変更時の実モデル、実モデルでの失敗後継続と旧出力保持については、タスク 5.2 の受け入れ確認として未検証のまま追跡する。
