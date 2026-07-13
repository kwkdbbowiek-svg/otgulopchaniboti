"""
Kanal handler — bot kanalga admin sifatida qo'shilganda tekshiradi.
Ruxsatsiz kanal bo'lsa bot chiqib ketadi.
"""
import logging

from aiogram import Bot, Router
from aiogram.filters import ChatMemberUpdatedFilter, IS_NOT_MEMBER, ADMINISTRATOR
from aiogram.types import ChatMemberUpdated

from database import db

logger = logging.getLogger(__name__)
router = Router()


@router.my_chat_member(
    ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> ADMINISTRATOR)
)
async def bot_added_to_channel(event: ChatMemberUpdated, bot: Bot):
    """Bot kanalga admin sifatida qo'shilganda."""
    if event.chat.type != "channel":
        return

    channel_id    = event.chat.id
    channel_title = event.chat.title or str(channel_id)

    is_auth = await db.get_channel(channel_id)

    if not is_auth:
        logger.warning(f"Ruxsatsiz kanal: {channel_title} ({channel_id}) — chiqilmoqda")
        try:
            await bot.leave_chat(channel_id)
        except Exception as e:
            logger.error(f"Kanaldan chiqishda xato: {e}")
    else:
        logger.info(f"Ruxsat etilgan kanalga qo'shildi: {channel_title} ({channel_id})")
