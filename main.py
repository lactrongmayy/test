import os
import re
import time
import asyncio
import logging
import unicodedata
from collections import Counter, OrderedDict
from typing import Optional, List, Dict, Tuple, Set

import aiohttp
import discord
from discord.ext import commands
from groq import AsyncGroq

# ==================================================
# CẤU HÌNH
# ==================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

WORDLIST_DIR = os.getenv("WORDLIST_DIR", "wordlists")
WORDLIST_SOURCES: Dict[str, List[str]] = {
    "Viet74K.txt": [
        "https://vietnamese-wordlist.duyet.net/Viet74K.txt",
        "https://raw.githubusercontent.com/duyet/vietnamese-wordlist/master/Viet74K.txt",
    ],
    "UTS_Dictionary.txt": [
        "https://huggingface.co/datasets/undertheseanlp/UTS_Dictionary/resolve/main/data/data.txt",
    ],
}
EXTRA_WORDS_FILE = os.path.join(WORDLIST_DIR, "extra_words.txt")

# Có thể override bằng env
BOT_A_ID = int(os.getenv("BOT_A_ID", "1248205177589334026"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "1564912638272602142"))
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

MAX_ATTEMPTS = 3
TEMPERATURES = [0.1, 0.4, 0.7]
CACHE_SIZE = 1500
MAX_AI_TOKENS = 64          # đáp án rất ngắn
SEND_RETRIES = 3
AI_RETRIES = 2

if not DISCORD_TOKEN:
    raise ValueError("Missing DISCORD_TOKEN")
if not GROQ_API_KEY:
    raise ValueError("Missing GROQ_API_KEY")


# ==================================================
# LOGGING
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("vua-tieng-viet")


# ==================================================
# DISCORD + GROQ
# ==================================================

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

ai = AsyncGroq(
    api_key=GROQ_API_KEY,
    max_retries=1,
    timeout=40.0,
)


# ==================================================
# BỘ NHỚ GIỚI HẠN
# ==================================================

class BoundedDict:
    """LRU-style dict với kích thước cố định."""
    def __init__(self, maxlen: int):
        self.maxlen = maxlen
        self._data: OrderedDict = OrderedDict()

    def __contains__(self, key) -> bool:
        return key in self._data

    def get(self, key, default=None):
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return default

    def set(self, key, value=True):
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self.maxlen:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)


processed = BoundedDict(CACHE_SIZE)      # đã trả lời thành công
attempted = BoundedDict(CACHE_SIZE)      # số lần đã thử
processing_locks: Dict[int, asyncio.Lock] = {}  # tránh race


# ==================================================
# TỪ ĐIỂN + CHỈ MỤC
# ==================================================

def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def letters_key(text: str) -> str:
    chars = [
        c for c in unicodedata.normalize("NFC", text).casefold()
        if c.isalpha()
    ]
    return "".join(sorted(chars))


ANAGRAMS: Dict[str, List[str]] = {}
SYLLABLES: Set[str] = set()
BIGRAMS: Set[Tuple[str, str]] = set()


def build_index(lines: List[str]) -> None:
    ANAGRAMS.clear()
    SYLLABLES.clear()
    BIGRAMS.clear()
    seen: Set[str] = set()

    for line in lines:
        word = normalize_text(line)
        if not word or word in seen:
            continue
        if not all(c.isalpha() or c in " -" for c in word):
            continue

        seen.add(word)
        key = letters_key(word)
        ANAGRAMS.setdefault(key, []).append(word)

        syllables = word.replace("-", " ").split()
        SYLLABLES.update(syllables)

        for left, right in zip(syllables, syllables[1:]):
            BIGRAMS.add((left, right))

    log.info(f"Indexed {len(seen)} entries | {len(SYLLABLES)} syllables | {len(BIGRAMS)} bigrams")


