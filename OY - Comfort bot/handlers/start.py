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


async def _register_and_link_counterparty(
    telegram_id: int, name: str, phone_norm: str
) -> tuple[str, bool]:
    """
    Register user and safely link to existing MoySklad counterparty.

    Returns (status, needs_address):
      status:
        "new"      — new counterparty was created in MoySklad
        "existing" — linked to an existing MoySklad counterparty
        "failed"   — MoySklad did not respond / counterparty not linked
      needs_address:
        True  — address is empty in MoySklad → ask client to share it
        False — address already filled OR registration failed
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
        try:
            cp = await moysklad_api.fetch_counterparty(
                f"{moysklad_api.MOYSKLAD_API}/entity/counterparty/{existing_cp_id}"
            )
            has_addr = bool((cp.get("actualAddress") or "").strip())
            return ("existing", not has_addr)
        except Exception as e:
            logger.error("Fetch counterparty %s failed: %s", existing_cp_id, e)
            return ("existing", True)

    try:
        cp_info = await moysklad_api.find_counterparty_by_phone(phone_norm)
        if cp_info and cp_info.get("id"):
            cp_id = cp_info["id"]
            await db.save_moysklad_counterparty_id(telegram_id, cp_id)
            logger.info(
                "Linked existing MoySklad counterparty %s (%s) for user %s",
                cp_id, cp_info.get("name"), telegram_id,
            )
            has_addr = bool(cp_info.get("actualAddress"))
            return ("existing", not has_addr)
    except Exception as e:
        logger.error("Error finding counterparty by phone %s: %s", phone_norm, e)
        return ("failed", False)

    try:
        cp_data = await moysklad_api.sync_counterparty(name, f"+{phone_norm}", telegram_id)
        cp_id = cp_data.get("id") if cp_data else None
        if cp_id:
            await db.save_moysklad_counterparty_id(telegram_id, cp_id)
            logger.info(
                "Created and saved MoySklad counterparty %s for user %s", cp_id, telegram_id
            )
            return ("new", True)
    except Exception as e:
        logger.error("Error syncing with MoySklad: %s", e)

    return ("failed", False)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()

    user = await db.get_user(message.from_user.id)
    if user:
        lang = user["language"]
        await message.answer(t("already_registered", lang))
        await message.answer(t("main_menu", lang), reply_markup=main_menu_kb(lang))
        return

    # New user – ask for phone
    await state.set_state(RegStates.waiting_phone)
    await message.answer(
        t("welcome_new", "uz"),
        reply_markup=share_phone_kb("uz"),
    )


async def _finish_registration(
    message: Message, state: FSMContext, status: str, needs_address: bool
) -> None:
    """After phone:
      - failed   → show error and clear state so user can /start again
      - existing → say "you are already registered" + ask address if missing
      - new      → "registered successfully" + ask address
    """
    if status == "failed":
        await state.clear()
        await message.answer(t("registration_ms_error", "uz"), reply_markup=main_menu_kb("uz"))
        return

    if status == "existing":
        if needs_address:
            await message.answer(t("existing_client_found", "uz"))
            await state.set_state(RegStates.waiting_address)
            await message.answer(t("ask_address", "uz"), reply_markup=skip_kb("uz"))
        else:
            await state.clear()
            await message.answer(t("registered_success", "uz"), reply_markup=main_menu_kb("uz"))
        return

    # status == "new"
    await message.answer(t("registered_success", "uz"))
    if needs_address:
        await state.set_state(RegStates.waiting_address)
        await message.answer(t("ask_address", "uz"), reply_markup=skip_kb("uz"))
    else:
        await state.clear()
        await message.answer(t("main_menu", "uz"), reply_markup=main_menu_kb("uz"))


@router.message(RegStates.waiting_phone, F.contact)
async def handle_contact(message: Message, state: FSMContext) -> None:
    contact: Contact = message.contact
    phone = contact.phone_number or ""
    name = message.from_user.full_name or contact.first_name or "Mijoz"

    phone_norm = db.normalize_phone(phone)
    status, needs_address = await _register_and_link_counterparty(
        message.from_user.id, name, phone_norm
    )
    await _finish_registration(message, state, status, needs_address)


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
    status, needs_address = await _register_and_link_counterparty(
        message.from_user.id, name, phone_norm
    )
    await _finish_registration(message, state, status, needs_address)


@router.message(RegStates.waiting_address, F.location)
async def handle_reg_address_location(message: Message, state: FSMContext) -> None:
    """Address step during registration: user shared GPS location."""
    loc: Location = message.location
    address = await moysklad_api.reverse_geocode(loc.latitude, loc.longitude)
    saved = await _save_reg_address(message.from_user.id, address)
    await state.clear()
    if saved:
        await message.answer(t("address_saved", "uz"), reply_markup=main_menu_kb("uz"))
    else:
        await message.answer(t("address_save_error", "uz"), reply_markup=main_menu_kb("uz"))


@router.message(RegStates.waiting_address)
async def handle_reg_address(message: Message, state: FSMContext) -> None:
    """Address step during registration: save or skip."""
    address = (message.text or "").strip()
    skip_text = t("skip_address_btn", "uz")

    if not address or address == skip_text:
        await state.clear()
        await message.answer(t("registered_success", "uz"), reply_markup=main_menu_kb("uz"))
        return

    saved = await _save_reg_address(message.from_user.id, address)
    await state.clear()
    if saved:
        await message.answer(t("address_saved", "uz"), reply_markup=main_menu_kb("uz"))
    else:
        await message.answer(t("address_save_error", "uz"), reply_markup=main_menu_kb("uz"))


async def _save_reg_address(telegram_id: int, address: str) -> bool:
    """Returns True on success, False if MoySklad update failed."""
    user = await db.get_user(telegram_id)
    cp_id = user.get("moysklad_counterparty_id") if user else None
    if not cp_id:
        logger.warning("No counterparty linked for user %s; address not saved", telegram_id)
        return False
    try:
        await moysklad_api.update_counterparty_address(cp_id, address)
        return True
    except Exception as e:
        logger.error("Error saving address during registration for user %s: %s", telegram_id, e)
        return False
