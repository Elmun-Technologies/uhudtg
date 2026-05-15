"""Registration flow: /start → share phone → main menu."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Contact, Location, Message

import logging
import database as db
from keyboards import main_menu_kb, share_phone_kb, skip_kb
from locales import t
import moysklad_api

router = Router()
logger = logging.getLogger(__name__)


class RegStates(StatesGroup):
    waiting_phone = State()
    waiting_address = State()


async def _register_and_link_counterparty(telegram_id: int, name: str, phone_norm: str) -> bool:
    """
    Register user and safely link to existing MoySklad counterparty.

    Priority:
    1) Reuse counterparty id from local DB by same phone
    2) Find existing counterparty in MoySklad by phone
    3) Create new counterparty only if nothing was found

    Returns True if a brand-new counterparty was created, False if an existing one was linked.
    """
    existing_user = await db.get_user_by_phone(phone_norm)
    existing_cp_id = existing_user.get("moysklad_counterparty_id") if existing_user else None

    await db.register_user(
        telegram_id=telegram_id,
        phone=phone_norm,
        name=name,
        language="uz",
    )

    if existing_cp_id:
        await db.save_moysklad_counterparty_id(telegram_id, existing_cp_id)
        logger.info("Reused local counterparty ID %s for user %s", existing_cp_id, telegram_id)
        return False

    try:
        cp_id = await moysklad_api.find_counterparty_id_by_phone(phone_norm)
        if cp_id:
            await db.save_moysklad_counterparty_id(telegram_id, cp_id)
            logger.info("Linked existing MoySklad counterparty ID %s for user %s", cp_id, telegram_id)
            return False
    except Exception as e:
        logger.error("Error finding counterparty by phone %s: %s", phone_norm, e)

    try:
        cp_data = await moysklad_api.sync_counterparty(name, f"+{phone_norm}", telegram_id)
        cp_id = cp_data.get("id") if cp_data else None
        if cp_id:
            await db.save_moysklad_counterparty_id(telegram_id, cp_id)
            logger.info("Created and saved MoySklad counterparty ID %s for user %s", cp_id, telegram_id)
    except Exception as e:
        logger.error("Error syncing with MoySklad: %s", e)

    return True


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()

    user = await db.get_user(message.from_user.id)
    if user:
        lang = user.get("language") or "uz"
        await message.answer(t("already_registered", lang))
        if not user.get("moysklad_counterparty_id"):
            await message.answer(t("no_counterparty_for_list", lang))
        await message.answer(t("main_menu", lang), reply_markup=main_menu_kb(lang))
        return

    # New user – ask for phone
    await state.set_state(RegStates.waiting_phone)
    await message.answer(
        t("welcome_new", "uz"),
        reply_markup=share_phone_kb("uz"),
    )


async def _finish_registration(message: Message, state: FSMContext, is_new: bool) -> None:
    """After phone: ask address for new counterparties, go straight to menu for existing ones."""
    if is_new:
        await state.set_state(RegStates.waiting_address)
        await message.answer(t("ask_address", "uz"), reply_markup=skip_kb("uz"))
    else:
        await state.clear()
        await message.answer(t("registered_success", "uz"), reply_markup=main_menu_kb("uz"))


@router.message(RegStates.waiting_phone, F.contact)
async def handle_contact(message: Message, state: FSMContext) -> None:
    contact: Contact = message.contact
    phone = contact.phone_number or ""
    name = message.from_user.full_name or contact.first_name or "Mijoz"

    phone_norm = db.normalize_phone(phone)
    is_new = await _register_and_link_counterparty(message.from_user.id, name, phone_norm)
    await _finish_registration(message, state, is_new)


@router.message(RegStates.waiting_phone)
async def handle_phone_text(message: Message, state: FSMContext) -> None:
    """User typed phone manually instead of using the button."""
    text = (message.text or "").strip()
    digits = "".join(c for c in text if c.isdigit())
    if len(digits) < 9:
        await message.answer(
            "❌ Noto'g'ri format. Iltimos, tugmani bosib raqamni ulashing.",
            reply_markup=share_phone_kb("uz"),
        )
        return

    name = message.from_user.full_name or "Mijoz"
    phone_norm = db.normalize_phone(digits)
    is_new = await _register_and_link_counterparty(message.from_user.id, name, phone_norm)
    await _finish_registration(message, state, is_new)


@router.message(RegStates.waiting_address, F.location)
async def handle_reg_address_location(message: Message, state: FSMContext) -> None:
    """Address step during registration: user shared GPS location."""
    loc: Location = message.location
    address = await moysklad_api.reverse_geocode(loc.latitude, loc.longitude)
    await _save_reg_address(message.from_user.id, address)
    await state.clear()
    await message.answer(t("registered_success", "uz"), reply_markup=main_menu_kb("uz"))


@router.message(RegStates.waiting_address)
async def handle_reg_address(message: Message, state: FSMContext) -> None:
    """Address step during registration: save or skip."""
    address = (message.text or "").strip()
    skip_text = t("skip_address_btn", "uz")
    if address and address != skip_text:
        await _save_reg_address(message.from_user.id, address)
    await state.clear()
    await message.answer(t("registered_success", "uz"), reply_markup=main_menu_kb("uz"))


async def _save_reg_address(telegram_id: int, address: str) -> None:
    user = await db.get_user(telegram_id)
    if not user:
        return
    cp_id = user.get("moysklad_counterparty_id")
    if not cp_id:
        phone = (user.get("phone") or "").strip()
        if phone:
            try:
                cp_id = await moysklad_api.find_counterparty_id_by_phone(phone)
                if cp_id:
                    await db.save_moysklad_counterparty_id(telegram_id, cp_id)
            except Exception as e:
                logger.warning("_save_reg_address: counterparty lookup failed user=%s: %s", telegram_id, e)
    if cp_id:
        try:
            await moysklad_api.update_counterparty_address(cp_id, address)
        except Exception as e:
            logger.error("Error saving address during registration for user %s: %s", telegram_id, e)
