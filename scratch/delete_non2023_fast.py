"""2023年以外の scraped_races / scraped_odds を即削除。"""
import os
import libsql_client


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not (url and token):
        print("[NG] TURSO_URL / TURSO_TOKEN 未設定")
        return
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    for tbl in ("scraped_races", "scraped_odds"):
        before = client.execute(f"SELECT COUNT(*) FROM {tbl}").rows[0][0]
        client.execute(f"DELETE FROM {tbl} WHERE race_id NOT LIKE 'nar-2023%'")
        after = client.execute(f"SELECT COUNT(*) FROM {tbl}").rows[0][0]
        remain_non2023 = client.execute(
            f"SELECT COUNT(*) FROM {tbl} WHERE race_id NOT LIKE 'nar-2023%'"
        ).rows[0][0]
        print(f"{tbl}: before={before} after={after} non2023_remain={remain_non2023}")

    try:
        client.close()
    except Exception:
        pass


main()
import os
os._exit(0)
