"""
Scheduler — har daqiqa kanallarni tekshiradi.
Kanal nomidan yuboradi (bot kanal admin bo'lsa avtomatik).
"""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
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
    texts  = [c for c in contents if c["media_type"] == "text"]
    photos = [c for c in contents if c["media_type"] == "photo"]
    videos = [c for c in contents if c["media_type"] == "video"]
    audios = [c for c in contents if c["media_type"] == "audio"]

    title = f"📚 <b>{lesson['lesson_number']}-dars: {lesson['title']}</b>"

    # 1 rasm bo'lsa sarlavhani caption sifatida yuboramiz
    if len(photos) == 1 and not videos and not audios:
        cap = title
        if texts:
            cap += "\n\n" + texts[0]["text_content"]
            texts = texts[1:]
        try:
            await bot.send_photo(cid, photo=photos[0]["file_id"], caption=cap)
            photos = []
        except (TelegramForbiddenError, TelegramBadRequest):
            raise
        except Exception as e:
            logger.error(f"send_photo+caption xato: {e}")
            await _msg(bot, cid, title)
    else:
        await _msg(bot, cid, title)

    for t in texts:
        await _msg(bot, cid, t["text_content"])

    if photos:
        await _media_group(bot, cid, photos, "photo")
    if videos:
        await _media_group(bot, cid, videos, "video")
    for a in audios:
        cap = a.get("text_content") or None
        await _safe(bot.send_audio, cid, audio=a["file_id"],
                    **({"caption": cap} if cap else {}))

    # Voice xabarlar
    for v in [c for c in contents if c["media_type"] == "voice"]:
        await _safe(bot.send_voice, cid, voice=v["file_id"])

    # Fayllar
    for d in [c for c in contents if c["media_type"] == "document"]:
        await _safe(bot.send_document, cid, document=d["file_id"])


async def _msg(bot, cid, text):
    await _safe(bot.send_message, cid, text=text)


async def _safe(fn, cid, **kw):
    try:
        await fn(cid, **kw)
    except (TelegramForbiddenError, TelegramBadRequest):
        raise
    except Exception as e:
        logger.error(f"{fn.__name__} xato ({cid}): {e}")


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
