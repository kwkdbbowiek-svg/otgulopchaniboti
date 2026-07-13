"""
Scheduler — har daqiqa kanallarni tekshiradi.
Kanal nomidan yuboradi (bot kanal admin bo'lsa avtomatik).
"""
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InputMediaPhoto, InputMediaVideo
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import db

logger = logging.getLogger(__name__)
UZ = ZoneInfo("Asia/Tashkent")
_busy: set = set()  # qayta yuborishdan himoya


def now_uz() -> datetime:
    """O'zbekiston vaqtida naive datetime (DB uchun)."""
    return datetime.now(UZ).replace(tzinfo=None)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    s = AsyncIOScheduler(timezone="Asia/Tashkent")
    s.add_job(tick, "interval", minutes=1, args=[bot],
              id="tick", replace_existing=True, max_instances=1, coalesce=True)
    return s


async def tick(bot: Bot):
    try:
        channels = await db.get_due_channels(now_uz())
        for ch in channels:
            await send_channel(bot, ch)
    except Exception as e:
        logger.error(f"tick xato: {e}", exc_info=True)


async def send_channel(bot: Bot, ch):
    cid = ch["channel_id"]
    if cid in _busy:
        return
    _busy.add(cid)
    try:
        num      = ch["current_lesson_number"]
        course   = ch["course_id"]
        interval = ch["interval_hours"]

        # Avval bazani yangilaymiz — qayta yuborishni oldini olish
        await db.advance_channel(cid, num + 1, now_uz() + timedelta(hours=interval))

        lesson = await db.get_lesson_by_num(course, num)
        if not lesson:
            total = await db.get_total_lessons(course)
            if num > total > 0:
                logger.info(f"Kanal {cid}: kurs tugadi ({total} dars).")
                await db.deactivate_channel(cid)
                try:
                    await bot.send_message(cid,
                        "🎓 <b>Kurs tugadi!</b> Barcha darslar yuborildi. Tabriklaymiz! 🎉")
                except Exception:
                    pass
            return

        contents = await db.get_contents(lesson["id"])
        if not contents:
            logger.warning(f"Kanal {cid}: {num}-dars bo'sh.")
            return

        await deliver(bot, cid, lesson, contents)
        logger.info(f"Kanal {cid}: {num}-dars → '{ch['course_name']}' ✅")

    except TelegramForbiddenError as e:
        logger.error(f"Kanal {cid}: forbidden → deaktiv. {e}")
        await db.deactivate_channel(cid)
    except TelegramBadRequest as e:
        logger.error(f"Kanal {cid}: bad_request → {e}")
        if any(x in str(e).lower() for x in ("not found", "kicked", "not enough rights")):
            await db.deactivate_channel(cid)
    except Exception as e:
        logger.error(f"Kanal {cid}: xato → {e}", exc_info=True)
    finally:
        _busy.discard(cid)


async def deliver(bot: Bot, cid: int, lesson, contents):
    """
    Dars kontent tartibini saqlagan holda yuboradi.
    Har xabar orasida 1s delay — flood limitdan himoya.
    Audio/rasm/video o'z text_content'ini caption sifatida ishlatadi.
    """
    title = f"📚 <b>{lesson['lesson_number']}-dars: {lesson['title']}</b>"

    # Sarlavha xabarini yuborish
    await _safe(bot.send_message, cid, text=title)

    # Kontentni order_index tartibida yuborish
    for c in contents:
        await asyncio.sleep(1)          # flood limitdan himoya
        mt  = c["media_type"]
        cap = c.get("text_content") or None

        if mt == "text":
            txt = (c.get("text_content") or "").strip()
            if txt:
                await _safe(bot.send_message, cid, text=txt)

        elif mt == "audio":
            await _safe(bot.send_audio, cid, audio=c["file_id"],
                        **({"caption": cap} if cap else {}))

        elif mt == "voice":
            await _safe(bot.send_voice, cid, voice=c["file_id"],
                        **({"caption": cap} if cap else {}))

        elif mt == "photo":
            await _safe(bot.send_photo, cid, photo=c["file_id"],
                        **({"caption": cap} if cap else {}))

        elif mt == "video":
            await _safe(bot.send_video, cid, video=c["file_id"],
                        **({"caption": cap} if cap else {}))

        elif mt == "document":
            await _safe(bot.send_document, cid, document=c["file_id"],
                        **({"caption": cap} if cap else {}))


async def _msg(bot, cid, text):
    await _safe(bot.send_message, cid, text=text)


async def _safe(fn, cid, **kw):
    """Xabar yuborish — flood limitga duch kelsa kutib qayta urinadi."""
    for attempt in range(5):
        try:
            await fn(cid, **kw)
            return
        except TelegramRetryAfter as e:
            wait = e.retry_after + 1
            logger.warning(f"{fn.__name__} flood limit — {wait}s kutilmoqda...")
            await asyncio.sleep(wait)
        except (TelegramForbiddenError, TelegramBadRequest):
            raise
        except Exception as e:
            logger.error(f"{fn.__name__} xato ({cid}): {e}")
            return
    logger.error(f"{fn.__name__} — 5 urinishdan keyin ham yuborilmadi ({cid})")


async def _media_group(bot: Bot, cid: int, items: list, kind: str):
    for i in range(0, len(items), 10):
        chunk = items[i:i+10]
        media = []
        for x in chunk:
            try:
                media.append(InputMediaPhoto(media=x["file_id"]) if kind == "photo"
                             else InputMediaVideo(media=x["file_id"]))
            except Exception as e:
                logger.error(f"media obj xato: {e}")
        if not media:
            continue
        try:
            await bot.send_media_group(cid, media=media)
        except (TelegramForbiddenError, TelegramBadRequest):
            raise
        except Exception as e:
            logger.warning(f"media_group xato, alohida yuborilmoqda: {e}")
            for x in chunk:
                try:
                    if kind == "photo":
                        await bot.send_photo(cid, photo=x["file_id"])
                    else:
                        await bot.send_video(cid, video=x["file_id"])
                except (TelegramForbiddenError, TelegramBadRequest):
                    raise
                except Exception as e2:
                    logger.error(f"alohida {kind} xato: {e2}")
