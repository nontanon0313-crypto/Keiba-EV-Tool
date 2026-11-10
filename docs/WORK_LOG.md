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
