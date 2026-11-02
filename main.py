import os
import re
import logging
import unicodedata
from collections import Counter

import discord
from discord.ext import commands
from groq import AsyncGroq

=====================================================

CẤU HÌNH

=====================================================

DISCORD_TOKEN = os.getenv(“DISCORD_TOKEN”)
GROQ_API_KEY = os.getenv(“GROQ_API_KEY”)

BOT_A_ID = 1248205177589334026
CHANNEL_ID = 1564912638272602142

MODEL = “openai/gpt-oss-120b”

if not DISCORD_TOKEN:
raise ValueError(“Thiếu DISCORD_TOKEN!”)

if not GROQ_API_KEY:
raise ValueError(“Thiếu GROQ_API_KEY!”)

=====================================================

LOGGING

=====================================================

logging.basicConfig(
level=logging.INFO,
format=”%(asctime)s | %(levelname)s | %(message)s”
)

=====================================================

KHỞI TẠO

=====================================================

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True

bot = commands.Bot(
command_prefix=”!”,
intents=intents
)

ai = AsyncGroq(
api_key=GROQ_API_KEY,
max_retries=3,
timeout=45
)

processed = set()
processing = set()

=====================================================

ĐỌC EMBED

=====================================================

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

=====================================================

TÁCH CHỮ CÁI

=====================================================

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
    logging.warning("Không tìm thấy chữ cái.")
    return None
raw = match.group(1).strip()
parts = [
    unicodedata.normalize("NFC", item.strip()).casefold()
    for item in raw.split("/")
    if item.strip()
]
letters = []
for part in parts:
    if len(part) != 1 or not part.isalpha():
        logging.warning(f"Ký tự không hợp lệ: {part}")
        return None
    letters.append(part)
return letters if letters else None

=====================================================

CHUẨN HÓA ĐÁP ÁN

=====================================================

def normalize_answer(text):

text = unicodedata.normalize(
    "NFC",
    text
).casefold()
return [
    char for char in text
    if char.isalpha()
]

=====================================================

KIỂM TRA CHỮ CÁI

=====================================================

def validate_answer(answer, original_letters):

answer_letters = normalize_answer(answer)
if not answer_letters:
    return False
original_counter = Counter(original_letters)
answer_counter = Counter(answer_letters)
valid = original_counter == answer_counter
if not valid:
    logging.warning("Đáp án không khớp chữ cái!")
    logging.warning(f"Đề bài: {original_counter}")
    logging.warning(f"Đáp án: {answer_counter}")
return valid

=====================================================

GỌI GROQ

=====================================================

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
        f"AI trả về rỗng: {choice.finish_reason}"
    )
    return None
answer = answer.strip().replace("`", "")
answer = re.sub(
    r"^(đáp án|answer)\s*[:：-]?\s*",
    "",
    answer,
    flags=re.IGNORECASE
)
return answer.splitlines()[0].strip().strip("\"'“”‘’")

=====================================================

GIẢI CÂU ĐỐ

=====================================================

async def solve_question(question):

original_letters = extract_scrambled_letters(question)
if not original_letters:
    logging.error("Không lấy được chữ cái.")
    return None
letters_text = " / ".join(original_letters)
logging.info(f"Các chữ cần ghép: {letters_text}")
prompt = f"""

Bạn là chuyên gia giải trò chơi Vua Tiếng Việt.

Hãy ghép các chữ cái sau thành từ hoặc cụm từ tiếng Việt có nghĩa.

CÁC CHỮ CÁI:
{letters_text}

CÂU ĐỐ:
{question}

YÊU CẦU:

* Sử dụng toàn bộ chữ cái.
* Mỗi chữ cái chỉ sử dụng đúng số lần xuất hiện.
* Không thêm chữ cái.
* Không bỏ chữ cái.
* Giữ nguyên dấu tiếng Việt.
* Có thể ghép thành nhiều tiếng.
* Ưu tiên từ có nghĩa và phù hợp ngữ cảnh.
* Chỉ trả về đáp án.
* Không giải thích.
    “””
    for attempt in range(3):

  try:
      logging.info(
          f"Đang giải lần {attempt + 1}/3..."
      )
      current_prompt = prompt
      if attempt > 0:
          current_prompt += """

Đáp án trước không vượt qua kiểm tra chữ cái.
Hãy suy nghĩ lại từ đầu.
Kiểm tra kỹ từng chữ cái và dấu tiếng Việt.
Không được lặp lại đáp án sai.
“””

        answer = await ask_groq(current_prompt)
        if not answer:
            continue
        logging.info(f"AI đề xuất: {answer}")
        if validate_answer(answer, original_letters):
            logging.info("ĐÁP ÁN HỢP LỆ!")
            return answer
        logging.warning("Đáp án sai, thử lại...")
    except Exception:
        logging.exception("Lỗi Groq API!")
logging.error("Không tìm được đáp án hợp lệ.")
return None

=====================================================

XỬ LÝ TIN NHẮN

=====================================================

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
    logging.info("NHẬN ĐƯỢC CÂU ĐỐ:")
    logging.info(question)
    answer = await solve_question(question)
    if not answer:
        logging.warning(
            "Không có đáp án hợp lệ. Không gửi."
        )
        return
    await message.reply(
        content=f"`{answer}`",
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none()
    )
    logging.info(f"ĐÃ GỬI ĐÁP ÁN: {answer}")
    processed.add(message_id)
except discord.Forbidden:
    logging.error("Bot thiếu quyền gửi tin nhắn!")
except discord.HTTPException as e:
    logging.error(f"Lỗi Discord: {e}")
except Exception:
    logging.exception("Lỗi xử lý tin nhắn!")
finally:
    processing.discard(message_id)

=====================================================

TIN NHẮN MỚI

=====================================================

@bot.event
async def on_message(message):

await process_message(message)
await bot.process_commands(message)

=====================================================

EMBED ĐƯỢC CHỈNH SỬA

=====================================================

@bot.event
async def on_message_edit(before, after):

if before.embeds != after.embeds:
    processed.discard(after.id)
    await process_message(after)

=====================================================

BOT ONLINE

=====================================================

@bot.event
async def on_ready():

logging.info("=" * 45)
logging.info(f"BOT ONLINE: {bot.user}")
logging.info(f"BOT A ID: {BOT_A_ID}")
logging.info(f"CHANNEL ID: {CHANNEL_ID}")
logging.info(f"AI MODEL: {MODEL}")
logging.info("KIỂM TRA CHỮ CÁI: ENABLED")
logging.info("=" * 45)

=====================================================

START BOT

=====================================================

bot.run(DISCORD_TOKEN)