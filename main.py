import os
import re
import logging
import unicodedata
from collections import Counter

import discord
from discord.ext import commands
from groq import AsyncGroq

# ==================================================
# CẤU HÌNH
# ==================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

BOT_A_ID = 1248205177589334026
CHANNEL_ID = 1564912638272602142

MODEL = "openai/gpt-oss-120b"

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
intents.message_content = True
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
    max_retries=3,
    timeout=45
)

processed = set()
processing = set()


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
        if len(part) != 1 or not part.isalpha():
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

async def ask_groq(prompt):
    response = await ai.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.1,
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

    return answer.splitlines()[0].strip().strip("\"'")


# ==================================================
# GIẢI CÂU ĐỐ
# ==================================================

async def solve_question(question):
    original_letters = extract_scrambled_letters(question)

    if not original_letters:
        return None

    letters_text = " / ".join(original_letters)

    logging.info(f"Letters: {letters_text}")

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

    for attempt in range(3):
        try:
            logging.info(
                f"Solving attempt {attempt + 1}/3"
            )

            current_prompt = prompt

            if attempt > 0:
                current_prompt += """
Đáp án trước không hợp lệ.
Hãy suy nghĩ lại và tìm một đáp án khác.
Kiểm tra chính xác từng chữ cái và dấu tiếng Việt.
"""

            answer = await ask_groq(current_prompt)

            if not answer:
                continue

            logging.info(f"AI answer: {answer}")

            if validate_answer(answer, original_letters):
                logging.info("Answer passed validation.")
                return answer

            logging.warning("Answer rejected.")

        except Exception:
            logging.exception("Groq API error.")

    return None


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

    processing.add(message_id)

    try:
        logging.info("=" * 45)
        logging.info("NEW PUZZLE:")
        logging.info(question)

        answer = await solve_question(question)

        if not answer:
            logging.warning("No valid answer found.")
            return

        await message.reply(
            content=f"`{answer}`",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none()
        )

        logging.info(f"ANSWER SENT: {answer}")

        processed.add(message_id)

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
async def on_message_edit(before, after):
    if before.embeds != after.embeds:
        processed.discard(after.id)
        await process_message(after)


@bot.event
async def on_ready():
    logging.info("=" * 45)
    logging.info(f"BOT ONLINE: {bot.user}")
    logging.info(f"BOT A ID: {BOT_A_ID}")
    logging.info(f"CHANNEL ID: {CHANNEL_ID}")
    logging.info(f"MODEL: {MODEL}")
    logging.info("LETTER VALIDATION: ENABLED")
    logging.info("=" * 45)


# ==================================================
# START BOT
# ==================================================

bot.run(DISCORD_TOKEN)