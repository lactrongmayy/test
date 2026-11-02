import os
import re
import logging
import unicodedata
import aiohttp
from collections import Counter, OrderedDict

import discord
from discord.ext import commands
from groq import AsyncGroq

# ==================================================
# CẤU HÌNH
# ==================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# File từ điển (tự tải về nếu chưa có)
WORDLIST_PATH = os.getenv("WORDLIST_PATH", "Viet74K.txt")
WORDLIST_URLS = [
    "https://vietnamese-wordlist.duyet.net/Viet74K.txt",
    "https://raw.githubusercontent.com/duyet/vietnamese-wordlist/master/Viet74K.txt",
]

BOT_A_ID = 1248205177589334026
CHANNEL_ID = 1564912638272602142

MODEL = "openai/gpt-oss-120b"
MAX_ATTEMPTS = 3
TEMPERATURES = [0.1, 0.5, 0.8]
CACHE_SIZE = 1000

if not DISCORD_TOKEN:
    raise ValueError("Missing DISCORD_TOKEN")

if not GROQ_API_KEY:
    raise ValueError("Missing GROQ_API_KEY")


# ==================================================
# LOGGING
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ==================================================
# DISCORD
# ==================================================

intents = discord.Intents.default()
intents.message_content = True  # Bật Message Content Intent trong Developer Portal
intents.guilds = True
intents.messages = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ==================================================
# GROQ
# ==================================================

ai = AsyncGroq(
    api_key=GROQ_API_KEY,
    max_retries=1,
    timeout=45
)


# ==================================================
# BỘ NHỚ GIỚI HẠN (tránh tăng mãi)
# ==================================================

class BoundedDict:
    def __init__(self, maxlen):
        self.maxlen = maxlen
        self._data = OrderedDict()

    def __contains__(self, key):
        return key in self._data

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value=True):
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self.maxlen:
            self._data.popitem(last=False)


processed = BoundedDict(CACHE_SIZE)   # message_id đã trả lời xong
attempted = BoundedDict(CACHE_SIZE)   # message_id -> nội dung câu đố đã thử
processing = set()                    # message_id đang xử lý


# ==================================================
# TỪ ĐIỂN + CHỈ MỤC ANAGRAM
# ==================================================

def normalize_text(text):
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def letters_key(text):
    chars = [
        c for c in unicodedata.normalize("NFC", text).casefold()
        if c.isalpha()
    ]
    return "".join(sorted(chars))


ANAGRAMS = {}  # key chữ cái đã sắp xếp -> danh sách đáp án


def build_index(lines):
    ANAGRAMS.clear()
    seen = set()

    for line in lines:
        word = normalize_text(line)

        if not word or word in seen:
            continue

        if not all(c.isalpha() or c in " -" for c in word):
            continue

        seen.add(word)
        ANAGRAMS.setdefault(letters_key(word), []).append(word)

    logging.info(f"Indexed {len(seen)} words.")


async def load_wordlist():
    if os.path.exists(WORDLIST_PATH):
        with open(WORDLIST_PATH, encoding="utf-8") as file:
            build_index(file.read().splitlines())
        return

    async with aiohttp.ClientSession() as session:
        for url in WORDLIST_URLS:
            try:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status != 200:
                        continue

                    text = await resp.text(encoding="utf-8")

                with open(WORDLIST_PATH, "w", encoding="utf-8") as file:
                    file.write(text)

                build_index(text.splitlines())
                return

            except Exception:
                logging.exception(f"Cannot download {url}")

    logging.error("Wordlist unavailable, using AI only.")


# ==================================================
# ĐỌC EMBED
# ==================================================

def extract_embed(message):
    contents = []

    for embed in message.embeds:
        if embed.title:
            contents.append(embed.title)

        if embed.description:
            contents.append(embed.description)

        if embed.author and embed.author.name:
            contents.append(embed.author.name)

        for field in embed.fields:
            if field.name:
                contents.append(field.name)

            if field.value:
                contents.append(field.value)

        if embed.footer and embed.footer.text:
            contents.append(embed.footer.text)

    return "\n".join(contents).strip()


