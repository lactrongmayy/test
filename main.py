import os
import re
import asyncio
import logging

import discord
from discord.ext import commands
from google import genai


# =====================================
# CONFIG
# =====================================

TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

BOT_A_ID = 1248205177589334026
CHANNEL_ID = 1564912638272602142

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

logging.basicConfig(level=logging.INFO)

ai = genai.Client(api_key=GEMINI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

processed = set()


# =====================================
# EXTRACT EMBED
# =====================================

def extract_embed(embed):

    parts = []

    if embed.title:
        parts.append(embed.title)

    if embed.description:
        parts.append(embed.description)

    if embed.author and embed.author.name:
        parts.append(embed.author.name)

    for field in embed.fields:
        parts.append(field.name)
        parts.append(field.value)

    if embed.footer and embed.footer.text:
        parts.append(embed.footer.text)

    return "\n".join(parts)


# =====================================
# SOLVE WITH GEMINI
# =====================================

def solve_question(question):

    prompt = f"""
Bạn là AI chuyên giải trò chơi ghép chữ tiếng Việt.

NHIỆM VỤ:
- Đọc các chữ cái bị xáo trộn.
- Sắp xếp thành từ hoặc cụm từ tiếng Việt có nghĩa.
- Phải sử dụng đúng các chữ cái được cung cấp.
- Giữ nguyên dấu tiếng Việt.
- Không tự ý thêm hoặc bỏ ký tự.
- Ưu tiên đáp án phù hợp với ngữ cảnh trò chơi.

NỘI DUNG EMBED:
{question}

CHỈ TRẢ VỀ ĐÁP ÁN.
KHÔNG GIẢI THÍCH.
KHÔNG VIẾT LỜI DẪN.
"""

    response = ai.models.generate_content(
        model=MODEL,
        contents=prompt
    )

    answer = (response.text or "").strip()

    answer = answer.replace("```", "")
    answer = answer.replace("`", "")

    answer = re.sub(
        r"^(đáp án|answer)\s*[:：-]?\s*",
        "",
        answer,
        flags=re.IGNORECASE
    )

    return answer.splitlines()[0].strip()


# =====================================
# DETECT BOT A EMBED
# =====================================

@bot.event
async def on_message(message):

    if message.author.id != BOT_A_ID:
        return

    if message.channel.id != CHANNEL_ID:
        return

    if not message.embeds:
        return

    if message.id in processed:
        return

    processed.add(message.id)

    try:

        embed = message.embeds[0]

        question = extract_embed(embed)

        if not question:
            return

        logging.info("Đã nhận Embed:")
        logging.info(question)

        answer = await asyncio.to_thread(
            solve_question,
            question
        )

        if not answer:
            return

        # Tránh nội dung quá dài
        answer = answer[:200]

        await message.reply(
            f"`{answer}`",
            mention_author=False
        )

        logging.info(f"Đáp án: {answer}")

    except Exception as e:

        logging.error(f"Lỗi xử lý: {e}")


# =====================================
# READY
# =====================================

@bot.event
async def on_ready():

    logging.info(
        f"Bot đã online: {bot.user}"
    )

    logging.info(
        f"Theo dõi Bot A: {BOT_A_ID}"
    )

    logging.info(
        f"Kênh: {CHANNEL_ID}"
    )


# =====================================
# START
# =====================================

if not TOKEN:
    raise RuntimeError("Thiếu DISCORD_TOKEN")

if not GEMINI_API_KEY:
    raise RuntimeError("Thiếu GEMINI_API_KEY")

bot.run(TOKEN)