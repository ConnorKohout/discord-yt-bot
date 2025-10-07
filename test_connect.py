# bonebot.py
import os
import re
import asyncio
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
import yt_dlp

# -------------------------------------------------------------
# Load environment variables
# -------------------------------------------------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID_ENV = os.getenv("DISCORD_GUILD_ID")
GUILD_ID = int(GUILD_ID_ENV) if GUILD_ID_ENV and GUILD_ID_ENV.isdigit() else None
IDLE_TIMEOUT_MINUTES = int(os.getenv("IDLE_TIMEOUT_MINUTES", "30"))

# -------------------------------------------------------------
# Intents & Bot
# -------------------------------------------------------------
intents = discord.Intents.default()
# Only enable message content if you also use prefix commands; slash commands don't need it.
intents.message_content = bool(os.getenv("ENABLE_MESSAGE_CONTENT_INTENT", "0") == "1")
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# -------------------------------------------------------------
# Global State
# -------------------------------------------------------------
queues: dict[int, list[tuple[str, str]]] = {}     # guild_id -> list[(title, url)]
voice_clients: dict[int, discord.VoiceClient] = {}# guild_id -> VoiceClient
last_activity: dict[int, datetime] = {}           # guild_id -> datetime
playlist_processing_status: dict[int, bool] = {}  # guild_id -> bool

# -------------------------------------------------------------
# YTDL options & instances
# -------------------------------------------------------------
yt_dl_options = {
    'format': 'm4a/bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'm4a',
        'preferredquality': '140',
    }],
    'default_search': 'auto',
    'noplaylist': False,
    'ignoreerrors': True,
    'flat_playlist': True,  # metadata only, faster
    'verbose': True
}

# Optional chunked playlist configs (used by process_remaining_playlist)
first_ten = {
    'format': 'm4a/bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'm4a',
        'preferredquality': '140',
    }],
    'noplaylist': False,
    'playlist_items': '2-10',
    'verbose': False
}
eleventofifty = {
    'format': 'm4a/bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'm4a',
        'preferredquality': '140',
    }],
    'noplaylist': False,
    'playlist_items': '11-50',
    'verbose': False
}
fifty_one_to_one_hundred = {
    'format': 'm4a/bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'm4a',
        'preferredquality': '140',
    }],
    'noplaylist': False,
    'playlist_items': '51-100',
    'verbose': False
}
one_hundred_to_two_hundred = {
    'format': 'm4a/bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'm4a',
        'preferredquality': '140',
    }],
    'noplaylist': False,
    'playlist_items': '101-200',
    'verbose': False
}
two_hundred_to_three_hundred = {
    'format': 'm4a/bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'm4a',
        'preferredquality': '140',
    }],
    'noplaylist': False,
    'playlist_items': '201-300',
    'verbose': False
}
from_three_hundred_on = {
    'format': 'm4a/bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'm4a',
        'preferredquality': '140',
    }],
    'noplaylist': False,
    'playliststart': '301',
    'verbose': False
}

# YTDL instances
ytdl = yt_dlp.YoutubeDL(yt_dl_options)
opt1 = yt_dlp.YoutubeDL(first_ten)
opt2 = yt_dlp.YoutubeDL(eleventofifty)
opt3 = yt_dlp.YoutubeDL(fifty_one_to_one_hundred)
opt4 = yt_dlp.YoutubeDL(one_hundred_to_two_hundred)
opt5 = yt_dlp.YoutubeDL(two_hundred_to_three_hundred)
opt6 = yt_dlp.YoutubeDL(from_three_hundred_on)

# FFMPEG options
ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -filter:a "volume=0.25"'
}

# -------------------------------------------------------------
# Background idle disconnect task
# -------------------------------------------------------------
@tasks.loop(minutes=1)
async def check_idle():
    now = datetime.now()
    for guild_id, vc in list(voice_clients.items()):
        if not vc or not vc.is_connected():
            continue
        last = last_activity.get(guild_id, now)
        if (now - last) > timedelta(minutes=IDLE_TIMEOUT_MINUTES) and not vc.is_playing():
            try:
                await vc.disconnect(force=False)
            except Exception:
                pass
            voice_clients.pop(guild_id, None)
            queues.pop(guild_id, None)
            playlist_processing_status.pop(guild_id, None)
            print(f"[idle] Auto-disconnected from guild {guild_id} due to inactivity.")

