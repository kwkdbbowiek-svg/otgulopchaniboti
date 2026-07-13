"""Admin panel — faqat adminlar uchun."""
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup, Message,
)
from database import db

logger   = logging.getLogger(__name__)
router   = Router()
SUPER_ID = int(os.environ.get("SUPER_ADMIN_ID", "0"))
UZ       = ZoneInfo("Asia/Tashkent")


# ── helpers ───────────────────────────────────────────────────────────────────

def now_uz():
    return datetime.now(UZ).replace(tzinfo=None)


def fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, str):
        for f in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                v = datetime.strptime(v, f); break
            except ValueError:
                continue
        else:
            return str(v)
    return v.strftime("%d.%m.%Y %H:%M") + " (UZ)" if isinstance(v, datetime) else str(v)


def active(v) -> bool:
    return v in (True, 1, "1")


def pid(data: str, prefix: str):
    try:
        return int(data[len(prefix):])
    except Exception:
        return None


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


def b(txt, dat):
    return [InlineKeyboardButton(text=txt, callback_data=dat)]


def main_kb():
    return kb(
        b("📚 Kurslar", "m:crs") + b("📢 Kanallar", "m:ch"),
        b("📊 Dashboard", "m:dash"),
        b("➕ Admin qo'shish", "m:adm"),
    )


def back(to="m:main"):
    return kb(b("⬅️ Orqaga", to))


async def chk(uid) -> bool:
    return await db.is_admin(uid)


async def no_msg(m: Message):
    await m.answer("🚫 Siz admin emassiz.")


async def no_cb(cb: CallbackQuery):
    await cb.answer("🚫 Siz admin emassiz!", show_alert=True)


# ── states ────────────────────────────────────────────────────────────────────

class CS(StatesGroup):
    name = State()
    desc = State()


class LS(StatesGroup):
    title        = State()
    content      = State()
    audio_caption = State()   # audio yuborilgandan keyin caption so'rash


class CHS(StatesGroup):
    cid      = State()
    course   = State()
    start    = State()
    interval = State()


# ── /start /admin /cancel ─────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(m: Message, state: FSMContext):
    if m.chat.type != "private":
        return
    await state.clear()
    uid = m.from_user.id
    if uid == SUPER_ID:
        await db.set_admin(uid)
        return await m.answer("👋 Xush kelibsiz, Super Admin!", reply_markup=main_kb())
    if await chk(uid):
        return await m.answer("👋 Admin panelga xush kelibsiz!", reply_markup=main_kb())
    await db.add_user(uid)
    await m.answer("👋 Salom!\n\n🚫 Siz admin emassiz.")


@router.message(Command("admin"))
async def cmd_admin(m: Message, state: FSMContext):
    if m.chat.type != "private":
        return
    await state.clear()
    if not await chk(m.from_user.id):
        return await no_msg(m)
    await m.answer("🎛 Admin panel:", reply_markup=main_kb())


@router.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    if m.chat.type != "private":
        return
    await state.clear()
    await m.answer("❌ Bekor qilindi.", reply_markup=main_kb())


# ── main menu ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "m:main")
async def cb_main(cb: CallbackQuery, state: FSMContext):
    if not await chk(cb.from_user.id):
        return await no_cb(cb)
    await state.clear()
    try:
        await cb.message.edit_text("🎛 Admin panel:", reply_markup=main_kb())
    except Exception:
        await cb.message.answer("🎛 Admin panel:", reply_markup=main_kb())


