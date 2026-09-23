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
