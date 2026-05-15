import asyncio
import database as db
import moysklad_api

async def main():
    print("Starting sync...")
    users = await db.get_all_users()
    for user in users:
        phone_norm = db.normalize_phone(user["phone"])
        print(f"Syncing {user['name']} (+{phone_norm})... ", end="")
        try:
            await moysklad_api.sync_counterparty(user["name"], f"+{phone_norm}", user["telegram_id"])
            print("OK")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
