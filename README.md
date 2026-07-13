# otgulopchaniboti

Telegram bot — kanalga avtomatik dars yuboruvchi bot.

## Imkoniyatlar
- 📚 Kurs va darslar yaratish
- 🎵 Audio + matn (caption) bilan dars qo'shish
- 📢 Kanalga avtomatik dars yuborish (scheduler)
- ⏱ Interval sozlash (24/48/72 soat)
- 🔐 Admin panel

## O'rnatish

### Environment variables
`.env.example` faylini `.env` ga ko'chiring va to'ldiring:
```
BOT_TOKEN=your_bot_token_here
DATABASE_URL=postgresql://user:password@host:5432/railway
SUPER_ADMIN_ID=123456789
```

### Lokal ishga tushirish
```bash
pip install -r requirements.txt
python bot.py
```

### Railway Deploy
Railway avtomatik `Dockerfile` orqali build qiladi.  
`railway.toml` sozlamalari allaqachon tayyor.

## Texnologiyalar
- Python 3.11
- aiogram 3.7
- asyncpg / aiosqlite
- APScheduler
- Railway (hosting)