# ==================================================
# LẤY CHỮ CÁI
# ==================================================

def extract_scrambled_letters(question):
    match = re.search(
        r"Từ cần đoán:\s*\*\*(.*?)\*\*",
        question,
        flags=re.IGNORECASE | re.DOTALL
    )

    if not match:
        match = re.search(
            r"Từ cần đoán:\s*(.+?)(?:\s*\(gồm|\n|$)",
            question,
            flags=re.IGNORECASE
        )

    if not match:
        logging.warning("Cannot find scrambled letters.")
        return None

    raw = match.group(1).strip()

    parts = [
        unicodedata.normalize("NFC", item.strip()).casefold()
        for item in raw.split("/")
        if item.strip()
    ]

    if not parts:
        return None

    for part in parts:
        if not part.isalpha():
            logging.warning(f"Invalid character: {part}")
            return None

    return parts


# ==================================================
# KIỂM TRA ĐÁP ÁN
# ==================================================

def normalize_answer(text):
    text = unicodedata.normalize("NFC", text).casefold()

    return [
        char for char in text
        if char.isalpha()
    ]


def validate_answer(answer, original_letters):
    answer_letters = normalize_answer(answer)

    if not answer_letters:
        return False

    return Counter(answer_letters) == Counter(original_letters)


# ==================================================
# GỌI GROQ
# ==================================================

async def ask_groq(prompt, temperature):
    response = await ai.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=temperature,
        max_completion_tokens=2048,
        reasoning_effort="low"
    )

    choice = response.choices[0]
    answer = choice.message.content or ""

    if not answer.strip():
        logging.warning(
            f"Empty AI response: {choice.finish_reason}"
        )
        return None

    answer = answer.strip().replace("`", "")

    answer = re.sub(
        r"^(đáp án|answer)\s*[:：-]?\s*",
        "",
        answer,
        flags=re.IGNORECASE
    )

    lines = answer.splitlines()

    if not lines:
        return None

    return lines[0].strip().strip("\"'") or None


# ==================================================
# GIẢI CÂU ĐỐ
# ==================================================

async def pick_candidate(question, candidates):
    prompt = f"""
Câu đố:
{question}

Các đáp án khả dĩ:
{chr(10).join("- " + c for c in candidates)}

Chọn đúng MỘT đáp án phù hợp ngữ cảnh nhất.
Chỉ trả về đáp án đó, không giải thích.
"""
    try:
        picked = await ask_groq(prompt, 0.1)
    except Exception:
        logging.exception("Groq API error (pick).")
        return candidates[0]

    if picked and normalize_text(picked) in candidates:
        return normalize_text(picked)

    return candidates[0]


async def solve_with_ai(question, original_letters):
    letters_text = " / ".join(original_letters)

    prompt = f"""
Bạn là chuyên gia giải trò chơi Vua Tiếng Việt.

CÁC CHỮ CÁI:
{letters_text}

CÂU ĐỐ:
{question}

YÊU CẦU:
- Ghép thành từ hoặc cụm từ tiếng Việt có nghĩa.
- Sử dụng toàn bộ chữ cái.
- Không thêm chữ cái.
- Không bỏ chữ cái.
- Mỗi chữ cái chỉ được sử dụng đúng số lần.
- Giữ đúng dấu tiếng Việt.
- Ưu tiên đáp án phù hợp ngữ cảnh.
- Chỉ trả về đáp án.
- Không giải thích.
"""

    rejected = []

    for attempt in range(MAX_ATTEMPTS):
        try:
            logging.info(f"AI attempt {attempt + 1}/{MAX_ATTEMPTS}")

            current_prompt = prompt

            if rejected:
                current_prompt += (
                    "\nCác đáp án SAI, tuyệt đối không lặp lại: "
                    + ", ".join(rejected)
                    + "\nKiểm tra chính xác từng chữ cái và dấu tiếng Việt.\n"
                )

            temperature = TEMPERATURES[
                min(attempt, len(TEMPERATURES) - 1)
            ]

            answer = await ask_groq(current_prompt, temperature)

            if not answer:
                continue

            logging.info(f"AI answer: {answer}")

            if validate_answer(answer, original_letters):
                return answer

            logging.warning("Answer rejected: wrong letters.")
            rejected.append(answer)

        except Exception:
            logging.exception("Groq API error.")

    return None