async def download_list(session: aiohttp.ClientSession, name: str, urls: List[str]) -> List[str]:
    path = os.path.join(WORDLIST_DIR, name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().splitlines()

    for url in urls:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    log.warning(f"{url} → HTTP {resp.status}")
                    continue
                text = await resp.text(encoding="utf-8")

            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            log.info(f"Downloaded {name}")
            return text.splitlines()
        except Exception as e:
            log.warning(f"Cannot download {url}: {e}")

    log.warning(f"Skipped {name}")
    return []


async def load_wordlist() -> None:
    os.makedirs(WORDLIST_DIR, exist_ok=True)
    lines: List[str] = []

    async with aiohttp.ClientSession() as session:
        tasks = [
            download_list(session, name, urls)
            for name, urls in WORDLIST_SOURCES.items()
        ]
        results = await asyncio.gather(*tasks)
        for r in results:
            lines.extend(r)

    if os.path.exists(EXTRA_WORDS_FILE):
        with open(EXTRA_WORDS_FILE, encoding="utf-8") as f:
            lines.extend(f.read().splitlines())

    if not lines:
        log.error("No wordlist available — falling back to AI only")
        return

    build_index(lines)


# ==================================================
# TIỆN ÍCH CÂU ĐỐ
# ==================================================

def extract_embed(message: discord.Message) -> str:
    parts: List[str] = []
    for embed in message.embeds:
        if embed.title:
            parts.append(embed.title)
        if embed.description:
            parts.append(embed.description)
        if embed.author and embed.author.name:
            parts.append(embed.author.name)
        for field in embed.fields:
            if field.name:
                parts.append(field.name)
            if field.value:
                parts.append(field.value)
        if embed.footer and embed.footer.text:
            parts.append(embed.footer.text)
    return "\n".join(parts).strip()


def extract_scrambled_letters(question: str) -> Optional[List[str]]:
    # Ưu tiên dạng **bold**
    match = re.search(
        r"Từ cần đoán:\s*\*\*(.*?)\*\*",
        question,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        match = re.search(
            r"Từ cần đoán:\s*(.+?)(?:\s*\(gồm|\n|$)",
            question,
            flags=re.IGNORECASE,
        )
    if not match:
        log.warning("Cannot find scrambled letters")
        return None

    raw = match.group(1).strip()
    parts = [
        unicodedata.normalize("NFC", p.strip()).casefold()
        for p in raw.split("/")
        if p.strip()
    ]
    if not parts:
        return None

    for p in parts:
        if not p.isalpha():
            log.warning(f"Invalid character in letters: {p}")
            return None
    return parts


def normalize_answer_letters(text: str) -> List[str]:
    text = unicodedata.normalize("NFC", text).casefold()
    return [c for c in text if c.isalpha()]


def validate_answer(answer: str, original_letters: List[str]) -> bool:
    return Counter(normalize_answer_letters(answer)) == Counter(
        "".join(original_letters)
    )


# ==================================================
# GHÉP ÂM TIẾT (cải tiến)
# ==================================================

def solve_by_syllables(
    letters: List[str],
    max_parts: int = 7,
    max_results: int = 40,
    top: int = 12,
    timeout: float = 4.5,
) -> List[str]:
    """
    Sinh các cụm từ có thứ tự ngay từ đầu, ưu tiên bigram.
    Tránh permutation toàn bộ → nhanh hơn rõ rệt.
    """
    deadline = time.monotonic() + timeout
    total = Counter("".join(letters))
    target_len = sum(total.values())

    # Chỉ giữ âm tiết khả thi
    fitting: List[Tuple[str, Counter]] = []
    for syl in SYLLABLES:
        cnt = Counter(syl)
        if all(total[c] >= n for c, n in cnt.items()):
            fitting.append((syl, cnt))

    # Sắp xếp theo độ dài giảm dần để ưu tiên âm tiết dài hơn (giảm branching)
    fitting.sort(key=lambda x: -len(x[0]))

    results: Dict[str, Tuple[int, int]] = {}  # phrase -> (bigram_score, -num_parts)

    def rec(chosen: List[str], remaining: Counter, used_len: int):
        if time.monotonic() > deadline or len(results) >= max_results:
            return

        if used_len == target_len:
            phrase = " ".join(chosen)
            # điểm bigram
            score = sum(
                1 for a, b in zip(chosen, chosen[1:]) if (a, b) in BIGRAMS
            )
            results[phrase] = (score, -len(chosen))
            return

        if len(chosen) >= max_parts:
            return

        # Ưu tiên âm tiết bắt đầu bằng chữ cái còn lại ít nhất (pruning nhẹ)
        for syl, cnt in fitting:
            if not all(remaining[c] >= n for c, n in cnt.items()):
                continue

            # cập nhật remaining
            for c, n in cnt.items():
                remaining[c] -= n
            chosen.append(syl)

            rec(chosen, remaining, used_len + sum(cnt.values()))

            chosen.pop()
            for c, n in cnt.items():
                remaining[c] += n

            if time.monotonic() > deadline or len(results) >= max_results:
                return

    rec([], Counter(total), 0)

    ranked = sorted(
        results.items(),
        key=lambda x: (x[1][0], x[1][1]),  # bigram cao → ít phần hơn
        reverse=True,
    )
    return [phrase for phrase, _ in ranked[:top]]


def segment_syllables(text: str, max_len: int = 7) -> Optional[List[str]]:
    """Tách chuỗi viết liền thành âm tiết hợp lệ (DP)."""
    text = text.replace(" ", "")
    n = len(text)
    best: List[Optional[List[str]]] = [None] * (n + 1)
    best[0] = []

    for i in range(1, n + 1):
        for j in range(max(0, i - max_len), i):
            if best[j] is None:
                continue
            piece = text[j:i]
            if piece in SYLLABLES:
                candidate = best[j] + [piece]
                if best[i] is None or len(candidate) < len(best[i]):
                    best[i] = candidate
    return best[n]


def repair_answer(answer: str) -> Optional[str]:
    if not SYLLABLES:
        return answer

    tokens = normalize_text(answer).split()
    if tokens and all(t in SYLLABLES for t in tokens):
        return " ".join(tokens)

    pieces = segment_syllables("".join(tokens))
    return " ".join(pieces) if pieces else None


# ==================================================
# GROQ
# ==================================================

async def ask_groq(prompt: str, temperature: float) -> Optional[str]:
    for attempt in range(AI_RETRIES + 1):
        try:
            response = await ai.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_completion_tokens=MAX_AI_TOKENS,
                reasoning_effort="low",
            )
            choice = response.choices[0]
            answer = (choice.message.content or "").strip()

            if not answer:
                log.warning(f"Empty AI response ({choice.finish_reason})")
                return None

            # Làm sạch
            answer = answer.replace("`", "").strip()
            answer = re.sub(
                r"^(đáp án|answer|kết quả)\s*[:：\-]?\s*",
                "",
                answer,
                flags=re.IGNORECASE,
            )
            lines = [ln.strip().strip("\"'") for ln in answer.splitlines() if ln.strip()]
            return lines[0] if lines else None

        except Exception as e:
            log.warning(f"Groq error (attempt {attempt + 1}): {e}")
            if attempt < AI_RETRIES:
                await asyncio.sleep(0.8 * (attempt + 1))
            else:
                return None
    return None


async def pick_candidate(question: str, candidates: List[str]) -> str:
    if len(candidates) == 1:
        return candidates[0]

    prompt = f"""Câu đố:
{question}

Các đáp án khả dĩ:
{chr(10).join("- " + c for c in candidates)}

Chọn đúng MỘT đáp án phù hợp ngữ cảnh nhất.
Chỉ trả về đáp án đó, không giải thích."""
    picked = await ask_groq(prompt, 0.1)
    if picked:
        norm = normalize_text(picked)
        for c in candidates:
            if normalize_text(c) == norm:
                return c
    return candidates[0]


async def solve_with_ai(question: str, original_letters: List[str]) -> Optional[str]:
    letters_text = " / ".join(original_letters)
    base_prompt = f"""Bạn là chuyên gia giải trò chơi Vua Tiếng Việt.

CÁC CHỮ CÁI (phải dùng hết, không thêm, không bớt):
{letters_text}

CÂU ĐỐ:
{question}

YÊU CẦU:
- Ghép thành từ hoặc cụm từ tiếng Việt có nghĩa.
- Sử dụng đúng toàn bộ chữ cái (kể cả dấu).
- Các âm tiết viết cách nhau bằng dấu cách (ví dụ: lá lúa).
- Chỉ trả về đáp án duy nhất.
- Không giải thích."""

    rejected: List[str] = []
    lenient: Optional[str] = None

    for attempt in range(MAX_ATTEMPTS):
        prompt = base_prompt
        if rejected:
            prompt += (
                "\n\nCác đáp án SAI, tuyệt đối không lặp lại: "
                + ", ".join(rejected)
                + "\nKiểm tra chính xác từng chữ cái và dấu."
            )

        temp = TEMPERATURES[min(attempt, len(TEMPERATURES) - 1)]
        log.info(f"AI attempt {attempt + 1}/{MAX_ATTEMPTS} (temp={temp})")

        answer = await ask_groq(prompt, temp)
        if not answer:
            continue

        log.info(f"AI raw: {answer}")
        fixed = repair_answer(answer)

        if fixed is None:
            log.warning("Rejected: invalid syllables")
            rejected.append(answer)
            if lenient is None and validate_answer(answer, original_letters):
                lenient = answer
            continue

        if validate_answer(fixed, original_letters):
            return fixed

        log.warning("Rejected: letter mismatch")
        rejected.append(answer)

    if lenient:
        log.info(f"Using lenient answer: {lenient}")
        return lenient
    return None


async def solve_question(question: str) -> Optional[str]:
    original_letters = extract_scrambled_letters(question)
    if not original_letters:
        return None

    letters_text = " / ".join(original_letters)
    log.info(f"Letters: {letters_text}")

    # 1. Anagram dictionary
    key = letters_key("".join(original_letters))
    candidates = ANAGRAMS.get(key, [])
    log.info(f"Dictionary hits: {candidates}")

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return await pick_candidate(question, candidates)

    # 2. Ghép âm tiết
    if SYLLABLES:
        combos = await asyncio.to_thread(solve_by_syllables, original_letters)
        log.info(f"Syllable candidates: {combos}")
        if combos:
            return await pick_candidate(question, combos)

    # 3. AI
    return await solve_with_ai(question, original_letters)


# ==================================================
# XỬ LÝ TIN NHẮN
# ==================================================

async def safe_send(channel: discord.abc.Messageable, content: str) -> bool:
    for attempt in range(SEND_RETRIES):
        try:
            await channel.send(
                content,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return True
        except discord.HTTPException as e:
            if e.status == 429:  # rate limit
                retry_after = getattr(e, "retry_after", 1.5)
                log.warning(f"Rate limited, sleep {retry_after:.1f}s")
                await asyncio.sleep(retry_after + 0.3)
            else:
                log.error(f"Discord HTTP {e.status}: {e}")
                if attempt < SEND_RETRIES - 1:
                    await asyncio.sleep(0.8 * (attempt + 1))
        except Exception as e:
            log.error(f"Send error: {e}")
            if attempt < SEND_RETRIES - 1:
                await asyncio.sleep(0.8 * (attempt + 1))
    return False


async def process_message(message: discord.Message) -> None:
    mid = message.id

    if mid in processed:
        return
    if message.author.id != BOT_A_ID:
        return
    if message.channel.id != CHANNEL_ID:
        return
    if not message.embeds:
        return

    question = extract_embed(message)
    if not question or "từ cần đoán" not in question.casefold():
        return

    # Giới hạn số lần thử
    tries = attempted.get(mid, 0)
    if tries >= 2:
        return
    attempted.set(mid, tries + 1)

    # Lock theo message_id
    lock = processing_locks.setdefault(mid, asyncio.Lock())
    if lock.locked():
        return

    async with lock:
        if mid in processed:  # double-check
            return

        try:
            log.info("=" * 50)
            log.info("NEW PUZZLE")
            log.info(question[:300] + ("..." if len(question) > 300 else ""))

            answer = await solve_question(question)
            if not answer:
                log.warning("No valid answer found")
                return

            ok = await safe_send(message.channel, answer)
            if ok:
                processed.set(mid)
                log.info(f"ANSWER SENT → {answer}")
            else:
                log.error("Failed to send answer after retries")

        except Exception:
            log.exception("Unexpected error in process_message")
        finally:
            # dọn lock cũ
            processing_locks.pop(mid, None)


# ==================================================
# EVENTS
# ==================================================

@bot.event
async def on_message(message: discord.Message):
    await process_message(message)
    await bot.process_commands(message)


@bot.event
async def on_raw_message_edit(payload: discord.RawMessageUpdateEvent):
    if payload.channel_id != CHANNEL_ID:
        return
    if payload.message_id in processed:
        return

    try:
        channel = bot.get_channel(payload.channel_id) or await bot.fetch_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
    except (discord.HTTPException, discord.NotFound):
        return

    await process_message(message)


@bot.event
async def setup_hook():
    await load_wordlist()


@bot.event
async def on_ready():
    log.info("=" * 50)
    log.info(f"BOT ONLINE  : {bot.user}")
    log.info(f"Watching bot: {BOT_A_ID}")
    log.info(f"Channel     : {CHANNEL_ID}")
    log.info(f"Model       : {MODEL}")
    log.info(f"Anagram groups: {len(ANAGRAMS)}")
    log.info("=" * 50)


# ==================================================
# START
# ==================================================

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)