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

MAX_LAN = 5                # giới hạn của Discord mỗi lần: tối đa 5 followup
DELAY = 1.5                # giây giữa mỗi tin
TEXT_DANG_NHAP = "⌨️ Đang nhập..."
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


# ==================== GỬI MỘT ĐỢT (tối đa 5 tin) ====================
async def gui_dot(interaction: discord.Interaction, noi_dung: str, so_lan: int,
                  xoa_phan_hoi: bool = False):
    """Gửi so_lan tin bằng followup. Tin cuối có nút 'Gửi tiếp'."""
    global chat_count
    sent = 0

    for i in range(so_lan):
        await asyncio.sleep(DELAY)
        la_tin_cuoi = (i == so_lan - 1)
        try:
            if la_tin_cuoi:
                await interaction.followup.send(
                    noi_dung,
                    allowed_mentions=MENTIONS,
                    view=TiepView(noi_dung, so_lan, interaction.user.id),
                )
            else:
                await interaction.followup.send(noi_dung, allowed_mentions=MENTIONS)
            sent += 1
        except discord.HTTPException as e:
            print(f"Lỗi followup: {e}")
            break

        # Sau tin đầu tiên thì xóa "Đang nhập..."
        if i == 0 and xoa_phan_hoi:
            try:
                await interaction.delete_original_response()
            except discord.HTTPException:
                pass

    chat_count += sent
    save_count(chat_count)


# ==================== NÚT "GỬI TIẾP" ====================
class TiepView(discord.ui.View):
    def __init__(self, noi_dung: str, so_lan: int, user_id: int):
        super().__init__(timeout=900)
        self.noi_dung = noi_dung
        self.so_lan = so_lan
        self.user_id = user_id

    @discord.ui.button(label="Gửi tiếp", style=discord.ButtonStyle.primary, emoji="➡️")
    async def gui_tiep(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Chỉ người dùng lệnh mới bấm được
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Chỉ người dùng lệnh mới bấm được.", ephemeral=True)
            return

        # Gỡ nút khỏi tin cũ (đây là phản hồi của lần bấm này)
        await interaction.response.edit_message(view=None)

        # Gửi thêm một đợt mới, tin cuối lại có nút "Gửi tiếp"
        await gui_dot(interaction, self.noi_dung, self.so_lan)


@bot.event
async def on_ready():
    print(f"Bot đã online: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Đã đồng bộ {len(synced)} lệnh slash")
    except Exception as e:
        print(f"Lỗi đồng bộ lệnh: {e}")


# ==================== LỆNH /chat [nội dung] [số lần] ====================
@bot.tree.command(name="chat", description="Gửi tin nhắn nhiều lần")
@app_commands.describe(noi_dung="Nội dung cần gửi", so_lan=f"Số lần mỗi đợt (1 - {MAX_LAN})")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def chat(
    interaction: discord.Interaction,
    noi_dung: app_commands.Range[str, 1, 2000],
    so_lan: app_commands.Range[int, 1, MAX_LAN] = MAX_LAN,
):
    await interaction.response.send_message(TEXT_DANG_NHAP)
    await gui_dot(interaction, noi_dung, so_lan, xoa_phan_hoi=True)


bot.run(TOKEN)
