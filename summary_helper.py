"""
대화 요약 헬퍼 CLI — Claude Code가 요약 결과를 DB에 저장하기 위한 도구.

사용법:
    python summary_helper.py status                     # 미요약 현황
    python summary_helper.py export <room_link> <date>   # 메시지 출력 (요약용)
    python summary_helper.py export-all                  # 모든 미요약 메시지 날짜별 출력
    python summary_helper.py save <json_file>            # JSON 파일에서 요약 일괄 저장
    python summary_helper.py save-one <room_link> <date> <summary> # 단건 저장
    python summary_helper.py verify                      # 저장 결과 검증
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from database import Database

DB_PATH = str(Path(__file__).parent / "data" / "telegram.db")


def cmd_status(args):
    """미요약 conversation 메시지 현황 출력"""
    db = Database(DB_PATH)
    with db._connect() as conn:
        # 전체 통계
        row = conn.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN summarized=1 THEN 1 ELSE 0 END) as done,
                      SUM(CASE WHEN summarized=0 THEN 1 ELSE 0 END) as pending
               FROM messages WHERE room_type='conversation' AND is_forwarded=0"""
        ).fetchone()
        print(f"전체: {row['total']}건  요약완료: {row['done']}건  미요약: {row['pending']}건")
        print()

        if row["pending"] == 0:
            print("미요약 메시지가 없습니다.")
            return

        # 방/날짜별 미요약 현황
        rows = conn.execute(
            """SELECT room_link, room_title, DATE(timestamp) as dt, COUNT(*) as cnt
               FROM messages
               WHERE room_type='conversation' AND summarized=0 AND is_forwarded=0
               GROUP BY room_link, dt ORDER BY room_link, dt"""
        ).fetchall()

        current_room = None
        for r in rows:
            if r["room_link"] != current_room:
                current_room = r["room_link"]
                title = r["room_title"] or r["room_link"]
                print(f"── {title} ({r['room_link']}) ──")
            print(f"  {r['dt']}  {r['cnt']:>5}건")


