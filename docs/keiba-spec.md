# Keiba-EV-Tool 仕様書

## 1. 目的
JRA の勝馬投票券において、Plackett-Luce 順位モデルで推定した確率と
オッズから期待値 (EV) を算出し、閾値以上の買い目のみを抽出。投票記録・
的中検証・収益管理までを1つの PWA で完結させる。

## 2. 構成
- frontend (GitHub Pages): PWA
- backend (Render): FastAPI
- データ永続化: bets.json / results.json

## 3. 確率モデル
### 3.1 単勝確率
Plackett-Luce を1着のみで適用。
score = 1/odds_win - (weight - 54) * 0.02 + noise(0, 0.05)
race_id をシードにした決定的乱数で毎回同じ予想を返す。

### 3.2 三連単確率
P(A->B->C) = P(A) * P(B|A) * P(C|A,B)
条件付きで逐次除去。独立掛け算 P(A)P(B)P(C) は禁止。

### 3.3 派生券種
三連単確率から以下を合算:
- 三連複: 3頭組み合わせ (6通りの三連単を合算)
- 馬単: 1-2着順序 (3着目を合算)
- 馬連: 1-2着順不同 (馬単2通りを合算)
- ワイド: 3頭から2頭組 (3ペア合算)

## 4. EV と金額
### 4.1 EV
EV = prob * odds - 1

### 4.2 券種別閾値
| 券種 | EV閾値 |
|---|---|
| 3連単 | 0.12 |
| 馬単 / 馬連 | 0.10 |
| 3連複 | 0.08 |
| ワイド | 0.05 |
| 単勝 | 0.05 |
| 複勝 | 0.03 |

### 4.3 推奨金額 (ケリー基準)
f = (prob * odds - 1) / (odds - 1)
amount = collateral * f * 0.25
上限 max_investment、100円単位切り捨て

## 5. 投票記録と収益
### 5.1 記録
POST /bets で race_id, combo, amount, odds, prob, ev, ticket_type を保存。
bets.json に追記。

### 5.2 確定
POST /bets/{id}/settle で払戻金額を記録。
- payout > 0 -> 的中
- payout = 0 -> 不的中
- 未確定 -> pending

### 5.3 サマリ
- 実的中率 = hits / total_bets
- 想定的中率 = 平均 prob
- 実ROI = 損益 / 投資
- 想定ROI = 想定損益 / 投資
- 平均オッズ / 加重平均オッズ

### 5.4 資産推移
投票順に x=累積投資額, y=累積損益 をプロット。
想定線 (EV積算) と実績線を重ねて表示。終端にドットと数値ラベル。

## 6. 検証ページ
### 6.1 スコープ
- 全体: 全候補
- 投票: 投票済みのみ
- 除外: 投票していないもの

### 6.2 ビュー
- 期待値帯: -1〜0 / 0〜0.05 / 0.05〜0.10 / 0.10〜0.15 / 0.15〜0.20 / 0.20〜0.30 / 0.30〜0.50 / 0.50〜1.0 / 1.0〜5.0 / 5.0+
- 確率帯: 0〜5% 0.1%刻み / 5〜10% 0.5%刻み / 10〜20% 1%刻み / 20〜50% 5%刻み
- オッズ帯: 1〜200 1刻み / 200〜1000 50刻み / 1000+
- 出走表項目: 人気 / 斤量 / 枠番 / 単勝オッズ

各テーブルに 予想的中率 / 実的中率 / オッズ平均 / 想定利益% / 実利益% を表示。
件数は投票対象/全体 (x/y) 形式で表示。

## 7. UI
- ダークネイビー #0B1426 + ゴールド #D4AF37
- 枠番色: 1白 2黒 3赤 4青 5黄 6緑 7橙 8桃
- EV色分け: <0 灰, 0〜閾値 白, 閾値〜0.3 金, >0.3 赤金
- タブ: 予想 / 検証 / 収益 / 設定(歯車)
- 詳細設定はモーダル (最低確率 / 最低オッズ / 証拠金 / 上限投資)
- 設定値は localStorage に保存、次回起動時も適用

### 7.1 予想タブ
- レース一覧: 発走時刻昇順、終了30分超のレースは非表示
- 詳細画面: 券種タブ (3連単/3連複/馬単/馬連/ワイド/単勝/複勝)
- EVテーブル: EV順ソート、金額入力可、個別投票/一括投票

### 7.2 収益タブ
- サマリ: 投票数 / 投資 / 払戻 / 損益 / 実的中率(x/y) / 想定的中率 / 実ROI / 想定ROI / 平均オッズ / 加重平均 / 想定損益
- 資産推移グラフ (Canvas、横軸=投資額、縦軸=損益)
- 投票履歴: レース / 買い目 / 金額 / オッズ / 状態 / 損益 / 払戻 / 削除
- 未確定行は払戻入力欄 + 確定ボタン
- 一括0円確定ボタン

## 8. デプロイ
### 8.1 バックエンド (Render)
- Blueprint (render.yaml)
- startCommand: uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT
- healthCheckPath: /health
- 環境変数: VOTE_MANAGER_URL, JRAVAN_SID, JRAVAN_DATA_DIR, LOG_LEVEL

### 8.2 フロント (GitHub Pages)
- Actions で frontend/ を Pages へデプロイ
- Source: GitHub Actions

### 8.3 PWA
- manifest.json: standalone, アイコン (SVG, maskable)
- sw.js: network-first (HTML/JS/CSS), cache-fallback

## 9. CI
- pytest (backend/tests)
- ruff (backend のみ、E501/E402/E401/E701/E702 など除外)
- mypy (continue-on-error)

## 10. 未実装 / 将来
- JRA-VAN 本番接続 (Windows + JV-Link)
- 自動結果取得 (JRA-VAN 結果データ)
- キャリブレーション有効化 (データ300件以上蓄積後)
- 券種別 ROI 比較ページ
- 買い目の編集機能
