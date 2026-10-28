import asyncio
import getpass
from pyrogram import Client

async def main():
    api_id_text = input("Telegram API_ID: ").strip()
    api_hash = getpass.getpass("Telegram API_HASH (hidden): ").strip()
    if not api_id_text.isdigit() or not api_hash:
        raise SystemExit("API_ID/API_HASH missing.")
    app = Client(
        "abhi_session_generator",
        api_id=int(api_id_text),
        api_hash=api_hash,
        in_memory=True,
    )
    try:
        await app.start()
        session = await app.export_session_string()
        print("\nSESSION STRING (keep private; do not send it to anyone):\n")
        print(session)
    finally:
        await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
