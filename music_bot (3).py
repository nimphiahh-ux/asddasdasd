import imageio_ffmpeg
FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import anthropic

discord.opus.load_opus('libopus.so.0')

# ─────────────────────────────────────────
#  설정
# ─────────────────────────────────────────
TOKEN = os.environ.get("TOKEN")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY")

# yt-dlp 옵션 (유튜브/사운드클라우드 등 지원)
YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    "cookiefile": "/app/cookies.txt",
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


# ─────────────────────────────────────────
#  봇 초기화
# ─────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ─────────────────────────────────────────
#  유틸: URL → 스트리밍 URL 추출
# ─────────────────────────────────────────
async def extract_audio_url(url: str) -> dict:
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
#  !틀어재껴 <url>  →  입장 + 재생
# ─────────────────────────────────────────
@bot.command(name="틀어재껴")
async def play(ctx, url: str = None):
    if not url:
        await ctx.send("❌ URL을 같이 입력해줘!  예) `!틀어재껴 https://youtu.be/xxxx`")
        return

    if not ctx.author.voice:
        await ctx.send("❌ 먼저 음성 채널에 들어가 있어야 해!")
        return

    voice_channel = ctx.author.voice.channel

    if ctx.voice_client:
        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        await ctx.voice_client.move_to(voice_channel)
        vc = ctx.voice_client
    else:
        vc = await voice_channel.connect()

    msg = await ctx.send("🔍 정보 긁어오는 중...")

    try:
        info = await extract_audio_url(url)
    except Exception as e:
        await msg.edit(content=f"❌ 재생 실패: `{e}`")
        if vc.is_connected():
            await vc.disconnect()
        return

    source = discord.FFmpegPCMAudio(info["stream_url"], executable=FFMPEG_PATH, **FFMPEG_OPTIONS)
    source = discord.PCMVolumeTransformer(source, volume=0.5)

    def after_play(error):
        if error:
            print(f"[재생 오류] {error}")
        coro = vc.disconnect()
        asyncio.run_coroutine_threadsafe(coro, bot.loop)

    vc.play(source, after=after_play)

    dur_min, dur_sec = divmod(info["duration"], 60)
    await msg.edit(
        content=(
            f"▶️ **{info['title']}** 재생 시작!\n"
            f"⏱️ {dur_min}분 {dur_sec}초 | 🔉 음량 50%\n"
            f"끄려면 `!적당히해`"
        )
    )


# ─────────────────────────────────────────
#  !적당히해  →  정지 + 퇴장
# ─────────────────────────────────────────
@bot.command(name="적당히해")
async def stop(ctx):
    vc = ctx.voice_client

    if not vc or not vc.is_connected():
        await ctx.send("❌ 봇이 음성 채널에 없는데?")
        return

    if vc.is_playing():
        vc.stop()

    await vc.disconnect()
    await ctx.send("⏹️ 정지하고 나왔어.")


# ─────────────────────────────────────────
#  !뭐라는거야 <텍스트>  →  Claude 의역 번역 (→ 한국어)
# ─────────────────────────────────────────
TRANSLATE_SYSTEM = """
너는 세상에서 가장 자연스러운 한국어 번역가야.
주어진 텍스트를 한국어로 번역하되 단순 직역이 아니라 완전한 의역을 해줘.
의도, 맥락, 문맥, 흐름, 상황, 어조, 스타일, 뉘앙스, 감정, 말투를 전부 살려서
실제 한국인이 그 상황에서 직접 쓴 것처럼 자연스럽게 옮겨줘.
구어체면 구어체로, 격식체면 격식체로, 욕이면 욕 뉘앙스도 살려서.
출력 형식은 딱 두 줄만:
언어: <감지된 언어 이름 (한국어로)>
번역: <번역 결과>
다른 말은 절대 붙이지 마.
""".strip()


@bot.command(name="뭐라는거야")
async def translate(ctx, *, text: str = None):
    if not text:
        await ctx.send("❌ 번역할 텍스트를 입력해줘!  예) `!뭐라는거야 what the hell is going on`")
        return

    msg = await ctx.send("🤔 읽어보는 중...")

    try:
        loop = asyncio.get_event_loop()

        def _call_claude():
            client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system=TRANSLATE_SYSTEM,
                messages=[{"role": "user", "content": text}],
            )
            return response.content[0].text.strip()

        raw = await loop.run_in_executor(None, _call_claude)

        lines = raw.splitlines()
        lang_line = next((l for l in lines if l.startswith("언어:")), None)
        trans_line = next((l for l in lines if l.startswith("번역:")), None)

        detected_lang = lang_line.split(":", 1)[1].strip() if lang_line else "알 수 없음"
        translated   = trans_line.split(":", 1)[1].strip() if trans_line else raw

        if detected_lang in ("한국어", "Korean", "ko"):
            await msg.edit(content="ℹ️ 이미 한국어야!")
            return

        embed = discord.Embed(color=0x5865F2)
        embed.set_author(name="🌐 번역 결과")
        embed.add_field(name=f"원문  ({detected_lang})", value=f"```{text}```", inline=False)
        embed.add_field(name="한국어 번역", value=f"```{translated}```", inline=False)
        embed.set_footer(text="translated by Claude ✦ 의역 버전")

        await msg.delete()
        await ctx.send(embed=embed)

    except Exception as e:
        await msg.edit(content=f"❌ 번역 실패: `{e}`")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ 인자가 빠졌어!\n`!틀어재껴 <URL>` / `!뭐라는거야 <텍스트>`")
    else:
        await ctx.send(f"⚠️ 오류 발생: `{error}`")


# ─────────────────────────────────────────
#  봇 실행
# ─────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ {bot.user} 로그인 완료")

bot.run(TOKEN)
