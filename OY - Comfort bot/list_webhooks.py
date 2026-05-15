import asyncio
import moysklad_api as ms

async def main():
    url = f"{ms.MOYSKLAD_API}/entity/webhook"
    try:
        resp = await ms._get(url)
        webhooks = resp.get("rows", [])
        if not webhooks:
            print("No webhooks configured in MoySklad.")
        else:
            for w in webhooks:
                print(f"Webhook {w.get('action')} on {w.get('entityType')}: {w.get('url')} (Enabled: {w.get('enabled')})")
    except Exception as e:
        print(f"Error fetching webhooks: {e}")

if __name__ == "__main__":
    asyncio.run(main())
