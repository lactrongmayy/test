import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import asyncio

# ==================== CẤU HÌNH ====================
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    print("Lỗi: Chưa đặt biến môi trường TOKEN")
    exit()

DEFAULT_MESSAGE = """# NGU :)"""
SO_LAN = 50  # số lần gửi mỗi lần gõ /chat
# ==================================================

COUNT_FILE = "chat_count.json"

def load_count():
    if os.path.exists(COUNT_FILE):
        try:
            with open(COUNT_FILE, "r") as f:
                return json.load(f).get("count", 0)
        except:
            return 0
    return 0

def save_count(count):
    with open(COUNT_FILE, "w") as f:
        json.dump({"count": count}, f)

chat_count = load_count()

intents = discord.Intents.default()
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    allowed_installs=discord.app_commands.AppInstallationType(guild=True, user=True),
    allowed_contexts=discord.app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True)
)

@bot.event
async def on_ready():
    print(f"Bot đã online: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Đã đồng bộ {len(synced)} lệnh slash")
    except Exception as e:
        print(f"Lỗi đồng bộ lệnh: {e}")

@bot.tree.command(name="chat", description="Gửi tin nhắn mặc định vào kênh")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def chat(interaction: discord.Interaction):
    global chat_count

    # Tin đầu tiên
    await interaction.response.send_message(DEFAULT_MESSAGE)

    # Các tin còn lại
    for _ in range(SO_LAN - 1):
        await asyncio.sleep(1)  # tránh rate limit
        await interaction.followup.send(DEFAULT_MESSAGE)

    chat_count += SO_LAN
    save_count(chat_count)

bot.run(TOKEN)
