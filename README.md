# Keiba-EV-Tool

Plackett-Luce 順位モデル + 期待値 (EV) フィルタで JRA 勝馬投票券の買い目を
自動生成し、投票記録・的中検証・収益管理までを一気通貫で行う PWA。

## 公開URL
- フロント (PWA): https://nontanon0313-crypto.github.io/Keiba-EV-Tool/
- API: https://keiba-ev-tool.onrender.com
- ヘルス: https://keiba-ev-tool.onrender.com/health
- ドキュメント: https://keiba-ev-tool.onrender.com/docs

## 特徴
- Plackett-Luce による順位確率 (独立掛け算禁止、条件付き逐次除去)
- 7券種対応: 3連単 / 3連複 / 馬単 / 馬連 / ワイド / 単勝 / 複勝
- 三連単確率から他券種を派生計算 (derived.py)
- EV = prob × odds − 1、券種別閾値
- ケリー基準による推奨金額の自動算出
- 予想の決定化 (race_id シード)
- 投票記録 / 払戻の手動確定 / 収益サマリ / 資産推移グラフ
- 検証ページ (スコープ別 / 券種別 / 項目別 / EV帯別)
- PWA (ダークネイビー #0B1426 + ゴールド #D4AF37)

## アーキテクチャ
Android Chrome / PWA (GitHub Pages)
  -> frontend/*.html css js
  -> JavaScript 実行
Render API (keiba-ev-tool.onrender.com)
  -> FastAPI
backend/app/services/
  -> bets.json / results.json (ファイル永続化)

## ディレクトリ
- backend/ : FastAPI アプリ本体
  - app/routers/ : races, predictions, vote_plans, analytics, bets, results, health
  - app/services/ : prediction, ev_calc, derived, bet_store, result_fetcher, vote_manager
  - app/models/schemas.py : Pydantic スキーマ
  - adapters/ : MockAdapter / JRAVANAdapter (JV-Link 骨組み)
  - tests/ : pytest
- frontend/ : PWA
  - index.html / app.js / theme.css / ev-theme.js
  - manifest.json / sw.js / icon.svg
- docs/ : 仕様書・デプロイ手順
- .github/workflows/ : CI と GitHub Pages デプロイ

## セットアップ
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest backend/tests -v
uvicorn backend.app.main:app --reload --port 8000

## 環境変数
| Key | 用途 | 設定タイミング |
|---|---|---|
| VOTE_MANAGER_URL | 競輪ツール vote-manager のURL | 競輪側デプロイ後 |
| VOTE_MANAGER_API_KEY | 認証トークン | 必要時 |
| JRAVAN_SID | JRA-VAN サービスID | Windowsサーバ運用時のみ |
| JRAVAN_DATA_DIR | JV-Data 蓄積ディレクトリ | 同上 |
| LOG_LEVEL | INFO / DEBUG / WARNING | 任意 |
| PYTHON_VERSION | Render の Python バージョン | 推奨 3.11.9 |

## Render デプロイ
1. Render Dashboard -> New -> Blueprint
2. リポジトリを接続
3. render.yaml 自動検出 -> keiba-ev-tool 作成
4. 環境変数を Dashboard で設定
5. https://keiba-ev-tool.onrender.com/health で確認

## GitHub Pages デプロイ
1. Settings -> Pages -> Source を GitHub Actions に変更
2. main へ push で自動デプロイ
3. https://nontanon0313-crypto.github.io/Keiba-EV-Tool/

## PWA インストール (Android)
1. Chrome で公開URLを開く
2. ⋮ メニュー -> ホーム画面に追加
3. KeibaEV アイコンから standalone 起動

## 主要エンドポイント
- GET /races : レース一覧
- GET /races/{race_id} : レース詳細
- GET /predictions/{race_id} : 予想確率
- POST /vote-plans : 券種・フィルタ指定で買い目生成
- GET /analytics : スコープ別・券種別の検証
- POST /bets : 投票記録
- GET /bets : 投票履歴
- GET /bets/summary : 収益サマリ
- GET /bets/curve : 資産推移カーブ
- POST /bets/{id}/settle : 払戻確定
- DELETE /bets/{id} : 投票削除
- GET /health : ヘルスチェック

## 券種の閾値
| 券種 | EV閾値 |
|---|---|
| 3連単 | 0.12 |
| 馬単 / 馬連 | 0.10 |
| 3連複 | 0.08 |
| ワイド | 0.05 |
| 単勝 | 0.05 |
| 複勝 | 0.03 |

## ロードマップ
- [x] MockAdapter / Plackett-Luce / EV計算 / vote_manager
- [x] PWA manifest + sw.js + アイコン
- [x] calibration / change_detector / config
- [x] JRAVANAdapter 骨組み / JV-Data パーサ
- [x] 7券種対応 / 派生計算 / ケリー金額
- [x] 収益管理 / 検証ページ / 資産推移グラフ
- [x] PWA ホーム画面追加
- [ ] JRA-VAN 本番接続 (Windowsサーバ)
- [ ] キャリブレーション有効化 (データ300件以上)
- [ ] 自動結果取得 (JRA-VAN 結果データ)
