# 作業ログ

## 2026-11 モデル再構築

### 問題
1. train_pl_model.py に時系列分割がない
   - 全期間（2023-2025）で学習→同じデータで評価していた
   - 過去の「公開データでは市場を超えられない」という結論は過学習を含む可能性
2. FEATURE_KEYS に新特徴量が未反映
   - 分析で確定した特徴量（騎手ランク、相性残差、枠番有利度、脚質、性別、年齢）が未統合
   - 分析とモデル構築を別作業として扱い、反映を先送りした

### 原因
- 「モデルを動かす」ことだけを考え「検証設計」を考えなかった
- 分析結果を記録して満足し、モデル反映を忘れた
- 目の前の課題解決しか考えていない（過去の指摘と同じ失敗）

### 対策
- 時系列分割を導入: 2023-2024で学習、2025で評価
- 分析結果を反映する作業を手順に組み込む
- 各Phaseで train/test 両方の損失を報告

### 作業手順

Phase 1: 現状保存（完了）
- RULES.md と analyze_*.py を commit

Phase 2: 作業ログ記録（このファイル）

Phase 3: 時系列分割機能を追加（最小変更）
- load_data で date 取得
- build_matrix で date を保持
- train/test 分割、両方の損失を評価

Phase 4: 時系列分割で現状特徴量を再評価
- baseline（市場のみ）と model（現状特徴量）を 2025年で比較
- これが真のベースライン

Phase 5: 新特徴量を段階的に追加
- 5-1: 性別・年齢（features から）
- 5-2: 脚質（features から）
- 5-3: 騎手ランク（jockey_stats_cache から join）
- 5-4: 相性残差（horse_jockey_residual_cache から join）
- 5-5: 枠番有利度（frame_mechanism_cache から join）
- 各Phase で train/test 両方の損失を確認、改善したものだけ残す

Phase 6: 最終評価
- 全特徴量 vs baseline を 2025年で比較
- 改善幅を記録

### 各Phaseの完了条件
- コード変更したら py_compile で通る
- 学習実行後、train と test の baseline/model 損失を報告
- 記録をこのファイルに追記

### 決定事項（2026-11-10）
- 騎手は当面「名前」で扱う（正規化: 記号除去＋所属除去）
- 騎手ID（jkyNb）への切り替えは後日、暇な時に実施
- 理由: 過去データ再取得に3〜5時間かかるため、モデル構築を優先
- 将来のID化に向けて、スクレイパー修正は別タスクとして記録

### 追加で判明した致命的な問題（2026-11-10 Phase 3 着手時）

train_pl_model.py を精査して判明。過去の私の報告に誤りがあった。

#### 問題5: train で market_log が加算されていない（致命的）
- 現状: `scores = X @ w` （特徴量のみ）
- baseline は market_log のみ
- つまり「市場のみ」と「特徴量のみ」を別々に計算して比較していただけ
- 「市場ベース＋残差補正」は一度も実行されていない
- 過去に報告した「baseline 1.586 vs 学習後 2.24」は、
  「市場単独が特徴量単独より優れている」という当たり前の結果の確認に過ぎない

#### 問題6: INTERACTIONS が X に含まれていない
- 定義はあるが、build_matrix の X 次元が len(FEATURE_KEYS) のみ
- 以前「INTERACTIONS を追加した」と報告したが、実際は定義だけで使われていなかった

#### 対策
- scores = market_log + X @ w に修正
- baseline = 市場のみ、評価 = 市場＋補正 に統一
- build_matrix で INTERACTIONS を計算して X に含める（方針A）
- 時系列分割: 2023-2024学習、2025評価

### Phase 3-b: 特徴量のみ版の再検証（2026-11-10）

#### 背景
Phase 3 で「市場ベース＋残差補正」が市場を悪化させることが確定（test 損失 2.0003 vs baseline 1.6026）。
ユーザー指示により、特徴量のみ版も正しく実装して比較する。

#### 実装内容
- train_pl_model.py に --no-market フラグ追加
- 市場ログを加算せず、X @ w のみでスコア計算
- 評価ベースライン:
  - uniform（1/頭数、市場も特徴量も使わない）
  - market（市場のみ、w=0）
  - feature-only（特徴量のみ、学習後）
- 保存ID: pl_feature_only（既存の pl は market-based のまま）
- メモリ対策: build_matrix 後、samples を del で解放

#### 変更前後の状態
- 変更前（phase 3）: market-based のみ、test 損失 2.0003（悪化）
- 変更後: --no-market で feature-only を評価可能に

#### 実行結果
（実行後に追記）
