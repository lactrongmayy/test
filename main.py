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

MAX_LAN = 100    # số lần tối đa cho phép nhập
DELAY = 1.5      # giây giữa mỗi tin (tránh rate limit)
# ==================================================

COUNT_FILE = "chat_count.json"
MENTIONS = discord.AllowedMentions.all()

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
    allowed_mentions=MENTIONS,
    allowed_installs=discord.app_commands.AppInstallationType(guild=True, user=True),
    allowed_contexts=discord.app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True)
)


# ==================== BẢNG NHẬP ====================
class ChatModal(discord.ui.Modal, title="Gửi tin nhắn"):
    noi_dung = discord.ui.TextInput(
        label="Nội dung",
        style=discord.TextStyle.paragraph,
        placeholder="Nhập nội dung (tag dùng <@ID> hoặc <@&ID>)",
        required=True,
        max_length=2000,
    )
    so_lan = discord.ui.TextInput(
        label=f"Số lần (1 - {MAX_LAN})",
        placeholder="Ví dụ: 10",
        default="1",
        required=True,
        max_length=3,
    )

    async def on_submit(self, interaction: discord.Interaction):
        global chat_count

        try:
            so_lan = int(self.so_lan.value.strip())
        except ValueError:
            await interaction.response.send_message("Số lần phải là số nguyên.", ephemeral=True)
            return
        if not 1 <= so_lan <= MAX_LAN:
            await interaction.response.send_message(f"Số lần phải từ 1 đến {MAX_LAN}.", ephemeral=True)
            return

        noi_dung = self.noi_dung.value
        channel = interaction.channel

        # 1. Bot phản hồi người dùng lệnh (công khai)
        await interaction.response.send_message("⏳ Đang gửi...", ephemeral=False)

        sent = 0

        # 2. Thử gửi thẳng vào kênh (không giới hạn số lượng)
        if channel is not None:
            try:
                for _ in range(so_lan):
                    await channel.send(noi_dung, allowed_mentions=MENTIONS)
                    sent += 1
                    await asyncio.sleep(DELAY)
            except (discord.Forbidden, discord.HTTPException, AttributeError) as e:
                print(f"Lỗi channel.send: {e}")

        # 3. Không gửi được vào kênh -> dùng followup (tối đa 5 tin)
        if sent == 0:
            for _ in range(min(so_lan, 5)):
                try:
                    await interaction.followup.send(noi_dung, allowed_mentions=MENTIONS)
                    sent += 1
                    await asyncio.sleep(DELAY)
                except discord.HTTPException as e:
                    print(f"Lỗi followup: {e}")
                    break

        # 4. Xóa câu phản hồi "Đang gửi..." (mất luôn dòng "đã sử dụng /chat")
        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            pass

        chat_count += sent
        save_count(chat_count)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"Lỗi modal: {error}")


# ==================== LỆNH ====================
@bot.event
async def on_ready():
    print(f"Bot đã online: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Đã đồng bộ {len(synced)} lệnh slash")
    except Exception as e:
        print(f"Lỗi đồng bộ lệnh: {e}")

@bot.tree.command(name="chat", description="Mở bảng nhập nội dung và số lần")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def chat(interaction: discord.Interaction):
    await interaction.response.send_modal(ChatModal())

bot.run(TOKEN)
