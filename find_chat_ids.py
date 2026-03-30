"""채팅방 ID 조회 스크립트 (일회용)"""
import asyncio
import yaml
from telethon import TelegramClient

TARGET_ROOMS = [
    "늘- 봄처럼 따뜻한 투자 이야기",
    "세사모",
    "너쟁이의 성실한 추추생활",
    "예의있는 생각공유방",
    "젬백스 채팅방",
    "인슐린 터제파타이드",
    "에스패스",
    "삼천당제약",
    "삼천당",
]

async def main():
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)

    tg = cfg["telegram"]
    client = TelegramClient("find_ids_session", int(tg["api_id"]), tg["api_hash"])

    await client.start(phone=tg["phone"])

    print("\n=== 참여 중인 채팅방 목록 ===\n")
    async for dialog in client.iter_dialogs():
        title = dialog.name or ""
        chat_id = dialog.id
        # 타겟 방 이름 매칭 (부분 문자열)
        for keyword in TARGET_ROOMS:
            if keyword in title:
                print(f"[매칭] {title}")
                print(f"       ID: {chat_id}")
                print(f"       peer_id: -100{abs(chat_id)} (채널/슈퍼그룹인 경우)")
                print()
                break
        else:
            # 매칭 안 됐어도 한국어 포함된 방은 출력
            if any('\uAC00' <= c <= '\uD7A3' for c in title):
                print(f"[기타] {title}  |  ID: {chat_id}")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
