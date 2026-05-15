import asyncio
import moysklad_api as ms
import json

async def check():
    url = f"{ms.MOYSKLAD_API}/entity/counterparty"
    try:
        resp = await ms._get(url, params={"search": "998934564000"})
        rows = resp.get("rows", [])
        if not rows:
            print("Not found by phone.")
        for r in rows:
            print(f"Name: {r.get('name')}")
            print(f"Phone: {r.get('phone')}")
            print(f"ExternalCode: {r.get('externalCode')}")
            print(f"ID: {r.get('id')}")
            print("---")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check())
