# Keiba-EV-Tool

Plackett-Luce 順位モデル + 期待値 (EV) フィルタで JRA 勝馬投票券の買い目を自動生成するツール。PWA フロント付き。

## 特徴
- Plackett-Luce による順位確率 (独立掛け算禁止)
- EV = prob x odds - 1、3連単閾値 0.12
- Platt scaling キャリブレーション
- ドリフト検知
- vote-manager 連携 (未設定時はモック保存)
- PWA (ダークネイビー #0B1426 + ゴールド #D4AF37)

## セットアップ
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
pytest backend/tests -v

## 起動
uvicorn backend.main:app --reload --port 8000

## 環境変数
- VOTE_MANAGER_URL : 未設定ならモック保存
- JRAVAN_SID : JRA-VAN サービス ID
- JRAVAN_DATA_DIR : JV-Link データディレクトリ

## ディレクトリ
- backend/ : FastAPI, モデル, キャリブレーション
- backend/app/services/ : 既存サービス (本体は backend/ 直下を再エクスポート)
- frontend/ : PWA
- docs/keiba-spec.md : 仕様書
- .github/workflows/test.yml : CI

## ロードマップ
- [x] MockAdapter
- [x] Plackett-Luce
- [x] EV 計算
- [x] vote_manager
- [x] PWA manifest + sw.js
- [x] calibration / change_detector / config
- [ ] JRAVANAdapter 本番化
- [ ] フロント枠番色 / EV 色分け
- [ ] 本番デプロイ

## 追加ドキュメント
- docs/deploy.md : デプロイ手順

## 追加モジュール
- backend/adapters/jravan_adapter.py : JRA-VAN 骨組み
- frontend/theme.css : 枠番色 + EV 色テーマ
- frontend/ev-theme.js : evClass / wakuClass ユーティリティ
