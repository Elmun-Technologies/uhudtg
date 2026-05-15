import asyncio
import moysklad_api as ms

async def list_attributes():
    url = f"{ms.MOYSKLAD_API}/entity/counterparty/metadata/attributes"
    try:
        resp = await ms._get(url)
        print("Resp type:", type(resp))
        print("Resp:", resp)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(list_attributes())
