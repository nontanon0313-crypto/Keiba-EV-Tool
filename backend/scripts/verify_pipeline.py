"""パイプライン少数検証。取得→パース→予想→検証を実データで確認。"""
import os
import sys
import time
from datetime import datetime

from backend.scraper.oddspark_keiba import (
    fetch_race_list, fetch_one_day, fetch_one_day_detail,
    fetch_shutuba, fetch_odds_all_full, fetch_result,
)
from backend.app.services import race_store, odds_store
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import build_mixed_bets, _candidates
from backend.app.models.schemas import Race, Runner


def race_obj(rid, payload):
    runners = []
    for r in payload.get("runners", []):
        try:
            runners.append(Runner(
                horse_number=int(r.get("horse_number", 0)),
                frame_number=int(r.get("frame_number", 0)),
                horse_id="", horse_name=r.get("horse_name", ""),
                jockey=r.get("jockey", ""), trainer="",
                weight=float(r.get("weight", 55.0) or 55.0),
                odds_win=float(r.get("odds_win", 50.0) or 50.0),
                popularity=r.get("popularity"),
            ))
        except (ValueError, TypeError):
            continue
    surf = payload.get("surface") or "ダート"
    if surf not in ("芝", "ダート", "障害"): surf = "ダート"
    return Race(
        race_id=rid, venue=payload.get("venue", ""), date=payload.get("date", ""),
        race_number=int(payload.get("race_number", 0)),
        start_at=datetime.now(), deadline_at=datetime.now(),
        surface=surf, distance=int(payload.get("distance", 0) or 0), runners=runners,
    )


def verify_one(date, track_cd, sponsor_cd, race_nb):
    rid = f"nar-{date}-{track_cd}-{race_nb}"
    print(f"\n{'='*60}")
    print(f"[{rid}] 検証開始")
    print(f"{'='*60}")
    t0 = time.time()

    # 1. 出走表
    try:
        sh = fetch_shutuba(date, track_cd, sponsor_cd, race_nb)
        if not sh:
            print("  ✗ 出走表 取得失敗")
            return False
        print(f"  ✓ 出走表: {len(sh['runners'])}頭")
        # 馬番の連続性チェック
        nums = sorted(r["horse_number"] for r in sh["runners"])
        expected = list(range(1, max(nums) + 1)) if nums else []
        missing = set(expected) - set(nums)
        if missing:
            print(f"    ✗ 馬番欠落: {sorted(missing)}")
        else:
            print(f"    ✓ 馬番連続: 1〜{max(nums)}")
    except Exception as e:
        print(f"  ✗ 出走表 ERROR: {e}")
        return False

    # 2. 結果
    try:
        res = fetch_result(date, track_cd, sponsor_cd, race_nb)
        if not res or not res.get("finish_order"):
            print("  ✗ 結果 取得失敗")
            return False
        print(f"  ✓ 結果: 着順={res['finish_order']}  結果頭数={len(res.get('runners', []))}")
    except Exception as e:
        print(f"  ✗ 結果 ERROR: {e}")
        return False

    # 3. 全券種オッズ
    try:
        num_runners = len(sh["runners"])
        odds = fetch_odds_all_full(date, track_cd, sponsor_cd, race_nb, num_runners)
        for t, m in odds.items():
            print(f"  ✓ {t}: {len(m) if m else 0}件")
    except Exception as e:
        print(f"  ✗ オッズ ERROR: {e}")
        return False

    # 4. 保存
    try:
        payload = {
            "race_id": rid,
            "venue": res.get("venue") or "",
            "date": f"{date[:4]}-{date[4:6]}-{date[6:8]}",
            "race_number": int(race_nb),
            "start_at": datetime.now().isoformat(),
            "deadline_at": datetime.now().isoformat(),
            "surface": res.get("surface", "ダート"),
            "distance": res.get("distance", 0),
            "runners": sh["runners"],
            "finish_order": res["finish_order"],
            "result_runners": res.get("runners", []),
            "payouts": res.get("payouts", {}),
            "source": "verify",
            "track_cd": track_cd, "sponsor_cd": sponsor_cd, "race_nb": race_nb,
        }
        race_store.save_race(rid, payload)
        odds_store.save_odds(rid, odds)
        print(f"  ✓ Turso保存完了")
    except Exception as e:
        print(f"  ✗ 保存 ERROR: {e}")
        return False

    # 5. 予想 → 買い目
    try:
        race = race_obj(rid, payload)
        pred = predict_race(race)
        print(f"  ✓ 予想: 単勝上位3={[(p.horse_number, round(p.win_prob,4)) for p in pred.probabilities[:3]]}")
        # 馬連確率合計
        q = _candidates(pred, "quinella")
        print(f"    馬連{len(q)}件 合計={sum(p for _, p in q)*100:.2f}%")
        # 実オッズで馬連EV計算
        real_q = odds.get("quinella") or {}
        in_range = sum(1 for k, v in real_q.items() if (v.get("odds") or 0) >= 30)
        print(f"    馬連実オッズ取得={len(real_q)}件 / 30倍以上={in_range}件")
        # 実際に買い目が出るか (min_odds=0で試す)
        bets = build_mixed_bets(race, pred, odds_min=0, ev_min=0)
        print(f"    買い目(全条件クリア): {len(bets)}件")
        for b in bets[:3]:
            print(f"      {b.type} {b.combination} odds={b.odds} ev={b.ev:.3f}")
    except Exception as e:
        print(f"  ✗ 予想 ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

    elapsed = time.time() - t0
    print(f"  ─ 所要: {elapsed:.1f}秒")
    return True


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else "20240115"
    # その日の開催場1つを取得
    venues = fetch_race_list(date)
    if not venues:
        print(f"{date}: 開催なし")
        os._exit(1)
    track_cd = venues[0]["track_cd"]
    sponsor_cd = venues[0]["sponsor_cd"]
    print(f"検証対象: {date} track={track_cd} sponsor={sponsor_cd}")

    races = fetch_one_day(track_cd, sponsor_cd, date)
    if not races:
        print("レース一覧取得失敗")
        os._exit(1)
    print(f"レース数: {len(races)}")

    # 先頭5レースを検証
    target = races[:5]
    success = 0
    t0 = time.time()
    for r in target:
        if verify_one(date, track_cd, sponsor_cd, r["race_nb"]):
            success += 1
    total = time.time() - t0
    print(f"\n{'='*60}")
    print(f"検証完了: {success}/{len(target)}成功")
    print(f"総所要: {total:.1f}秒 / 1レース平均 {total/len(target):.1f}秒")
    est_5000 = (total / len(target)) * 5000 / 60
    print(f"5000件推定: {est_5000:.0f}分 ({est_5000/60:.1f}時間)")
    os._exit(0)


if __name__ == "__main__":
    main()
