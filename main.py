import os
import re
import logging
import discord

from discord.ext import commands
from groq import AsyncGroq


# =====================================================
# CONFIG
# =====================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

BOT_A_ID = 1248205177589334026
CHANNEL_ID = 1564912638272602142

MODEL = "openai/gpt-oss-120b"


# =====================================================
# CHECK CONFIG
# =====================================================

if not DISCORD_TOKEN:
    raise ValueError("Thiếu DISCORD_TOKEN!")

if not GROQ_API_KEY:
    raise ValueError("Thiếu GROQ_API_KEY!")


# =====================================================
# LOGGING
# =====================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# =====================================================
# DISCORD BOT
# =====================================================

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =====================================================
# GROQ AI
# =====================================================

ai = AsyncGroq(
    api_key=GROQ_API_KEY,
    max_retries=3,
    timeout=45
)


# =====================================================
# MESSAGE TRACKING
# =====================================================

processed = set()
processing = set()


# =====================================================
# EXTRACT EMBED
# =====================================================

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


# =====================================================
# SOLVE QUESTION
# =====================================================

async def solve_question(question):

    prompt = f"""
Bạn là chuyên gia giải trò chơi ghép chữ tiếng Việt.

Nhiệm vụ:
Ghép các chữ cái được cung cấp thành từ hoặc cụm từ tiếng Việt có nghĩa.

QUY TẮC:
- Sử dụng đúng các chữ cái được cung cấp.
- Không tự ý thêm chữ cái.
- Không tự ý bỏ chữ cái.
- Giữ đúng dấu tiếng Việt.
- Chú ý số lượng ký tự.
- Ưu tiên đáp án phù hợp với ngữ cảnh.
- Nếu có nhiều khả năng, chọn đáp án hợp lý nhất.
- Chỉ trả về đáp án.
- Không giải thích.
- Không viết lời dẫn.

CÂU ĐỐ:
{question}
"""

    try:

        logging.info("Đang gửi câu hỏi đến Groq...")

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

            logging.error(
                f"AI trả về rỗng. "
                f"Finish reason: {choice.finish_reason}"
            )

            return None

        answer = answer.strip()
        answer = answer.replace("`", "")

        answer = re.sub(
            r"^(đáp án|answer)\s*[:：-]?\s*",
            "",
            answer,
            flags=re.IGNORECASE
        )

        answer = answer.splitlines()[0].strip()
        answer = answer.strip("\"'“”‘’")

        if not answer:
            return None

        logging.info(f"Đáp án AI: {answer}")

        return answer

    except Exception:

        logging.exception("Lỗi Groq API!")

        return None


# =====================================================
# PROCESS MESSAGE
# =====================================================

async def process_message(message):

    message_id = message.id

    if message_id in processed:
        return

    if message_id in processing:
        return

    # Chỉ nhận Bot A
    if message.author.id != BOT_A_ID:
        return

    # Chỉ nhận kênh chỉ định
    if message.channel.id != CHANNEL_ID:
        return

    # Chỉ nhận Embed
    if not message.embeds:
        return

    question = extract_embed(message)

    if not question:
        logging.warning("Embed không có nội dung.")
        return

    processing.add(message_id)

    try:

        logging.info("=" * 45)
        logging.info("NHẬN ĐƯỢC CÂU ĐỐ:")
        logging.info(question)

        answer = await solve_question(question)

        if not answer:
            logging.warning("Không tìm được đáp án.")
            return

        await message.reply(
            content=f"`{answer}`",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none()
        )

        logging.info(f"ĐÃ TRẢ LỜI: {answer}")

        processed.add(message_id)

    except discord.Forbidden:

        logging.error(
            "Bot thiếu quyền đọc hoặc gửi tin nhắn!"
        )

    except discord.HTTPException as e:

        logging.error(f"Lỗi Discord HTTP: {e}")

    except Exception:

        logging.exception("Lỗi xử lý tin nhắn!")

    finally:

        processing.discard(message_id)


# =====================================================
# NEW MESSAGE
# =====================================================

@bot.event
async def on_message(message):

    await process_message(message)

    await bot.process_commands(message)


# =====================================================
# EDIT MESSAGE
# =====================================================

@bot.event
async def on_message_edit(before, after):

    if before.embeds != after.embeds:

        processed.discard(after.id)

        await process_message(after)


# =====================================================
# BOT READY
# =====================================================

@bot.event
async def on_ready():

    logging.info("=" * 45)
    logging.info(f"BOT ONLINE: {bot.user}")
    logging.info(f"BOT A ID: {BOT_A_ID}")
    logging.info(f"CHANNEL ID: {CHANNEL_ID}")
    logging.info(f"AI MODEL: {MODEL}")
    logging.info("=" * 45)


# =====================================================
# START BOT
# =====================================================

bot.run(DISCORD_TOKEN)