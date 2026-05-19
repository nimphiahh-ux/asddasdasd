````python
import imageio_ffmpeg
FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import anthropic
import ctypes.util
import glob

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
TOKEN = os.environ.get("TOKEN")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY")

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    "cookiefile": "cookies.txt",
}

FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_delay_max 5 "
        "-nostdin"
    ),
    "options": "-vn -ar 48000 -ac 2",
}

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ─────────────────────────────────────────
# Opus 로드
# ─────────────────────────────────────────
def load_opus():
    if discord.opus.is_loaded():
        return True

    candidates = [
        "/usr/lib/x86_64-linux-gnu/libopus.so.0",
        "/usr/lib/aarch64-linux-gnu/libopus.so.0",
        "/usr/lib/arm-linux-gnueabihf/libopus.so.0",
        "/usr/lib/libopus.so.0",
        "/usr/local/lib/libopus.so.0",
        "libopus.so.0",
        "libopus.so",
        "libopus",
    ]

    for pattern in [
        "/usr/lib/**/libopus.so.0",
        "/lib/**/libopus.so.0"
    ]:
        candidates.extend(glob.glob(pattern, recursive=True))

    found = ctypes.util.find_library("opus")

    if found:
        candidates.append(found)

    for name in candidates:
        try:
            discord.opus.load_opus(name)
            print(f"✅ Opus loaded: {name}")
            return True
        except:
            pass

    print("⚠️ Opus 로드 실패")
    return False


OPUS_LOADED = load_opus()

# ─────────────────────────────────────────
# 오디오 소스 생성
# ─────────────────────────────────────────
def make_audio_source(stream_url: str, volume: float = 0.5):

    opts = dict(FFMPEG_OPTIONS)
    opts["options"] = f"{opts['options']} -af volume={volume}"

    if OPUS_LOADED:
        return discord.FFmpegOpusAudio(
            stream_url,
            executable=FFMPEG_PATH,
            **opts,
        )

    return discord.FFmpegPCMAudio(
        stream_url,
        executable=FFMPEG_PATH,
        **opts,
    )

# ─────────────────────────────────────────
# yt-dlp URL 추출
# ─────────────────────────────────────────
async def extract_audio_url(url: str):

    loop = asyncio.get_event_loop()

    def _extract():
        with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:

            info = ydl.extract_info(url, download=False)

            if "entries" in info:
                info = info["entries"][0]

            return {
                "stream_url": info["url"],
                "title": info.get("title", "알 수 없는 제목"),
                "duration": info.get("duration", 0),
            }

    return await loop.run_in_executor(None, _extract)

# ─────────────────────────────────────────
# 음악 재생
# ─────────────────────────────────────────
@bot.command(name="틀어재껴")
async def play(ctx, url: str = None):

    if not url:
        await ctx.send("❌ URL 입력해줘!")
        return

    if not ctx.author.voice:
        await ctx.send("❌ 먼저 음성채널 들어가!")
        return

    voice_channel = ctx.author.voice.channel

    try:
        if ctx.voice_client:

            vc = ctx.voice_client

            if vc.channel != voice_channel:
                await vc.move_to(voice_channel)

        else:
            vc = await voice_channel.connect()
            await asyncio.sleep(2)

        if not vc.is_connected():
            await ctx.send("❌ 음성채널 연결 실패")
            return

    except Exception as e:
        await ctx.send(f"❌ 연결 오류: {e}")
        return

    msg = await ctx.send("🔍 정보 가져오는 중...")

    try:
        info = await extract_audio_url(url)

    except Exception as e:

        await msg.edit(content=f"❌ 재생 실패: {e}")

        if vc.is_connected():
            await vc.disconnect()

        return

    try:
        source = make_audio_source(
            info["stream_url"],
            volume=0.5
        )

    except Exception as e:

        await msg.edit(content=f"❌ 오디오 생성 실패: {e}")

        if vc.is_connected():
            await vc.disconnect()

        return

    def after_play(error):

        if error:
            print(f"[재생 오류] {error}")

        future = asyncio.run_coroutine_threadsafe(
            vc.disconnect(),
            bot.loop
        )

        try:
            future.result()
        except:
            pass

    vc.play(source, after=after_play)

    dur_min, dur_sec = divmod(info["duration"], 60)

    await msg.edit(
        content=(
            f"▶️ {info['title']}\n"
            f"⏱️ {dur_min}분 {dur_sec}초 재생 시작!"
        )
    )

# ─────────────────────────────────────────
# 음악 정지
# ─────────────────────────────────────────
@bot.command(name="적당히해")
async def stop(ctx):

    vc = ctx.voice_client

    if not vc or not vc.is_connected():
        await ctx.send("❌ 봇이 음성채널에 없어!")
        return

    if vc.is_playing():
        vc.stop()

    await vc.disconnect()

    await ctx.send("⏹️ 음악 정지")

# ─────────────────────────────────────────
# 번역 시스템
# ─────────────────────────────────────────
TRANSLATE_SYSTEM = """
너는 세상에서 가장 자연스러운 한국어 번역가야.
단순 직역이 아니라 맥락과 감정을 살린 의역을 해줘.
출력 형식:
언어: <언어>
번역: <번역결과>
""".strip()

# ─────────────────────────────────────────
# 번역 명령어
# ─────────────────────────────────────────
@bot.command(name="뭐라는거야")
async def translate(ctx, *, text: str = None):

    if not text:
        await ctx.send("❌ 번역할 텍스트 입력해줘!")
        return

    msg = await ctx.send("🤔 번역 중...")

    try:

        loop = asyncio.get_event_loop()

        def _call_claude():

            client = anthropic.Anthropic(
                api_key=ANTHROPIC_KEY
            )

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system=TRANSLATE_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": text
                    }
                ],
            )

            return response.content[0].text.strip()

        raw = await loop.run_in_executor(
            None,
            _call_claude
        )

        lines = raw.splitlines()

        lang_line = next(
            (l for l in lines if l.startswith("언어:")),
            None
        )

        trans_line = next(
            (l for l in lines if l.startswith("번역:")),
            None
        )

        detected_lang = (
            lang_line.split(":", 1)[1].strip()
            if lang_line else "알 수 없음"
        )

        translated = (
            trans_line.split(":", 1)[1].strip()
            if trans_line else raw
        )

        embed = discord.Embed(
            title="🌐 번역 결과",
            color=0x5865F2
        )

        embed.add_field(
            name=f"원문 ({detected_lang})",
            value=f"```{text}```",
            inline=False
        )

        embed.add_field(
            name="한국어 번역",
            value=f"```{translated}```",
            inline=False
        )

        await msg.delete()

        await ctx.send(embed=embed)

    except Exception as e:
        await msg.edit(content=f"❌ 번역 실패: {e}")

# ─────────────────────────────────────────
# 에러 핸들러
# ─────────────────────────────────────────
@bot.event
async def on_command_error(ctx, error):

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ 인자가 부족해!")
    else:
        await ctx.send(f"⚠️ 오류 발생: {error}")

# ─────────────────────────────────────────
# 로그인 완료
# ─────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ 로그인 완료: {bot.user}")

# ─────────────────────────────────────────
# 실행
# ─────────────────────────────────────────
bot.run(TOKEN)
````
