import os
import re
import asyncio
import logging
import time
import random

import discord
from discord.ext import commands
from google import genai


# ==========================================
# CONFIG
# ==========================================

TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

BOT_A_ID = 1248205177589334026
CHANNEL_ID = 1564912638272602142

MODELS = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite"
]

MAX_RETRIES = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ==========================================
# GEMINI CLIENT
# ==========================================

if not GEMINI_API_KEY:
    raise RuntimeError("Thiếu GEMINI_API_KEY")

if not TOKEN:
    raise RuntimeError("Thiếu DISCORD_TOKEN")

ai = genai.Client(
    api_key=GEMINI_API_KEY
)


# ==========================================
# DISCORD
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

def solve_question(question):

    prompt = f"""
Bạn là chuyên gia giải trò chơi ghép chữ tiếng Việt.

NHIỆM VỤ:

1. Đọc các chữ cái trong câu đố.
2. Ghép chúng thành từ hoặc cụm từ tiếng Việt có nghĩa.
3. Phải sử dụng đúng các chữ cái được cung cấp.
4. Chú ý dấu thanh và dấu tiếng Việt.
5. Không tự ý thêm hoặc bỏ chữ cái.
6. Phân tích ngữ cảnh để tìm đáp án phù hợp nhất.
7. Nếu có nhiều đáp án, chọn đáp án phù hợp nhất với câu hỏi.

CÂU ĐỐ:

{question}

YÊU CẦU TRẢ LỜI:

- Chỉ trả về đáp án.
- Không giải thích.
- Không đánh số.
- Không viết "Đáp án là".
- Không sử dụng Markdown.
- Không thêm bất kỳ nội dung nào khác.
"""

    for model in MODELS:

        logging.info(f"Đang sử dụng model: {model}")

        for attempt in range(MAX_RETRIES):

            try:

                response = ai.models.generate_content(
                    model=model,
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

                answer = answer.splitlines()[0].strip()

                if not answer:
                    raise ValueError("AI trả về đáp án rỗng")

                logging.info(
                    f"Đáp án từ {model}: {answer}"
                )

                return answer

            except Exception as error:

                logging.error(
                    f"{model} | Lần {attempt + 1}: {error}"
                )

                if attempt < MAX_RETRIES - 1:

                    wait = (2 ** (attempt + 1)) + random.uniform(0, 1)

                    time.sleep(wait)

        logging.warning(
            f"Model {model} không khả dụng. Chuyển model tiếp theo."
        )

    return None


# ==========================================
# PROCESS MESSAGE
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
            return

        logging.info("=" * 40)
        logging.info("ĐÃ NHẬN EMBED")
        logging.info(question)

        # Gọi AI không chặn Discord
        answer = await asyncio.to_thread(
            solve_question,
            question
        )

        if not answer:

            logging.error(
                "Tất cả model đều không trả lời được."
            )

            return

        answer = answer[:200]

        # Kiểm tra tin nhắn vẫn tồn tại
        await message.channel.fetch_message(message.id)

        # Reply đáp án
        await message.reply(
            content=f"`{answer}`",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none()
        )

        processed.add(message.id)

        # Giới hạn bộ nhớ cache
        if len(processed) > MAX_CACHE:
            processed.clear()

        logging.info(
            f"ĐÃ TRẢ LỜI: {answer}"
        )

    except discord.NotFound:

        logging.warning(
            "Embed đã bị xóa."
        )

    except Exception as error:

        logging.exception(
            f"Lỗi xử lý Embed: {error}"
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
# EDITED MESSAGE
# ==========================================

@bot.event
async def on_message_edit(before, after):

    if before.embeds != after.embeds:

        processed.discard(after.id)

        await process_message(after)


# ==========================================
# READY
# ==========================================

@bot.event
async def on_ready():

    logging.info("=" * 40)

    logging.info(
        f"BOT ONLINE: {bot.user}"
    )

    logging.info(
        f"BOT A ID: {BOT_A_ID}"
    )

    logging.info(
        f"CHANNEL ID: {CHANNEL_ID}"
    )

    logging.info(
        "Đang chờ Embed câu đố..."
    )

    logging.info("=" * 40)


# ==========================================
# START
# ==========================================

bot.run(TOKEN)