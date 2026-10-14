# 分析前チェックリスト

分析スクリプトを書く前に、必ずこのチェックリストを通す。

## 1. データソースの確認

同じ情報が複数箇所にある場合、全て確認する。

| 情報 | runners | result_runners | features | 備考 |
|---|---|---|---|---|
| age_sex | 牡/牝のみ | 牡/牝/セ | 牡/牝のみ | **runners はセを牡と誤記** |
| horse_number | あり | あり | あり | |
| jockey | あり | あり | あり | |
| weight | あり | あり | あり | |
| horse_weight | あり | あり | あり | |
| horse_weight_change | あり | あり | あり | runners は bulk_fetch 修正後のみ |
| trainer | 空 | あり | 空 | **result_runners のみ** |
| time | なし | あり | なし | |
| agari_3f | なし | あり | なし | |
| corner | なし | あり | なし | |
| finish | なし | あり | なし | |

## 2. 過去の分析との整合性

- 前に見たデータ、分析結果を思い出す
- 矛盾する結果が出たら、データソースの違いを疑う
- 「存在しない」と判断する前に、考えうる全ての箇所を確認する

## 3. 検証結果の出所

- 何のデータを、いつ、どう集計したか
- サンプル数、除外条件
- 想定される交絡因子

## 4. 分析前に確認する過去の分析

- single_feature.py の結果
- feature_analytics_cache（単一特徴）
- feature_interactions_cache（交互作用）
- frame_mechanism_cache（枠番機構）
- frame_by_popularity_cache（人気×枠）
- frame_by_odds_cache（オッズ×枠）
- age_analysis_cache（年齢、**runners ベースなのでセ抜け**）
- condition_deviation_cache（条件別乖離）

## 5. 忘れ防止のルール

- 分析スクリプト作成時、このチェックリストを最初に読む
- 過去の分析と同じ観点を扱う時は、前回のスクリプトを確認する
- データを「取り直す」前に、既存データを確認する
