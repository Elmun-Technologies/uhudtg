"""Entry point: starts the Telegram bot + MoySklad webhook server."""

import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import database as db
import moysklad_api as moysklad
import webhook_server
import scheduler
from config import BOT_TOKEN, WEBHOOK_PORT
from handlers import start, menu

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

async def main() -> None:
    # Init database
    await db.init_db()
    logger.info("Database initialised.")

    # Create bot & dispatcher
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(menu.router)

    # Create aiohttp app for MoySklad webhooks
    web_app = web.Application()
    webhook_server.setup(web_app, bot)

    # Run both concurrently
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)
    await site.start()
    logger.info("Webhook server listening on port %s", WEBHOOK_PORT)

    daily_report_task = asyncio.create_task(scheduler.run_daily_report_loop(bot))

    logger.info("Starting bot polling…")
    try:
        # Aniq ro'yxat: resolve_used_update_types ba'zi muhitlarda tor qolishi mumkin
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
        )
    finally:
        daily_report_task.cancel()
        try:
            await daily_report_task
        except (asyncio.CancelledError, Exception):
            pass
        await moysklad.close_moysklad_http()
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
