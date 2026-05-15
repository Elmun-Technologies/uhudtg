import asyncio
import moysklad_api as ms

async def check():
    url = f"{ms.MOYSKLAD_API}/entity/counterparty/c4e4ef6a-0e8b-11f1-0a80-075f0013b09c"
    try:
        resp = await ms._get(url)
        print(f"Name: {resp.get('name')}")
        print(f"Phone: {resp.get('phone')}")
        print(f"ID: {resp.get('id')}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check())
