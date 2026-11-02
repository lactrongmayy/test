import os
import re
import asyncio
import logging

import discord
from discord.ext import commands
from groq import AsyncGroq


# ==========================================
# CONFIG
# ==========================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

BOT_A_ID = 1248205177589334026
CHANNEL_ID = 1564912638272602142

MODEL = "openai/gpt-oss-20b"

MAX_ANSWER_LENGTH = 200

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ==========================================
# CHECK CONFIG
# ==========================================

if not DISCORD_TOKEN:
    raise RuntimeError("Thiếu DISCORD_TOKEN")

if not GROQ_API_KEY:
    raise RuntimeError("Thiếu GROQ_API_KEY")


# ==========================================
# GROQ CLIENT
# ==========================================

ai = AsyncGroq(
    api_key=GROQ_API_KEY,
    max_retries=3,
    timeout=30
)


# ==========================================
# DISCORD CLIENT
# ==========================================

intents = discord.Intents.default()

intents.message_content = True
intents.messages = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ==========================================
# CACHE
# ==========================================

processed = set()
processing = set()

MAX_CACHE = 2000


# ==========================================
# EXTRACT EMBED
# ==========================================

def extract_embed(message):

    results = []

    for embed in message.embeds:

        if embed.title:
            results.append(embed.title)

        if embed.description:
            results.append(embed.description)

        if embed.author and embed.author.name:
            results.append(embed.author.name)

        for field in embed.fields:

            if field.name:
                results.append(field.name)

            if field.value:
                results.append(field.value)

        if embed.footer and embed.footer.text:
            results.append(embed.footer.text)

    return "\n".join(results).strip()


# ==========================================
# SOLVE QUESTION
# ==========================================

async def solve_question(question):

    prompt = f"""
Bạn là chuyên gia giải trò chơi ghép chữ tiếng Việt.

NHIỆM VỤ:

- Đọc các chữ cái bị xáo trộn.
- Ghép thành từ hoặc cụm từ tiếng Việt có nghĩa.
- Sử dụng đúng các chữ cái được cung cấp.
- Chú ý dấu thanh và dấu tiếng Việt.
- Không tự ý thêm hoặc bỏ chữ cái.
- Phân tích ngữ cảnh để tìm đáp án.
- Nếu có nhiều đáp án, chọn đáp án hợp lý nhất.

CÂU ĐỐ:

{question}

QUY TẮC TRẢ LỜI:

- Chỉ trả về đáp án.
- Không giải thích.
- Không viết lời dẫn.
- Không đánh số.
- Không sử dụng Markdown.
- Không thêm nội dung khác.
"""

    response = await ai.chat.completions.create(

        model=MODEL,

        messages=[
            {
                "role": "system",
                "content": (
                    "Bạn là AI chuyên giải trò chơi ghép chữ "
                    "tiếng Việt. Luôn trả lời ngắn gọn."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],

        temperature=0.1,

        max_completion_tokens=100
    )

    answer = response.choices[0].message.content

    if not answer:
        return None

    answer = answer.strip()

    answer = answer.replace("```", "")
    answer = answer.replace("`", "")

    answer = re.sub(
        r"^(đáp án|answer)\s*[:：-]?\s*",
        "",
        answer,
        flags=re.IGNORECASE
    )

    answer = answer.splitlines()[0].strip()

    if not answer:
        return None

    return answer


# ==========================================
# PROCESS EMBED
# ==========================================

async def process_message(message):

    if message.author.id != BOT_A_ID:
        return

    if message.channel.id != CHANNEL_ID:
        return

    if not message.embeds:
        return

    if message.id in processed:
        return

    if message.id in processing:
        return

    processing.add(message.id)

    try:

        question = extract_embed(message)

        if not question:
            logging.warning("Embed không có nội dung.")
            return

        logging.info("=" * 40)
        logging.info("NHẬN ĐƯỢC CÂU ĐỐ:")
        logging.info(question)

        logging.info("Đang gửi câu hỏi đến Groq...")

        answer = await solve_question(question)

        if not answer:

            logging.warning("AI không trả về đáp án.")

            return

        answer = answer[:MAX_ANSWER_LENGTH]

        # Kiểm tra tin nhắn còn tồn tại
        await message.channel.fetch_message(message.id)

        # Trả lời trực tiếp Embed
        await message.reply(
            content=f"`{answer}`",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none()
        )

        processed.add(message.id)

        if len(processed) > MAX_CACHE:
            processed.clear()

        logging.info(f"ĐÃ TRẢ LỜI: {answer}")

    except discord.NotFound:

        logging.warning("Embed đã bị xóa.")

    except Exception as error:

        logging.exception(
            f"LỖI XỬ LÝ: {error}"
        )

    finally:

        processing.discard(message.id)


# ==========================================
# NEW MESSAGE
# ==========================================

@bot.event
async def on_message(message):

    await process_message(message)

    await bot.process_commands(message)


# ==========================================
# EDIT MESSAGE
# ==========================================

@bot.event
async def on_message_edit(before, after):

    if before.embeds != after.embeds:

        if after.id not in processed:

            await process_message(after)


# ==========================================
# BOT READY
# ==========================================

@bot.event
async def on_ready():

    logging.info("=" * 45)

    logging.info(f"BOT ONLINE: {bot.user}")

    logging.info(f"BOT A ID: {BOT_A_ID}")

    logging.info(f"CHANNEL ID: {CHANNEL_ID}")

    logging.info(f"AI MODEL: {MODEL}")

    logging.info("ĐANG CHỜ CÂU ĐỐ...")

    logging.info("=" * 45)


# ==========================================
# START
# ==========================================

async def main():

    async with bot:

        await bot.start(DISCORD_TOKEN)


asyncio.run(main())