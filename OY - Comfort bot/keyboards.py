from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from locales import t

remove_keyboard = ReplyKeyboardRemove()


def main_menu_kb(lang: str = "uz") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=t("btn_orders", lang)),
                KeyboardButton(text=t("btn_balance", lang)),
            ],
            [
                KeyboardButton(text=t("btn_report", lang)),
                KeyboardButton(text=t("btn_language", lang)),
            ],
        ],
        resize_keyboard=True,
    )


def share_phone_kb(lang: str = "uz") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("share_phone_btn", lang), request_contact=True)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def report_period_kb(lang: str = "uz") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=t("btn_daily", lang)),
                KeyboardButton(text=t("btn_weekly", lang)),
                KeyboardButton(text=t("btn_monthly", lang)),
            ],
            [
                KeyboardButton(text=t("btn_quarterly", lang)),
                KeyboardButton(text=t("btn_yearly", lang)),
                KeyboardButton(text=t("btn_all", lang)),
            ],
            [KeyboardButton(text=t("btn_back", lang))],
        ],
        resize_keyboard=True,
    )


def report_nav_kb(lang: str = "uz") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=t("btn_prev", lang)),
                KeyboardButton(text=t("btn_current", lang)),
                KeyboardButton(text=t("btn_next", lang)),
            ],
            [KeyboardButton(text=t("btn_back", lang))],
        ],
        resize_keyboard=True,
    )


def language_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇺🇿 O'zbek", callback_data="lang:uz"),
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
            ]
        ]
    )
