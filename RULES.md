# Keiba-EV-Tool 開発ルール

## コマンド終了の絶対ルール
- すべての Python スクリプトは末尾で `import os; os._exit(0)` を実行する
- 特に libsql_client / aiohttp を使うスクリプトは必須
- `sys.exit(0)` や `atexit.register` だけでは aiohttp セッションが残ってハングする
- `python3 - <<'PY'` で実行する場合も最終行に `os._exit(0)` を入れる

## 出力ルール
- 進捗は print(..., flush=True) を使う
- `| tail -N` でパイプするとプロセス終了まで何も見えないので、進捗確認時はパイプしない

## SWキャッシュ更新の絶対ルール
- フロント（frontend/*.js, *.css, *.html）を変更したら必ず:
  1. frontend/sw.js の CACHE_NAME をインクリメント（v14 → v15 → ...）
  2. frontend/index.html の app.js?v=N も同じ番号に更新
- 片方だけ忘れるとキャッシュが効いて変更が反映されない
- コミット前に `grep CACHE_NAME frontend/sw.js` と `grep app.js frontend/index.html` で確認する

## スクレイピングの性能ルール
- 複数URL/レースを取得する処理は最初から asyncio + セマフォで並列化する
- 逐次処理で書かない。並列度8〜12が目安
- 1レース内の複数券種も asyncio.gather で並列化
- 待機は1リクエスト0.5秒（並列前提）、券種間は不要

## Mock禁止の絶対ルール（最重要）
### 過去に私が犯した根本的失敗
1. 「動けばいい」思考: mock で見た目が動くと「正しい」と錯覚
2. 手間回避: 実データ取得より mock を優先
3. 検証の意味を理解していなかった: mock 予想を実オッズで検証しても無意味
4. 自己解釈: 「動かす」要求を「実データで」と解釈せず mock で済ませた
5. 確認不足: 「このデータは実データか?」を毎回自問しなかった

### 対策（毎回守る）
- 作業開始前に必ず自問: 「このデータは実データか、mock か」
- mock を使う場合、なぜ mock でよいか・いつ実データ化するかを明示
- 予想・検証・収益のフローで mock を使わない
- 判断基準は常に「実運用のROIを正しく推定できるか」
- 「動いているように見える」≠「正しい」

### 具体的に破棄すべき mock
- `ev_calc.py` の `mock_odds` — 予想ページ・検証ページの両方で使用中
- `race_fetcher.py` の `MockAdapter` — 本番データなし時に偽レースを返す
- `result_fetcher.py` の Mock 結果
- `vote_manager.py` の `mock_saved`
- `daily_fetch.py` は単勝のみ保存 → 全券種必要
