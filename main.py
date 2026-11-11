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

DEFAULT_MESSAGE = "# NGU :)"
SO_LAN = 50      # số tin gửi mỗi lần gõ /chat
DELAY = 1.5      # giây giữa mỗi tin (tránh rate limit)
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

    # Báo đã nhận lệnh (chỉ mình bạn thấy)
    await interaction.response.defer(ephemeral=True)

    channel = interaction.channel
    sent = 0

    # Thử gửi thẳng vào kênh
    try:
        if channel is None:
            raise discord.Forbidden(None, "no channel")
        for _ in range(SO_LAN):
            await channel.send(DEFAULT_MESSAGE)
            sent += 1
            await asyncio.sleep(DELAY)
        await interaction.delete_original_response()

    # Không có quyền gửi vào kênh -> dùng followup (tối đa 5 tin)
    except (discord.Forbidden, discord.HTTPException):
        remaining = min(SO_LAN - sent, 5)
        for _ in range(remaining):
            try:
                await interaction.followup.send(DEFAULT_MESSAGE)
                sent += 1
                await asyncio.sleep(DELAY)
            except discord.HTTPException:
                break

    chat_count += sent
    save_count(chat_count)

bot.run(TOKEN)
