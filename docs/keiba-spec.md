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