async def solve_question(question):
    original_letters = extract_scrambled_letters(question)

    if not original_letters:
        return None

    letters_text = " / ".join(original_letters)
    logging.info(f"Letters: {letters_text}")

    # Bước 1: tra từ điển theo anagram (chính xác 100% về chữ cái)
    candidates = ANAGRAMS.get(letters_key("".join(original_letters)), [])
    logging.info(f"Dictionary candidates: {candidates}")

    if len(candidates) == 1:
        return candidates[0]

    if len(candidates) > 1:
        return await pick_candidate(question, candidates)

    # Bước 2: không có trong từ điển -> nhờ AI
    return await solve_with_ai(question, original_letters)


# ==================================================
# XỬ LÝ TIN NHẮN
# ==================================================

async def process_message(message):
    message_id = message.id

    if message_id in processed:
        return

    if message_id in processing:
        return

    if message.author.id != BOT_A_ID:
        return

    if message.channel.id != CHANNEL_ID:
        return

    if not message.embeds:
        return

    question = extract_embed(message)

    if not question:
        return

    # Bỏ qua embed không phải câu đố (kết quả, bảng điểm...)
    if "từ cần đoán" not in question.casefold():
        return

    # Không thử lại nếu nội dung câu đố không đổi
    if attempted.get(message_id) == question:
        return

    attempted.set(message_id, question)
    processing.add(message_id)

    try:
        logging.info("=" * 45)
        logging.info("NEW PUZZLE:")
        logging.info(question)

        answer = await solve_question(question)

        if not answer:
            logging.warning("No valid answer found.")
            return

        await message.channel.send(
            answer,
            allowed_mentions=discord.AllowedMentions.none()
        )

        processed.set(message_id)
        logging.info(f"ANSWER SENT: {answer}")

    except discord.Forbidden:
        logging.error("Missing Discord permissions.")

    except discord.HTTPException as error:
        logging.error(f"Discord error: {error}")

    except Exception:
        logging.exception("Message processing error.")

    finally:
        processing.discard(message_id)


# ==================================================
# EVENT
# ==================================================

@bot.event
async def on_message(message):
    await process_message(message)
    await bot.process_commands(message)


@bot.event
async def on_raw_message_edit(payload):
    if payload.channel_id != CHANNEL_ID:
        return

    if payload.message_id in processed:
        return

    try:
        channel = bot.get_channel(payload.channel_id)

        if channel is None:
            channel = await bot.fetch_channel(payload.channel_id)

        message = await channel.fetch_message(payload.message_id)

    except discord.HTTPException:
        return

    await process_message(message)


@bot.event
async def setup_hook():
    await load_wordlist()


@bot.event
async def on_ready():
    logging.info("=" * 45)
    logging.info(f"BOT ONLINE: {bot.user}")
    logging.info(f"BOT A ID: {BOT_A_ID}")
    logging.info(f"CHANNEL ID: {CHANNEL_ID}")
    logging.info(f"MODEL: {MODEL}")
    logging.info("LETTER VALIDATION: ENABLED")
    logging.info(f"DICTIONARY ENTRIES: {len(ANAGRAMS)} anagram groups")
    logging.info("=" * 45)


# ==================================================
# START BOT
# ==================================================

bot.run(DISCORD_TOKEN)