# ── admin qo'shish ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "m:adm")
async def cb_adm(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != SUPER_ID:
        return await cb.answer("Faqat Super Admin!", show_alert=True)
    await cb.message.edit_text("Yangi adminning Telegram ID sini yuboring:", reply_markup=back())
    await state.set_state("adm_id")


@router.message(StateFilter("adm_id"))
async def proc_adm(m: Message, state: FSMContext):
    if m.from_user.id != SUPER_ID:
        return
    try:
        nid = int(m.text.strip())
        await db.set_admin(nid)
        await state.clear()
        await m.answer(f"✅ <code>{nid}</code> admin qilindi.", reply_markup=main_kb())
    except ValueError:
        await m.answer("❌ Faqat raqam kiriting:")


# ── kurslar ───────────────────────────────────────────────────────────────────

async def show_courses(target):
    courses = await db.get_all_courses()
    rows = [[InlineKeyboardButton(text=f"📘 {c['name']}", callback_data=f"crs:{c['id']}")]
            for c in courses]
    rows += [b("➕ Yangi kurs", "crs:new"), b("⬅️ Orqaga", "m:main")]
    txt = f"📚 <b>Kurslar</b> ({len(courses)} ta)"
    mkb = InlineKeyboardMarkup(inline_keyboard=rows)
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(txt, reply_markup=mkb)
        except Exception:
            await target.message.answer(txt, reply_markup=mkb)
    else:
        await target.answer(txt, reply_markup=mkb)


@router.callback_query(F.data == "m:crs")
async def cb_crs(cb: CallbackQuery):
    if not await chk(cb.from_user.id): return await no_cb(cb)
    await show_courses(cb)


@router.callback_query(F.data == "crs:new")
async def cb_crs_new(cb: CallbackQuery, state: FSMContext):
    if not await chk(cb.from_user.id): return await no_cb(cb)
    await cb.message.edit_text("📘 Kurs nomini kiriting:", reply_markup=back("m:crs"))
    await state.set_state(CS.name)


@router.message(CS.name)
async def proc_cs_name(m: Message, state: FSMContext):
    if not await chk(m.from_user.id): return await no_msg(m)
    await state.update_data(cname=m.text.strip())
    await m.answer("📝 Tavsif kiriting ('-' = bo'sh):")
    await state.set_state(CS.desc)


@router.message(CS.desc)
async def proc_cs_desc(m: Message, state: FSMContext):
    if not await chk(m.from_user.id): return await no_msg(m)
    data = await state.get_data()
    desc = "" if m.text.strip() == "-" else m.text.strip()
    cid  = await db.create_course(data["cname"], desc)
    await state.clear()
    await m.answer(
        f"✅ Kurs yaratildi!\n🆔 <code>{cid}</code> — <b>{data['cname']}</b>",
        reply_markup=main_kb()
    )


@router.callback_query(F.data.startswith("crsdel:"))
async def cb_crs_del(cb: CallbackQuery):
    if not await chk(cb.from_user.id): return await no_cb(cb)
    await db.delete_course(pid(cb.data, "crsdel:"))
    await cb.answer("✅ Kurs o'chirildi!", show_alert=True)
    await show_courses(cb)


@router.callback_query(F.data.startswith("crs:") & ~F.data.startswith("crs:new"))
async def cb_crs_detail(cb: CallbackQuery):
    if not await chk(cb.from_user.id): return await no_cb(cb)
    cid    = pid(cb.data, "crs:")
    course = await db.get_course(cid)
    if not course: return await cb.answer("Topilmadi!", show_alert=True)
    lessons = await db.get_lessons(cid)
    rows = [[InlineKeyboardButton(
                text=f"📖 {l['lesson_number']}-dars: {l['title']}",
                callback_data=f"les:{l['id']}")] for l in lessons]
    rows += [b("➕ Dars qo'shish", f"lesadd:{cid}"),
             b("🗑 Kursni o'chirish", f"crsdel:{cid}"),
             b("⬅️ Orqaga", "m:crs")]
    await cb.message.edit_text(
        f"📘 <b>{course['name']}</b>\n{course['description'] or ''}\n\n📖 {len(lessons)} ta dars",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )

# ── darslar ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("lesadd:"))
async def cb_les_add(cb: CallbackQuery, state: FSMContext):
    if not await chk(cb.from_user.id): return await no_cb(cb)
    cid = pid(cb.data, "lesadd:")
    await state.update_data(cid=cid, items=[])
    await cb.message.edit_text(
        "📖 Dars sarlavhasini kiriting:\n\n/cancel — bekor qilish",
        reply_markup=back(f"crs:{cid}")
    )
    await state.set_state(LS.title)


@router.message(LS.title)
async def proc_ls_title(m: Message, state: FSMContext):
    if not await chk(m.from_user.id): return await no_msg(m)
    await state.update_data(title=m.text.strip())
    await m.answer(
        "📎 Kontent yuboring:\n"
        "• 📝 Matn\n• 🖼 Rasm\n• 🎬 Video\n• 🎵 Audio\n\n"
        "Hammasi tayyor bo'lgach — /done\n"
        "Bekor qilish — /cancel"
    )
    await state.set_state(LS.content)


@router.message(LS.content, Command("done"))
async def proc_ls_done(m: Message, state: FSMContext):
    if not await chk(m.from_user.id): return await no_msg(m)
    data  = await state.get_data()
    items = data.get("items", [])
    cid   = data.get("cid")
    title = data.get("title", "")

    if not items:
        return await m.answer(
            "⚠️ Hech qanday kontent qo'shilmadi.\n"
            "Rasm, video, audio yoki matn yuboring, keyin /done"
        )
    if not cid or not title:
        await state.clear()
        return await m.answer("⚠️ Xato: ma'lumot yo'qoldi. /start dan boshlang.", reply_markup=main_kb())

    try:
        num    = await db.get_next_lesson_num(cid)
        les_id = await db.create_lesson(cid, num, title)
        for i, item in enumerate(items):
            await db.add_content(les_id, item["t"], item.get("f"), item.get("txt"), i)
        await state.clear()
        await m.answer(
            f"✅ <b>{num}-dars saqlandi!</b>\n"
            f"📖 <b>{title}</b>\n"
            f"📎 Kontent: {len(items)} ta",
            reply_markup=main_kb()
        )
    except Exception as e:
        logger.error(f"Dars saqlash xato: {e}", exc_info=True)
        await m.answer(f"❌ Xato: {e}\nQaytadan urinib ko'ring.")


@router.message(LS.content, F.photo)
async def ls_photo(m: Message, state: FSMContext):
    if not await chk(m.from_user.id): return
    data = await state.get_data()
    items = data.get("items", [])
    items.append({"t": "photo", "f": m.photo[-1].file_id})
    await state.update_data(items=items)
    await m.answer(f"✅ Rasm ({len(items)} ta). Davom eting yoki /done")


@router.message(LS.content, F.video)
async def ls_video(m: Message, state: FSMContext):
    if not await chk(m.from_user.id): return
    data = await state.get_data()
    items = data.get("items", [])
    items.append({"t": "video", "f": m.video.file_id})
    await state.update_data(items=items)
    await m.answer(f"✅ Video ({len(items)} ta). Davom eting yoki /done")


@router.message(LS.content, F.audio)
async def ls_audio(m: Message, state: FSMContext):
    if not await chk(m.from_user.id): return
    # Audioga caption ham qo'shish imkoniyati
    await state.update_data(_pending_audio=m.audio.file_id)
    await state.set_state(LS.audio_caption)
    await m.answer(
        "🎵 Audio qabul qilindi!\n\n"
        "📝 Audioga matn (caption) qo'shmoqchimisiz?\n\n"
        "• Matn yuboring — caption sifatida qo'shiladi\n"
        "• /skip — matnsiz saqlash\n"
        "• /cancel — bekor qilish"
    )


@router.message(LS.audio_caption, Command("done"))
async def ls_audio_caption_done(m: Message, state: FSMContext):
    """Audio caption kutilayotganda /done bosilsa — skip qilib davom etamiz."""
    if not await chk(m.from_user.id): return
    data  = await state.get_data()
    items = data.get("items", [])
    file_id = data.get("_pending_audio")
    if file_id:
        items.append({"t": "audio", "f": file_id, "txt": None})
        await state.update_data(items=items, _pending_audio=None)
    await state.set_state(LS.content)
    # /done ni qayta ishlash uchun content state'ga o'tkazib, proc_ls_done chaqiramiz
    await m.answer("ℹ️ Audio matnsiz saqlandi. /done bilan darsni yakunlang.")


@router.message(LS.audio_caption, Command("skip"))
async def ls_audio_skip(m: Message, state: FSMContext):
    """Captionsiz saqlash."""
    if not await chk(m.from_user.id): return
    data  = await state.get_data()
    items = data.get("items", [])
    file_id = data.get("_pending_audio")
    items.append({"t": "audio", "f": file_id, "txt": None})
    await state.update_data(items=items, _pending_audio=None)
    await state.set_state(LS.content)
    await m.answer(f"✅ Audio saqlandi ({len(items)} ta). Davom eting yoki /done")


@router.message(LS.audio_caption, F.text)
async def ls_audio_caption(m: Message, state: FSMContext):
    """Caption bilan saqlash."""
    if not await chk(m.from_user.id): return
    data  = await state.get_data()
    items = data.get("items", [])
    file_id = data.get("_pending_audio")
    caption = m.text.strip()
    items.append({"t": "audio", "f": file_id, "txt": caption})
    await state.update_data(items=items, _pending_audio=None)
    await state.set_state(LS.content)
    await m.answer(f"✅ Audio + matn saqlandi ({len(items)} ta). Davom eting yoki /done")


@router.message(LS.content, F.voice)
async def ls_voice(m: Message, state: FSMContext):
    if not await chk(m.from_user.id): return
    data  = await state.get_data()
    items = data.get("items", [])
    items.append({"t": "voice", "f": m.voice.file_id})
    await state.update_data(items=items)
    await m.answer(f"✅ Ovozli xabar ({len(items)} ta). Davom eting yoki /done")


@router.message(LS.content, F.document)
async def ls_doc(m: Message, state: FSMContext):
    if not await chk(m.from_user.id): return
    data  = await state.get_data()
    items = data.get("items", [])
    items.append({"t": "document", "f": m.document.file_id})
    await state.update_data(items=items)
    await m.answer(f"✅ Fayl ({len(items)} ta). Davom eting yoki /done")


@router.message(LS.content, F.text)
async def ls_text(m: Message, state: FSMContext):
    if not await chk(m.from_user.id): return
    data = await state.get_data()
    items = data.get("items", [])
    items.append({"t": "text", "txt": m.text})
    await state.update_data(items=items)
    await m.answer(f"✅ Matn ({len(items)} ta). Davom eting yoki /done")


# ── kanallar ──────────────────────────────────────────────────────────────────

async def show_channels(target):
    chs = await db.get_all_channels()
    rows = [[InlineKeyboardButton(
                text=f"{'🟢' if active(ch['is_active']) else '🔴'} {ch['channel_name'] or ch['channel_id']}",
                callback_data=f"chi:{ch['channel_id']}")] for ch in chs]
    rows += [b("➕ Kanal qo'shish", "ch:add"), b("⬅️ Orqaga", "m:main")]
    txt = f"📢 <b>Kanallar</b> ({len(chs)} ta)"
    mkb = InlineKeyboardMarkup(inline_keyboard=rows)
    try:
        await target.message.edit_text(txt, reply_markup=mkb)
    except Exception:
        await target.message.answer(txt, reply_markup=mkb)


@router.callback_query(F.data == "m:ch")
async def cb_ch(cb: CallbackQuery):
    if not await chk(cb.from_user.id): return await no_cb(cb)
    await show_channels(cb)


@router.callback_query(F.data == "ch:add")
async def cb_ch_add(cb: CallbackQuery, state: FSMContext):
    if not await chk(cb.from_user.id): return await no_cb(cb)
    await cb.message.edit_text(
        "📢 <b>Kanal qo'shish</b>\n\n"
        "Kanal ID sini kiriting.\n"
        "<i>💡 Kanal ID: @getmyid_bot ni kanalga qo'shing</i>\n\n"
        "Misol: <code>-1001234567890</code>\n\n"
        "/cancel — bekor qilish",
        reply_markup=back("m:ch")
    )
    await state.set_state(CHS.cid)


@router.message(CHS.cid)
async def proc_chs_cid(m: Message, state: FSMContext):
    if not await chk(m.from_user.id): return await no_msg(m)
    try:
        cid = int(m.text.strip())
    except ValueError:
        return await m.answer("❌ Noto'g'ri. Misol: <code>-1001234567890</code>\n/cancel")
    courses = await db.get_all_courses()
    if not courses:
        await state.clear()
        return await m.answer("⚠️ Avval kurs yarating.", reply_markup=main_kb())
    await state.update_data(channel_id=cid)
    rows = [[InlineKeyboardButton(text=f"📘 {c['name']}", callback_data=f"chcrs:{c['id']}")]
            for c in courses]
    rows.append(b("❌ Bekor qilish", "m:main"))
    await m.answer(
        f"✅ Kanal ID: <code>{cid}</code>\n\nKursni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await state.set_state(CHS.course)


@router.callback_query(CHS.course, F.data.startswith("chcrs:"))
async def proc_chs_course(cb: CallbackQuery, state: FSMContext):
    if not await chk(cb.from_user.id): return await no_cb(cb)
    await state.update_data(course_id=pid(cb.data, "chcrs:"))
    await cb.message.edit_text(
        "⏰ Birinchi dars vaqtini kiriting <b>(O'zbekiston vaqti, HH:MM)</b>:\n\n"
        "Misol: <code>20:00</code>\n\n/cancel — bekor qilish"
    )
    await state.set_state(CHS.start)


@router.message(CHS.start)
async def proc_chs_start(m: Message, state: FSMContext):
    if not await chk(m.from_user.id): return await no_msg(m)
    try:
        h, mi = map(int, m.text.strip().split(":"))
        assert 0 <= h <= 23 and 0 <= mi <= 59
    except Exception:
        return await m.answer("❌ HH:MM formatda kiriting. Misol: <code>20:00</code>\n/cancel")
    await state.update_data(sh=h, sm=mi)
    await m.answer(
        "⏱ Interval (soat):\n"
        "<code>24</code> — kuniga 1 dars\n"
        "<code>48</code> — 2 kunda 1 dars\n"
        "<code>72</code> — 3 kunda 1 dars\n\n"
        "/cancel — bekor qilish"
    )
    await state.set_state(CHS.interval)


@router.message(CHS.interval)
async def proc_chs_interval(m: Message, state: FSMContext):
    if not await chk(m.from_user.id): return await no_msg(m)
    try:
        iv = int(m.text.strip())
        assert iv >= 1
    except Exception:
        return await m.answer("❌ Musbat raqam kiriting. Misol: <code>48</code>\n/cancel")

    data      = await state.get_data()
    ch_id     = data["channel_id"]
    course_id = data["course_id"]
    h, mi     = data["sh"], data["sm"]

    now   = now_uz()
    start = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if start <= now:
        start += timedelta(days=1)

    ch_name = f"Kanal {ch_id}"
    try:
        chat    = await m.bot.get_chat(ch_id)
        ch_name = chat.title or ch_name
    except Exception:
        pass

    await db.upsert_channel(ch_id, ch_name, course_id, iv, start)
    course = await db.get_course(course_id)
    await state.clear()
    await m.answer(
        f"✅ <b>Kanal qo'shildi!</b>\n\n"
        f"📢 <b>{ch_name}</b>\n"
        f"🆔 <code>{ch_id}</code>\n"
        f"📘 Kurs: <b>{course['name']}</b>\n"
        f"⏰ Birinchi dars: <b>{start.strftime('%d.%m.%Y %H:%M')} (UZ)</b>\n"
        f"⏱ Interval: <b>{iv} soat</b>\n\n"
        f"⚠️ Botni kanalga admin sifatida qo'shing!",
        reply_markup=main_kb()
    )


@router.callback_query(F.data.startswith("chi:"))
async def cb_chi(cb: CallbackQuery):
    if not await chk(cb.from_user.id): return await no_cb(cb)
    cid    = pid(cb.data, "chi:")
    ch     = await db.get_channel(cid)
    if not ch: return await cb.answer("Topilmadi!", show_alert=True)
    course = await db.get_course(ch["course_id"]) if ch["course_id"] else None
    total  = await db.get_total_lessons(ch["course_id"]) if ch["course_id"] else 0
    status = "🟢 Faol" if active(ch["is_active"]) else "🔴 Nofaol"
    await cb.message.edit_text(
        f"📢 <b>{ch['channel_name'] or ch['channel_id']}</b>\n\n"
        f"🆔 ID: <code>{cid}</code>\n"
        f"📌 Holat: {status}\n"
        f"📘 Kurs: <b>{course['name'] if course else '—'}</b>\n"
        f"📖 Dars: <b>{ch['current_lesson_number']}</b> / {total}\n"
        f"⏱ Interval: <b>{ch['interval_hours']} soat</b>\n"
        f"📅 Keyingi: <b>{fmt(ch['next_send_time'])}</b>",
        reply_markup=kb(b("🗑 O'chirish", f"chdel:{cid}"), b("⬅️ Orqaga", "m:ch"))
    )


@router.callback_query(F.data.startswith("chdel:"))
async def cb_chdel(cb: CallbackQuery):
    if not await chk(cb.from_user.id): return await no_cb(cb)
    await db.delete_channel(pid(cb.data, "chdel:"))
    await cb.answer("✅ Kanal o'chirildi!", show_alert=True)
    await show_channels(cb)


# ── dashboard ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "m:dash")
async def cb_dash(cb: CallbackQuery):
    if not await chk(cb.from_user.id): return await no_cb(cb)
    chs = await db.get_all_channels()
    if not chs:
        return await cb.message.edit_text(
            "📊 <b>Dashboard</b>\n\nHali hech qanday kanal yo'q.", reply_markup=back()
        )
    lines = ["📊 <b>Dashboard — Jonli Monitoring</b>\n"]
    for ch in chs:
        total = await db.get_total_lessons(ch["course_id"]) if ch["course_id"] else 0
        icon  = "🟢" if active(ch["is_active"]) else "🔴"
        lines.append(
            f"{icon} <b>{ch['channel_name'] or ch['channel_id']}</b>\n"
            f"   📘 {ch.get('course_name') or '—'}\n"
            f"   📖 {ch['current_lesson_number']} / {total} dars\n"
            f"   📅 {fmt(ch['next_send_time'])}\n"
            f"   ⏱ {ch['interval_hours']} soat\n"
        )
    try:
        await cb.message.edit_text("\n".join(lines), reply_markup=back())
    except Exception:
        await cb.message.answer("\n".join(lines), reply_markup=back())
