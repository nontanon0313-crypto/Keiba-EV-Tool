# Keiba-EV-Tool 仕様書

## 1. 目的
JRA の勝馬投票券において、Plackett-Luce 順位モデルで推定した確率と
オッズから期待値 (EV) を算出し、閾値以上の買い目のみを vote-manager へ
連携する。フロントは PWA でオフライン閲覧可能。

## 2. 構成
- backend/ (FastAPI)
  - adapter/ : MockAdapter, JRAVANAdapter(骨組み)
  - model/ : Plackett-Luce 推定
  - calibration.py : Platt scaling
  - change_detector.py : ドリフト検知
  - vote_manager.py : 買い目送信
  - config.py : 設定
- frontend/ (PWA)
- backend/tests/ : pytest

## 3. 確率モデル
Plackett-Luce: P(A→B→C) = P(A) · P(B|A) · P(C|A,B)
独立掛け算 P(A)P(B)P(C) は禁止。条件付きで逐次除去する。

## 4. EV
EV = prob × odds − 1
閾値: 3連単 0.12 / 馬単 0.10 / 3連複 0.08 / ワイド 0.05

## 5. vote-manager 連携
- VOTE_MANAGER_URL 未設定 → モック保存
- 設定時 → POST {URL}/api/v1/vote-plans
- client_plan_id = keiba-YYYYMMDD-場-R-乱数6桁

## 6. キャリブレーション
Platt scaling をロジット空間で適用。CALIB_WINDOW 件で再フィット。

## 7. 変化検知
予測平均と実測的中率の差が DRIFT_THRESHOLD を超えたら drift=true。

## 8. UI
ダークネイビー #0B1426 + ゴールド #D4AF37
枠番色: 1白 2黒 3赤 4青 5黄 6緑 7橙 8桃
EV 色分け: <0 灰, 0〜閾値 白, 閾値〜0.3 金, >0.3 赤金

## 9. デプロイ
1. backend を uvicorn で起動 (systemd or Docker)
2. frontend を static ホスティング
3. PWA manifest + sw.js でキャッシュ
4. VOTE_MANAGER_URL を env で注入
