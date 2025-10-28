import asyncio
import feedparser
import json
import os
import re
import aiohttp
from datetime import datetime, time
from telegram import Bot
from telegram.error import TelegramError
from deep_translator import GoogleTranslator

# 🔧 Настройки
BOT_TOKEN = "8216129159:AAEPydIO3dU-tg4YUrP12-B3CoemTcA2ve8"
CHANNEL_ID = "@tunespots"

FETCH_INTERVAL = 3 * 3600   # каждые 3 часа парсим RSS
POST_INTERVAL = 120        # каждые 2 минут постим
WORK_HOURS = (8, 20)        # публикации с 08:00 до 20:00

NEWS_FILE = "news_queue.json"
POSTED_FILE = "posted.json"

# 🎧 RSS источники


RSS_FEEDS = [
    # 🌍 Англоязычные крупные порталы
    "https://www.billboard.com/feed/",
    "https://pitchfork.com/feed/",
    "https://www.nme.com/news/music/feed",
    "https://www.rollingstone.com/music/music-news/feed/",
    "https://musicfeeds.com.au/feed/",
    "https://consequence.net/feed/",
    "https://www.stereogum.com/feed/",
    "https://www.spin.com/feed/",
    "https://uproxx.com/music/feed/",
    "https://www.clashmusic.com/feed/",
    "https://www.thefader.com/feed/rss",
    "https://www.dancingastronaut.com/feed/",
    "https://djmag.com/rss.xml",
    "https://mixmag.net/rss.xml",
    "https://www.thissongissick.com/feed/",
    "https://www.indieisnotagenre.com/feed/",
    "https://www.hypebot.com/feed/",
    "https://www.xxlmag.com/feed/",
    "https://hiphopdx.com/feed",
    "https://metalinjection.net/feed",
    "https://metalhammer.com/feed",
    "https://popjustice.com/feed/",

    # 🇷🇺 Русскоязычные музыкальные СМИ
    "https://the-flow.ru/rss",
    "https://rockcult.ru/feed/",
    "https://daily.afisha.ru/rss/news/",
    "https://musify.club/news/rss",
    "https://rumusicnews.ru/feed/",
    "https://rusradio.ru/news/rss.xml",
    "https://newslab.ru/rss/music",
    "https://musicboxgroup.ru/feed",
    "https://www.zvuki.ru/rss/news.xml",

    # 🎛 Альтернативные / жанровые
    "https://edm.com/.rss/full/",
    "https://routenote.com/blog/feed/",
    "https://www.allmusic.com/rss",
    "https://soundcloudnews.wordpress.com/feed/",
    "https://musictech.com/feed/",
    "https://musicbusinessworldwide.com/feed/",
]


# ---------- Вспомогательные функции ----------

def load_json(filename, default=None):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    return default or []


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def translate_text(text, dest_lang="ru"):
    try:
        return GoogleTranslator(source="auto", target=dest_lang).translate(text)
    except Exception as e:
        print(f"⚠️ Ошибка перевода: {e}")
        return text


# ---------- Поиск артиста и трека на Яндекс.Музыке ----------

async def get_yandex_track(artist_name: str):
    """Пытается найти артиста на Яндекс.Музыке и вернуть ссылку на последний трек"""
    search_url = f"https://music.yandex.ru/search?text={artist_name}"
    api_url = f"https://music.yandex.ru/api/search?text={artist_name}&type=artist"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

                if not data.get("artists", {}).get("results"):
                    return None

                artist_id = data["artists"]["results"][0]["id"]
                artist_name = data["artists"]["results"][0]["name"]

                # Теперь получаем последний трек артиста
                artist_tracks_url = f"https://music.yandex.ru/artist/{artist_id}/tracks"
                return f"https://music.yandex.ru/artist/{artist_id}"

    except Exception as e:
        print(f"⚠️ Ошибка при поиске артиста {artist_name}: {e}")
        return None


def extract_possible_artist(title: str):
    """Пытается выделить имя артиста из заголовка"""
    # Убираем скобки, кавычки, лишние символы
    clean_title = re.sub(r"[\(\)\[\]\"“”‘’]", "", title)

    # Берём первые 2-3 слова (в заголовках часто имя артиста идёт в начале)
    words = clean_title.split()
    if len(words) <= 3:
        return clean_title
    return " ".join(words[:3])


# ---------- Парсинг и публикация ----------

async def fetch_news():
    posted_titles = set(load_json(POSTED_FILE, []))
    news_queue = load_json(NEWS_FILE, [])
    new_items = []

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:10]:
            title = entry.title
            link = entry.link
            summary = getattr(entry, "summary", "")

            if title not in posted_titles and all(n["title"] != title for n in news_queue):
                new_items.append({
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "source": feed_url
                })
                posted_titles.add(title)

    if new_items:
        news_queue.extend(new_items)
        save_json(NEWS_FILE, news_queue)
        save_json(POSTED_FILE, list(posted_titles))
        print(f"📰 Добавлено {len(new_items)} новых новостей.")
    else:
        print("😴 Новых новостей нет.")


async def post_next_news(bot: Bot):
    now = datetime.now().time()
    if not (time(WORK_HOURS[0], 0) <= now <= time(WORK_HOURS[1], 0)):
        print(f"🌙 Сейчас {now.strftime('%H:%M')}, публикации приостановлены до 08:00.")
        return

    news_queue = load_json(NEWS_FILE, [])
    if not news_queue:
        print("⏳ Очередь пуста — ждём новых новостей.")
        return

    news = news_queue.pop(0)
    save_json(NEWS_FILE, news_queue)

    translated_title = await translate_text(news["title"])
    translated_summary = await translate_text(news["summary"])

    # Попробуем найти ссылку на Яндекс.Музыку
    possible_artist = extract_possible_artist(news["title"])
    yandex_link = await get_yandex_track(possible_artist)

    message = (
        f"🎵 **{translated_title}** 🇷🇺\n"
        f"{translated_summary}\n\n"
        f"🔗 [Оригинал]({news['link']})\n"
        f"📡 Источник: {news['source']}"
    )

    if yandex_link:
        message += f"\n🎧 [Слушать {possible_artist} на Яндекс.Музыке]({yandex_link})"

    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=message, parse_mode="Markdown")
        print(f"✅ Опубликовано: {news['title']}")
    except TelegramError as e:
        print(f"⚠️ Ошибка публикации: {e}")


# ---------- Главный цикл ----------

async def main():
    print("🤖 Бот запущен.")
    bot = Bot(token=BOT_TOKEN)

    async def fetch_loop():
        while True:
            await fetch_news()
            await asyncio.sleep(FETCH_INTERVAL)

    async def post_loop():
        while True:
            await post_next_news(bot)
            await asyncio.sleep(POST_INTERVAL)

    await asyncio.gather(fetch_loop(), post_loop())


if __name__ == "__main__":
    asyncio.run(main())
