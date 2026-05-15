import asyncio
import moysklad_api as ms
from config import WEBHOOK_HOST, WEBHOOK_PATH, WEBHOOK_SECRET

async def setup_webhooks():
    url = f"{ms.MOYSKLAD_API}/entity/webhook"
    target_url = f"{WEBHOOK_HOST}{WEBHOOK_PATH}?secret={WEBHOOK_SECRET}"
    
    webhooks_to_create = [
        {"action": "CREATE", "entityType": "customerorder"},
        {"action": "CREATE", "entityType": "demand"},
        {"action": "CREATE", "entityType": "salesreturn"},
        {"action": "CREATE", "entityType": "cashin"},
        {"action": "CREATE", "entityType": "paymentin"},
        {"action": "CREATE", "entityType": "cashout"},
        {"action": "CREATE", "entityType": "paymentout"},
        {"action": "CREATE", "entityType": "supply"},
        {"action": "CREATE", "entityType": "purchasereturn"},
    ]
    
    print(f"Setting up webhooks to point to: {target_url}\n")
    
    for w in webhooks_to_create:
        data = {
            "url": target_url,
            "action": w["action"],
            "entityType": w["entityType"]
        }
        try:
            resp = await ms._post(url, json_data=data)
            print(f"✅ Created webhook for {w['entityType']} {w['action']}")
        except Exception as e:
            print(f"❌ Failed to create webhook for {w['entityType']} {w['action']}: {e}")

if __name__ == "__main__":
    asyncio.run(setup_webhooks())
