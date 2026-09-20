# デプロイ手順

## 1. 事前準備
- Termux または Linux サーバ
- Python 3.11+
- VOTE_MANAGER_URL (本番連携時のみ)
- JRAVAN_SID / JRAVAN_DATA_DIR (JV-Link 本番時のみ)

## 2. 依存インストール
python -m pip install -r backend/requirements.txt
python -m pip install uvicorn pydantic pydantic-settings httpx

## 3. 環境変数
.env をプロジェクト直下に置く:
VOTE_MANAGER_URL=https://your-vote-manager.example.com
JRAVAN_SID=your-sid
JRAVAN_DATA_DIR=/path/to/jvdata
LOG_LEVEL=INFO

## 4. backend 起動
uvicorn backend.main:app --host 0.0.0.0 --port 8000

## 5. テスト
python -m pytest backend/tests -v

## 6. frontend
- frontend/ を任意の static ホスティング (Cloudflare Pages / GitHub Pages)
- theme.css と ev-theme.js を読み込む
- PWA manifest + sw.js は frontend/ 配下に配置

## 7. systemd 例
[Unit]
Description=Keiba-EV-Tool
After=network.target

[Service]
WorkingDirectory=/home/user/Keiba-EV-Tool
EnvironmentFile=/home/user/Keiba-EV-Tool/.env
ExecStart=/usr/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target

## 8. 動作確認
curl http://localhost:8000/health
curl http://localhost:8000/api/races/today

## 9. トラブルシュート
- pytest が No module named pytest → python -m pip install pytest
- printf invalid format → % エスケープ漏れ
- VOTE_MANAGER_URL 未設定 → モック保存で動作継続