def cmd_export(args):
    """특정 방/날짜의 미요약 메시지를 출력"""
    db = Database(DB_PATH)
    msgs = db.get_unsummarized_chat_messages(args.room_link, args.date)
    if not msgs:
        print(f"미요약 메시지 없음: {args.room_link} / {args.date}")
        return

    limit = args.limit or len(msgs)
    if args.sample and len(msgs) > limit:
        # 앞/뒤/중간 샘플링
        n = limit // 3
        sample = msgs[:n] + msgs[len(msgs)//2 - n//2 : len(msgs)//2 + n//2] + msgs[-n:]
        msgs_to_show = sample
    else:
        msgs_to_show = msgs[:limit]

    print(f"=== {args.room_link} / {args.date} ({len(msgs)}건, 출력 {len(msgs_to_show)}건) ===")
    for m in msgs_to_show:
        ts = m["timestamp"][:16] if m.get("timestamp") else "?"
        text = m.get("text", "")
        if args.truncate:
            text = text[:args.truncate]
        print(f"[{ts}] {text}")

    # message_ids 출력
    all_ids = [m["message_id"] for m in db.get_unsummarized_chat_messages(args.room_link, args.date)]
    print(f"\nmessage_ids ({len(all_ids)}건): {json.dumps(all_ids)}")


def cmd_export_all(args):
    """모든 미요약 메시지를 방/날짜별로 출력"""
    db = Database(DB_PATH)
    with db._connect() as conn:
        groups = conn.execute(
            """SELECT room_link, room_title, DATE(timestamp) as dt, COUNT(*) as cnt
               FROM messages
               WHERE room_type='conversation' AND summarized=0 AND is_forwarded=0
               GROUP BY room_link, dt ORDER BY room_link, dt"""
        ).fetchall()

    if not groups:
        print("미요약 메시지가 없습니다.")
        return

    limit = args.limit or 100
    for g in groups:
        msgs = db.get_unsummarized_chat_messages(g["room_link"], g["dt"])
        title = g["room_title"] or g["room_link"]
        print(f"\n=== [{title}] {g['dt']} ({len(msgs)}건) ===")

        if len(msgs) <= limit:
            show = msgs
        else:
            # 앞 40% + 뒤 40% 샘플
            n = limit // 2
            show = msgs[:n] + msgs[-n:]

        for m in show:
            ts = m["timestamp"][:16] if m.get("timestamp") else "?"
            text = (m.get("text", "") or "")[:200]
            print(f"[{ts}] {text}")

        all_ids = [m["message_id"] for m in msgs]
        print(f"message_ids: {json.dumps(all_ids)}")


def cmd_save(args):
    """JSON 파일에서 요약 일괄 저장

    JSON 형식:
    [
        {
            "room_link": "-100xxx",
            "room_title": "방 이름",
            "date": "2026-04-08",
            "msg_ids": [1, 2, 3],
            "summary": "- 요약 내용"
        },
        ...
    ]
    """
    data = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    db = Database(DB_PATH)
    ok = 0
    fail = 0
    for s in data:
        try:
            db.save_summary(
                s["room_link"], s.get("room_title"), s["summary"],
                s["msg_ids"], s["date"],
            )
            db.mark_messages_summarized(s["msg_ids"], s["room_link"])
            print(f"OK: [{s.get('room_title', s['room_link'])}] {s['date']} — {len(s['msg_ids'])}건")
            ok += 1
        except Exception as e:
            print(f"FAIL: [{s.get('room_title', s['room_link'])}] {s['date']} — {e}")
            fail += 1
    print(f"\n완료: 성공 {ok}건 / 실패 {fail}건")


def cmd_save_one(args):
    """단건 요약 저장"""
    db = Database(DB_PATH)

    # message_ids 조회
    msgs = db.get_unsummarized_chat_messages(args.room_link, args.date)
    if not msgs:
        print(f"미요약 메시지 없음: {args.room_link} / {args.date}")
        return

    msg_ids = [m["message_id"] for m in msgs]
    room_title = msgs[0].get("room_title")

    try:
        db.save_summary(args.room_link, room_title, args.summary, msg_ids, args.date)
        db.mark_messages_summarized(msg_ids, args.room_link)
        print(f"OK: [{room_title or args.room_link}] {args.date} — {len(msg_ids)}건")
    except Exception as e:
        print(f"FAIL: {e}")


def cmd_verify(args):
    """요약 저장 결과 검증"""
    db = Database(DB_PATH)
    with db._connect() as conn:
        # 전체 통계
        row = conn.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN summarized=1 THEN 1 ELSE 0 END) as done,
                      SUM(CASE WHEN summarized=0 THEN 1 ELSE 0 END) as pending
               FROM messages WHERE room_type='conversation' AND is_forwarded=0"""
        ).fetchone()
        print(f"대화 메시지: {row['total']}건 (요약완료: {row['done']} / 미요약: {row['pending']})")

        # 요약 건수
        summary_count = conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
        print(f"요약 레코드: {summary_count}건")

        # 최근 요약 5건
        recent = conn.execute(
            """SELECT room_title, date, LENGTH(summary) as len, created_at
               FROM summaries ORDER BY id DESC LIMIT 5"""
        ).fetchall()
        if recent:
            print("\n최근 요약:")
            for r in recent:
                print(f"  [{r['room_title']}] {r['date']}  {r['len']}자  ({r['created_at']})")


def main():
    parser = argparse.ArgumentParser(description="Hermes 대화 요약 헬퍼")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="미요약 현황")

    p_export = sub.add_parser("export", help="메시지 출력")
    p_export.add_argument("room_link")
    p_export.add_argument("date")
    p_export.add_argument("--limit", type=int, help="출력 제한")
    p_export.add_argument("--truncate", type=int, default=200, help="텍스트 길이 제한")
    p_export.add_argument("--sample", action="store_true", help="대량 시 앞/중/뒤 샘플링")

    p_all = sub.add_parser("export-all", help="모든 미요약 메시지 출력")
    p_all.add_argument("--limit", type=int, default=100, help="날짜당 출력 제한")

    p_save = sub.add_parser("save", help="JSON에서 요약 일괄 저장")
    p_save.add_argument("json_file")

    p_one = sub.add_parser("save-one", help="단건 요약 저장")
    p_one.add_argument("room_link")
    p_one.add_argument("date")
    p_one.add_argument("summary")

    sub.add_parser("verify", help="저장 결과 검증")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    {
        "status": cmd_status,
        "export": cmd_export,
        "export-all": cmd_export_all,
        "save": cmd_save,
        "save-one": cmd_save_one,
        "verify": cmd_verify,
    }[args.command](args)


if __name__ == "__main__":
    main()
