## 1. 契約と開発基盤

- [x] 1.1 `pyproject.toml`、`src/app/__init__.py`、`README.md` を `demo-vlm-dom` 配布名と `demo` CLI に合わせ、Pillow と HTTPX を追加して `uv.lock` を更新する。対象 OS の準備手順、推論用画像の最大寸法の設定方法と元寸法出力、用語集、旧 CLI 名を参照する雛形テストの置換方針も反映する。対応: `NREQ-001`、設計「背景・前提」「構成と設定」「移行とロールバック」、`TC-017`。完了条件: `uv run --locked demo` が入口を解決し、README に Mac/Ubuntu・Python 3.13・Ollama・画像と設定の準備、CLI 名が記載される。
- [x] 1.2 `config/setting.ini` と `src/app/driving_scene_annotation/config.py` に URL、事前ロード・推論タイムアウト、保持時間、推論用画像の最大幅・最大高さ、線幅、三色を定義して型と範囲を検証する。対応: `REQ-008`、設計「データ契約と状態」「構成と設定」、`TC-015`。完了条件: 既定の推論上限が 1280×720 px となり、有効な INI の設定値を取得でき、0 以下や整数以外の寸法では項目名を示して画像処理前に停止する。

## 2. 画像とモデルの責務

- [x] 2.1 `src/app/driving_scene_annotation/images.py` に単一フレーム画像の読取、縦横比を保つ必要時のみの縮小と上限内 PNG の VLM 入力化、元画像への三色・線幅の矩形描画、元寸法・元形式での一時保存と成功時の同名置換を実装する。対応: `REQ-002`、`REQ-004`、`REQ-005`、`REQ-006`、設計「データ契約と状態」「画像形式と失敗時の旧出力保護」、`TC-008`、`TC-009`、`TC-011`、`TC-012`、`TC-018`、`TC-019`。完了条件: 推論画像は上限内で小画像を拡大せず、無検出は元寸法・無枠で出力され、保存失敗は旧出力を保持し、成功時だけ同名が更新される。
- [x] 2.2 `src/app/driving_scene_annotation/ollama_client.py` と `analysis.py` に VLM の英語指示、JSON Schema 付き画像解析、`json.loads()` による構造・ID・推論用画像ピクセル座標の検証、検証済み矩形の元画像座標への換算を実装する。対応: `REQ-002`、設計「データ契約と状態」「Ollama への接続方法」、`TC-002`、`TC-003`、`TC-004`、`TC-018`。完了条件: 有効な車両の矩形を元画像の対応位置に外向き丸めで換算し、無効矩形だけを除外し、形式不正と ID 重複を画像失敗として返す。
- [x] 2.3 `src/app/driving_scene_annotation/ollama_client.py` と `analysis.py` に一車両ごとの短い `state`、英語の四択 `choice`、`answers` と車両 ID の対応付けを実装する。対応: `REQ-003`、設計「データ契約と状態」「Ollama への接続方法」、`TC-005`、`TC-006`、`TC-007`。完了条件: 高・中・低を区別し、根拠不足は判定不能となり、欠落・未知選択肢は画像失敗となる。
- [x] 2.4 `src/app/driving_scene_annotation/ollama_client.py` に VLM の空要求と DOM の固定質問による初回使用直前の事前ロード、応答確認、別タイムアウト、保持時間、失敗後の次画像での再試行を実装する。対応: `REQ-007`、`REQ-005`、`REQ-008`、設計「処理フロー」「インターフェースと失敗時の結果」、`TC-013`、`TC-014`、`TC-015`。完了条件: 模擬 HTTP の呼出順序でロード前に実推論しないこと、ロード失敗後に後続画像で再試行することを確認できる。
- [x] 2.5 `analysis.py` と `ollama_client.py` に自車線を独立した項目で渡し、各車両の車線は従来の位置関係と根拠に記述させる。異なる車線を前方という理由だけで高にしない DOM 指示を追加する。自車線は `left/center/right/single/unknown` とし、曖昧な配置は不明として扱う。対応: `REQ-002`、`REQ-003`、`REQ-003-S04`、設計「データ契約と状態」「Ollama への接続方法」、`TC-002`、`TC-020`。完了条件: 自車線と対象車両の位置関係が DOM に渡り、対象画像の左隣車両が実モデルで中となる。
- [x] 2.6 `analysis.py` と `ollama_client.py` に、見かけの小さい遠方車両を低とする前処理と、反対車線を低にする DOM 指示を追加する。VLM には実在する遠方の小さい車両も重複なく列挙させる。対応: `REQ-002`、`REQ-003`、`REQ-003-S05`、設計「処理フロー」「データ契約と状態」、`TC-021`。完了条件: 遠方車両は車線不明でも青枠となり、5 枚の実画像で近い同車線・近い左右・遠方の色を確認できる。

## 3. CLI と画像別の処理

- [x] 3.1 `src/app/driving_scene_annotation/cli.py` に `data/src` 直下の名前順処理、画像別の失敗継続、理由と段階のログ、成功・失敗件数・失敗ファイル名・処理時間の集計を実装する。対応: `REQ-001`、`REQ-005`、`REQ-009`、設計「業務フローと責務」「境界条件と失敗モード」、`TC-001`、`TC-010`、`TC-011`、`TC-016`。完了条件: 一枚の破損・モデル失敗後も次画像が処理され、集計と終了コードが設計どおりになる。

## 4. 自動試験と品質確認

