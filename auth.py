"""텔레그램 최초 인증 스크립트 - 한 번만 실행하면 됩니다."""
import asyncio
import yaml
from telethon import TelegramClient

async def main():
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    tg = cfg["telegram"]
    client = TelegramClient("hermes", int(tg["api_id"]), tg["api_hash"])
    await client.start(phone=tg["phone"])
    me = await client.get_me()
    print(f"\n인증 성공! {me.first_name} ({me.phone}) 로 로그인됐습니다.")
    print("hermes.session 파일이 생성됐습니다. 이제 main.py를 실행하세요.")
    await client.disconnect()

asyncio.run(main())