@bot.event
async def on_ready():
    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            cmds = await bot.tree.sync(guild=guild)
            print(f"Synced {len(cmds)} command(s) to guild {GUILD_ID}: {[c.name for c in cmds]}")
        else:
            cmds = await bot.tree.sync()
            print(f"Synced {len(cmds)} global command(s).")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    check_idle.start()
    print("Ready")

# -------------------------------------------------------------
# Helpers
# -------------------------------------------------------------
def cleanup_guild_state(guild_id: int):
    queues.pop(guild_id, None)
    playlist_processing_status.pop(guild_id, None)
    last_activity[guild_id] = datetime.now()

async def fetch_stream_url(url: str) -> str:
    """Extract a direct audio URL via yt-dlp off the event loop."""
    loop = asyncio.get_running_loop()
    def _extract():
        return ytdl.extract_info(url, download=False)
    data = await loop.run_in_executor(None, _extract)
    if "url" not in data:
        raise Exception("No stream URL found from extractor.")
    return data["url"]

async def retry_with_backoff(func, *args, retries=5, initial_delay=2):
    delay = initial_delay
    for attempt in range(retries):
        try:
            return await func(*args)
        except Exception as e:
            print(f"[retry] Attempt {attempt+1}/{retries} failed: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise

async def connect_with_voice_reset(channel: discord.VoiceChannel, guild_id: int):
    """
    Try a normal connect; if the voice gateway closes with 4006 (dropped/invalid session),
    force-disconnect any lingering client and try again fresh.
    """
    try:
        return await channel.connect(reconnect=True)
    except discord.errors.ConnectionClosed as e:
        if getattr(e, "code", None) == 4006:
            # Hard reset: drop any cached VC and force a brand-new session
            try:
                vc = voice_clients.get(guild_id)
                if vc and vc.is_connected():
                    await vc.disconnect(force=True)
            except Exception:
                pass
            voice_clients.pop(guild_id, None)
            await asyncio.sleep(1)
            return await channel.connect(reconnect=False)
        raise

# -------------------------------------------------------------
# Playback pipeline
# -------------------------------------------------------------
async def play_next(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    last_activity[guild_id] = datetime.now()

    vc = voice_clients.get(guild_id)
    if not vc or not vc.is_connected():
        await interaction.followup.send("Not connected to a voice channel.")
        return

    if not queues.get(guild_id):
        # Queue empty; background idle task will eventually disconnect
        return

    next_title, next_url = queues[guild_id].pop(0)
    try:
        stream_url = await retry_with_backoff(fetch_stream_url, next_url)
        player = discord.FFmpegOpusAudio(stream_url, **ffmpeg_options)

        def _after_playback(error):
            if error:
                print(f"[player] Error: {error}")
            # Schedule next track safely from player thread
            bot.loop.call_soon_threadsafe(asyncio.create_task, play_next(interaction))

        voice_clients[guild_id].play(player, after=_after_playback)
        await interaction.followup.send(f"Now playing: {next_title}")
    except Exception as e:
        print(f"[player] Failed to play {next_title}: {e}")
        await interaction.followup.send(f"Error playing {next_title}. Skipping...")
        if queues[guild_id]:
            await play_next(interaction)
        else:
            cleanup_guild_state(guild_id)

# -------------------------------------------------------------
# Slash Commands
# -------------------------------------------------------------
@bot.tree.command(name="play", description="Play a song from YouTube")
@app_commands.describe(query="Song name or YouTube URL")
async def play_cmd(interaction: discord.Interaction, query: str):
    guild_id = interaction.guild_id
    last_activity[guild_id] = datetime.now()

    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("You need to be in a voice channel to use this command.")
        return

    if not interaction.response.is_done():
        await interaction.response.defer(thinking=True)

    # ---------- Resolve the first item BEFORE connecting to voice ----------
    # Use yt-dlp's ytsearch1 to avoid blocking HTML scraping
    if not re.match(r"^(https?://)?(www\.)?(youtube\.com|youtu\.?be)/.+$", query):
        source = f"ytsearch1:{query}"
    else:
        source = query

    ytdl_single = yt_dlp.YoutubeDL({**yt_dl_options, "noplaylist": True})
    loop = asyncio.get_running_loop()
    try:
        first_video = await loop.run_in_executor(
            None, lambda: ytdl_single.extract_info(source, download=False)
        )
        if 'entries' in first_video:
            first_video = first_video['entries'][0]
    except Exception as e:
        await interaction.followup.send(f"Search/extract failed: {e}", ephemeral=True)
        return

    # Queue it
    queues.setdefault(guild_id, []).append((first_video["title"], first_video["url"]))
    await interaction.followup.send(f"Added to queue: {first_video['title']}")

    # Kick off any playlist processing in the background if a playlist link was provided
    if "list=" in query:
        await interaction.followup.send("Playlist detected. Fetching more songs...")
        asyncio.create_task(process_remaining_playlist(interaction, query))

    # ---------- Connect to voice AFTER we have something queued ----------
    voice_channel = interaction.user.voice.channel
    existing_vc = voice_clients.get(guild_id)
    if existing_vc and existing_vc.is_connected():
        if existing_vc.channel != voice_channel:
            await existing_vc.move_to(voice_channel)
        vc = existing_vc
    else:
        try:
            vc = await connect_with_voice_reset(voice_channel, guild_id)
            voice_clients[guild_id] = vc
        except Exception as e:
            await interaction.followup.send(f"Could not connect to voice channel: {e}")
            return

    # Start playback if nothing is currently playing
    if not voice_clients[guild_id].is_playing():
        await play_next(interaction)

@bot.tree.command(name="skip", description="Skip the current track")
async def skip_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    last_activity[guild_id] = datetime.now()
    vc = voice_clients.get(guild_id)
    if not vc or not vc.is_connected():
        await interaction.response.send_message("Not connected.")
        return
    if vc.is_playing():
        vc.stop()
        await interaction.response.send_message("Skipped.")
    else:
        await interaction.response.send_message("Nothing is playing.")

@bot.tree.command(name="queue", description="Show the current queue")
async def queue_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    q = queues.get(guild_id, [])
    if not q:
        await interaction.response.send_message("Queue is empty.")
        return
    msg = "\n".join(f"{i+1}. {t}" for i, (t, _) in enumerate(q[:20]))
    if len(q) > 20:
        msg += f"\n...and {len(q)-20} more"
    await interaction.response.send_message(msg)

@bot.tree.command(name="stop", description="Stop playback and disconnect")
async def stop_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    vc = voice_clients.get(guild_id)
    if vc and vc.is_connected():
        queues[guild_id] = []
        try:
            await vc.disconnect(force=False)
        except Exception:
            pass
    voice_clients.pop(guild_id, None)
    cleanup_guild_state(guild_id)
    await interaction.response.send_message("Stopped and disconnected.")

# Diagnostic command retained (optional)
@bot.tree.command(name="pingvc", description="Test voice connect: join your voice and leave after 2s.")
async def pingvc_cmd(interaction: discord.Interaction):
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        vc = await interaction.user.voice.channel.connect(reconnect=True)
        await interaction.followup.send("Connected. Leaving in 2s…")
        await asyncio.sleep(2)
        await vc.disconnect()
    except Exception as e:
        await interaction.followup.send(f"Failed: {e}")

# -------------------------------------------------------------
# Playlist processing (optional / background)
# -------------------------------------------------------------
async def process_remaining_playlist(interaction: discord.Interaction, link: str):
    guild_id = interaction.guild_id
    playlist_processing_status[guild_id] = True
    loop = asyncio.get_running_loop()

    downloaders = [opt1, opt2, opt3, opt4, opt5, opt6]
    titles_added = 0

    async def _extract(dl, url):
        return await loop.run_in_executor(None, lambda: dl.extract_info(url, download=False))

    try:
        for dl in downloaders:
            try:
                info = await _extract(dl, link)
            except Exception:
                continue
            if not info:
                continue
            entries = info.get("entries") or []
            for e in entries:
                if not e:
                    continue
                title = e.get("title")
                url = e.get("url") or e.get("webpage_url") or e.get("original_url")
                if not title or not url:
                    continue
                queues.setdefault(guild_id, []).append((title, url))
                titles_added += 1

        if titles_added:
            await interaction.followup.send(f"Queued {titles_added} more tracks from the playlist.")
        else:
            await interaction.followup.send("No additional tracks found in the playlist.")
    finally:
        playlist_processing_status[guild_id] = False

# -------------------------------------------------------------
# Run
# -------------------------------------------------------------
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_BOT_TOKEN is not set.")
    bot.run(TOKEN)