- [x] 4.1 `tests/test_vehicle_analysis.py` に `TC-002`、`TC-003`、`TC-004`、`TC-005`、`TC-006`、`TC-007`、`TC-018` の pytest テストを作成・実行し、正常 JSON、推論用画像の座標境界、縦横比を保つ縮小・非拡大・元画像座標への換算、ID 重複、四択、判定不能、応答不正を確認する。対応: `REQ-002`、`REQ-003`、各 Scenario、設計「試験設計」。完了条件: 設計表の対応する7つの pytest 関数が成功する。
- [x] 4.2 `tests/test_image_output.py` に `TC-008`、`TC-009`、`TC-011`、`TC-012`、`TC-019` の pytest テストを作成・実行し、実画像の形式・元寸法・色・太さ、無検出、保存失敗時の旧出力保持、成功時の同名置換を確認する。対応: `REQ-004`、`REQ-005`、`REQ-006`、各 Scenario、設計「試験設計」。完了条件: 設計表の対応する5つの pytest 関数が成功する。
- [x] 4.3 `tests/test_ollama_client.py` と `tests/test_demo_config.py` に `TC-013`、`TC-014`、`TC-015` の pytest テストを作成・実行し、VLM の空要求・DOM の固定質問・実推論の順序、ロード失敗後の再試行、INI 値の適用を確認する。対応: `REQ-007`、`REQ-008`、各 Scenario、設計「試験設計」。完了条件: 設計表の対応する3つの pytest 関数が成功する。
- [x] 4.4 `tests/test_demo_cli.py` に `TC-001`、`TC-010`、`TC-016`、`TC-017` の pytest テストを作成・実行し、複数画像、失敗後継続、集計、対象 OS 上の CLI 起動を確認する。対応: `REQ-001`、`REQ-005`、`REQ-009`、`NREQ-001`、各 Scenario、設計「試験設計」。完了条件: 設計表の対応する4つの pytest 関数が成功する。
- [x] 4.5 `tests/test_vehicle_analysis.py`、`tests/test_ollama_client.py`、`tests/test_demo_cli.py` に自車線項目の構造検証、DOM への自車線と位置関係の受け渡し、判定不能と隣接車線の回帰 pytest テストを追加し、全自動試験と品質検査を再実行する。対応: `REQ-002`、`REQ-003`、`REQ-003-S04`、`TC-002`、`TC-006`、`TC-020`。完了条件: 新契約の試験と `npm run check`、pre-commit、実装段階のトレーサビリティ検査が成功する。
- [x] 4.6 `tests/test_vehicle_analysis.py` に見かけの大きさによる遠方判定と DOM を呼ばない順序を確認する pytest テストを追加する。対応: `REQ-003`、`REQ-003-S05`、`TC-021`。完了条件: 高さの境界、車線不明の遠方、近い車両の DOM 判定が検証できる。

## 5. 対象環境での受け入れと完了

- [x] 5.1 `uv run --locked pytest`、`uv run --locked ruff check .`、`uv run --locked ruff format --check .`、`uv run --locked pyright`、`uv run --locked pre-commit run --all-files`、`npm run check` と `uv run --locked python scripts/check_openspec_traceability.py --change demo-vlm-dom --phase implementation` を実行する。対応: `REQ-001`～`REQ-009`、`NREQ-001`、設計「試験設計」「網羅性確認」。完了条件: 全自動試験、品質検査、参照テスト収集が成功し、結果を証跡に記録する。
- [ ] 5.2 `AC-001` について、来歴が確かな実走行画像で三段階・元寸法・枠位置・小車両の精度を確認し、旧 JPEG・AVIF・WebP の結果と遠方小矩形の過剰検出を再検証する。結果を `evidence/acceptance.md` に記録し、design の状態を更新する。対応: `REQ-002`～`REQ-004`、設計「受け入れ検証」。完了条件: 実画像で AC-001 の状態と証跡が一致する。
- [ ] 5.4 `AC-002` について、無検出・根拠不足を含む実画像で枠の有無と理由を確認し、結果を `evidence/acceptance.md` に記録する。対応: `REQ-002`～`REQ-004`、設計「受け入れ検証」。完了条件: AC-002 の実画像結果と証跡が一致する。
- [ ] 5.5 `AC-003` について、実モデルで一枚失敗した後の継続と、その画像の旧出力保持を確認し、結果を `evidence/acceptance.md` に記録する。対応: `REQ-005`、`REQ-006`、設計「受け入れ検証」。完了条件: AC-003 の実モデル結果と証跡が一致する。
- [ ] 5.6 `AC-004` について、設定値を変更した実モデル実行で画像上限・二種類のタイムアウト・保持時間と事前ロードの分離を確認し、結果を `evidence/acceptance.md` に記録する。対応: `REQ-007`、`REQ-008`、設計「受け入れ検証」。完了条件: AC-004 の設定変更時の結果と証跡が一致する。
- [x] 5.3 `npx --no-install openspec validate demo-vlm-dom --strict` と通常は `uv run --locked python scripts/check_openspec_traceability.py --change demo-vlm-dom --phase complete` を verify / archive 前に実行し、成果物、完了タスク、受け入れ証跡をレビューする。受け入れ確認だけを延期する場合は、該当する `AC-001`～`AC-004` の 5.2、5.4～5.6 を未完了のまま README の「延期中の受け入れ確認」へ引き継ぎ、`--phase limited-archive` を使い、利用者の明示的了承を得る。対応: 全要件、設計「受け入れ検証」「移行とロールバック」。完了条件: 通常または制限付きの該当する厳密検証に成功し、証跡の環境・結果がレビュー済みである。
