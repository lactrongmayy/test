import os
import re
import logging
import discord

from discord.ext import commands
from groq import AsyncGroq


# =====================================================
# CẤU HÌNH
# =====================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ID bot gửi câu đố
BOT_A_ID = 1248205177589334026

# ID kênh cần theo dõi
CHANNEL_ID = 1564912638272602142

# Model Groq
MODEL = "llama-3.3-70b-versatile"


# =====================================================
# KIỂM TRA CẤU HÌNH
# =====================================================

if not DISCORD_TOKEN:
    raise ValueError("Thiếu DISCORD_TOKEN!")

if not GROQ_API_KEY:
    raise ValueError("Thiếu GROQ_API_KEY!")


# =====================================================
# LOG
# =====================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# =====================================================
# KHỞI TẠO
# =====================================================

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

ai = AsyncGroq(
    api_key=GROQ_API_KEY,
    max_retries=3,
    timeout=30
)

# Lưu ID tin nhắn đã xử lý
processed = set()

# Lưu ID tin nhắn đang xử lý
processing = set()


# =====================================================
# ĐỌC NỘI DUNG EMBED
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

        if embed.fields:
            for field in embed.fields:

                if field.name:
                    contents.append(field.name)

                if field.value:
                    contents.append(field.value)

        if embed.footer and embed.footer.text:
            contents.append(embed.footer.text)

    return "\n".join(contents).strip()


# =====================================================
# GIẢI CÂU ĐỐ BẰNG GROQ
# =====================================================

async def solve_question(question):

    prompt = f"""
Bạn là chuyên gia giải trò chơi ghép chữ tiếng Việt.

Nhiệm vụ:
Đọc câu đố và ghép các chữ cái thành từ hoặc cụm từ tiếng Việt có nghĩa.

QUY TẮC:
- Sử dụng đúng các chữ cái được cung cấp.
- Không tự ý thêm chữ cái.
- Không tự ý bỏ chữ cái.
- Giữ đúng dấu tiếng Việt.
- Chú ý số lượng ký tự được đề cập trong câu đố.
- Ưu tiên đáp án phù hợp với ngữ cảnh.
- Nếu có nhiều khả năng, chọn đáp án hợp lý nhất.
- Chỉ trả về đáp án.
- Không giải thích.
- Không viết thêm lời dẫn.

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
            max_completion_tokens=512
        )

        choice = response.choices[0]

        answer = choice.message.content or ""

        if not answer.strip():

            logging.error(
                "AI không trả về nội dung. "
                f"Finish reason: {choice.finish_reason}"
            )

            return None

        answer = answer.strip()

        # Xóa dấu ngoặc code nếu AI tự thêm
        answer = answer.replace("`", "")

        # Xóa phần mở đầu không cần thiết
        answer = re.sub(
            r"^(đáp án|answer)\s*[:：-]?\s*",
            "",
            answer,
            flags=re.IGNORECASE
        )

        # Chỉ lấy dòng đầu tiên
        answer = answer.splitlines()[0].strip()

        # Loại bỏ dấu ngoặc kép ở hai đầu
        answer = answer.strip("\"'“”‘’")

        if not answer:
            return None

        logging.info(f"Đáp án AI: {answer}")

        return answer

    except Exception:

        logging.exception("Lỗi khi gọi Groq!")

        return None


# =====================================================
# XỬ LÝ TIN NHẮN
# =====================================================

async def process_message(message):

    message_id = message.id

    if message_id in processed:
        return

    if message_id in processing:
        return

    # Chỉ nhận tin nhắn từ Bot A
    if message.author.id != BOT_A_ID:
        return

    # Chỉ theo dõi kênh đã cài đặt
    if message.channel.id != CHANNEL_ID:
        return

    # Chỉ xử lý tin nhắn có Embed
    if not message.embeds:
        return

    question = extract_embed(message)

    if not question:
        logging.warning("Embed không có nội dung văn bản.")
        return

    processing.add(message_id)

    try:

        logging.info("=" * 40)
        logging.info("NHẬN ĐƯỢC CÂU ĐỐ:")
        logging.info(question)

        answer = await solve_question(question)

        if not answer:
            logging.warning("Không tìm được đáp án.")
            return

        # Trả lời tin nhắn gốc
        await message.reply(
            content=f"`{answer}`",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none()
        )

        logging.info(f"Đã gửi đáp án: {answer}")

        processed.add(message_id)

    except discord.Forbidden:

        logging.error(
            "Bot không có quyền gửi tin nhắn trong kênh!"
        )

    except discord.HTTPException as e:

        logging.error(f"Lỗi Discord: {e}")

    except Exception:

        logging.exception("Lỗi khi xử lý câu đố!")

    finally:

        processing.discard(message_id)


# =====================================================
# NHẬN TIN NHẮN MỚI
# =====================================================

@bot.event
async def on_message(message):

    await process_message(message)

    await bot.process_commands(message)


# =====================================================
# XỬ LÝ KHI EMBED ĐƯỢC CHỈNH SỬA
# =====================================================

@bot.event
async def on_message_edit(before, after):

    if before.embeds != after.embeds:

        # Cho phép xử lý lại tin nhắn đã chỉnh sửa
        processed.discard(after.id)

        await process_message(after)


# =====================================================
# BOT KHỞI ĐỘNG
# =====================================================

@bot.event
async def on_ready():

    logging.info("=" * 45)
    logging.info(f"Bot đã online: {bot.user}")
    logging.info(f"Bot A ID: {BOT_A_ID}")
    logging.info(f"Kênh theo dõi: {CHANNEL_ID}")
    logging.info(f"AI Model: {MODEL}")
    logging.info("=" * 45)


# =====================================================
# CHẠY BOT
# =====================================================

bot.run(DISCORD_TOKEN)