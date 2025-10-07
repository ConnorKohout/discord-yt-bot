# bonebot.py — YouTube + SoundCloud + Spotify (tuple queue preserved)
import os
import re
import asyncio
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
import yt_dlp

# Optional Spotify support
try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
except Exception:
    spotipy = None  # handled gracefully below

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
# URL matchers / helpers
# -------------------------------------------------------------
YOUTUBE_RE = re.compile(r'^(https?://)?(www\.)?(youtube\.com|youtu\.?be)/.+$', re.I)
SOUNDCLOUD_RE = re.compile(r'(?:https?://)?(?:www\.)?soundcloud\.com/\S+', re.I)

SPOTIFY_TRACK_RE = re.compile(r'open\.spotify\.com/(?:intl-[a-z]{2}/)?track/([A-Za-z0-9]+)', re.I)
SPOTIFY_PLAYLIST_RE = re.compile(r'open\.spotify\.com/(?:intl-[a-z]{2}/)?playlist/([A-Za-z0-9]+)', re.I)
SPOTIFY_ALBUM_RE = re.compile(r'open\.spotify\.com/(?:intl-[a-z]{2}/)?album/([A-Za-z0-9]+)', re.I)

def is_youtube_url(s: str) -> bool:
    return bool(YOUTUBE_RE.match(s))

def is_soundcloud_url(s: str) -> bool:
    return bool(SOUNDCLOUD_RE.search(s))

def is_spotify_url(s: str) -> bool:
    return 'open.spotify.com' in s

# -------------------------------------------------------------
# yt-dlp options & instances
# -------------------------------------------------------------
yt_dl_options = {
    # Prefer already-opus sources when possible; fall back to bestaudio.
    'format': 'bestaudio[acodec=opus]/bestaudio/best',
    'default_search': 'ytsearch',
    'noplaylist': False,
    'ignoreerrors': True,
    'quiet': True,
    'no_warnings': True,
    'extract_flat': 'in_playlist',  # fast playlist enumeration
}

ytdl = yt_dlp.YoutubeDL(yt_dl_options)

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
opt1 = yt_dlp.YoutubeDL(first_ten)
opt2 = yt_dlp.YoutubeDL(eleventofifty)
opt3 = yt_dlp.YoutubeDL(fifty_one_to_one_hundred)
opt4 = yt_dlp.YoutubeDL(one_hundred_to_two_hundred)
opt5 = yt_dlp.YoutubeDL(two_hundred_to_three_hundred)
opt6 = yt_dlp.YoutubeDL(from_three_hundred_on)

# FFMPEG options
ffmpeg_options = {
    'before_options': (
        '-nostdin '
        '-hide_banner -loglevel warning '
        '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 '
        '-rw_timeout 15000000 '           # 15s I/O timeout
        '-analyzeduration 0 -probesize 32k'  # fast start
    ),
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
    """Extract a direct audio URL via yt-dlp off the event loop. Robust for SoundCloud/HLS."""
    loop = asyncio.get_running_loop()
    def _extract():
        return ytdl.extract_info(url, download=False)
    data = await loop.run_in_executor(None, _extract)
    if not data:
        raise Exception("Extractor returned no data.")

    # Prefer top-level url if present
    if data.get("url"):
        return data["url"]

    # Fallback to requested_formats/formats (common on SoundCloud/HLS)
    fmts = data.get("requested_formats") or data.get("formats") or []
    for f in fmts:
        u = f.get("url")
        if u:
            return u

    raise Exception("No stream URL found from extractor.")

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

# ---- Spotify helpers -------------------------------------------------------
def _clean_title(s: str) -> str:
    # Remove bracketed fluff like (Remastered 2011), [Official Video], etc.
    return re.sub(r'\s*[\(\[\{].*?[\)\]\}]', '', s).strip()

def _get_spotify_client():
    if spotipy is None:
        return None, "Spotify support not installed. Run: pip install spotipy"
    cid = os.getenv("SPOTIFY_CLIENT_ID")
    sec = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not cid or not sec:
        return None, "Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in your environment (.env)."
    auth = SpotifyClientCredentials(client_id=cid, client_secret=sec)
    return spotipy.Spotify(auth_manager=auth), None

async def _yt_search_watch_url(query: str) -> tuple[str, str]:
    """Return (title, watch_url) for the best YouTube match."""
    loop = asyncio.get_running_loop()
    ytdl_single = yt_dlp.YoutubeDL({**yt_dl_options, "noplaylist": True})
    data = await loop.run_in_executor(None, lambda: ytdl_single.extract_info(f"ytsearch1:{query}", download=False))
    if not data or not data.get("entries"):
        raise RuntimeError(f"No YouTube results for: {query}")
    e = data["entries"][0]
    title = e.get("title") or query
    watch_url = e.get("webpage_url") or (f"https://www.youtube.com/watch?v={e.get('id')}" if e.get("id") else None)
    if not watch_url:
        raise RuntimeError("Could not resolve a YouTube watch URL.")
    return title, watch_url

async def _enqueue_spotify_track(interaction: discord.Interaction, sp, track_id: str):
    guild_id = interaction.guild_id
    loop = asyncio.get_running_loop()
    tr = await loop.run_in_executor(None, lambda: sp.track(track_id))
    if not tr:
        raise RuntimeError("Spotify track not found.")
    name = _clean_title(tr.get("name", ""))
    artists = ", ".join(a.get("name") for a in tr.get("artists", []) if a and a.get("name"))
    query = f"{artists} - {name}" if artists else name
    yt_title, yt_watch = await _yt_search_watch_url(query)
    queues.setdefault(guild_id, []).append((yt_title, yt_watch))
    await interaction.followup.send(f"Added to queue: {artists} – {name} (via Spotify)")

async def _collect_spotify_items(sp, kind: str, obj_id: str) -> list[tuple[str, str]]:
    """Collect (track_name, artist_names) pairs for a playlist/album."""
    items: list[tuple[str, str]] = []
    if kind == "playlist":
        results = sp.playlist_items(obj_id, additional_types=('track',), limit=100)
        while results:
            for item in results.get('items', []):
                tr = (item or {}).get('track') or {}
                if tr and tr.get('name'):
                    name = tr['name']
                    artists = ", ".join(a.get("name") for a in tr.get("artists", []) if a and a.get("name"))
                    items.append((name, artists))
            results = sp.next(results) if results.get('next') else None
    elif kind == "album":
        album = sp.album(obj_id)
        album_artists = ", ".join(a.get("name") for a in album.get("artists", []) if a and a.get("name"))
        results = sp.album_tracks(obj_id, limit=50)
        while results:
            for tr in results.get('items', []):
                if tr and tr.get('name'):
                    name = tr['name']
                    artists = ", ".join(a.get("name") for a in tr.get('artists', [])) or album_artists
                    items.append((name, artists))
            results = sp.next(results) if results.get('next') else None
    return items

async def _process_spotify_collection(interaction: discord.Interaction, sp, kind: str, obj_id: str, skip_first: int = 1):
    guild_id = interaction.guild_id
    loop = asyncio.get_running_loop()

    def _collect():
        return _collect_spotify_items(sp, kind, obj_id)

    meta_list = await loop.run_in_executor(None, _collect)
    meta_list = meta_list[skip_first:] if skip_first else meta_list

    added = 0
    for name, artists in meta_list:
        query = f"{artists} - {_clean_title(name)}" if artists else _clean_title(name)
        try:
            yt_title, yt_watch = await _yt_search_watch_url(query)
            queues.setdefault(guild_id, []).append((yt_title, yt_watch))
            added += 1
        except Exception as e:
            print(f"[spotify] Failed to map '{query}': {e}")

    if added:
        await interaction.followup.send(f"Queued {added} more from Spotify {kind}.")
    else:
        await interaction.followup.send(f"No additional playable items found in this Spotify {kind}.")

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
@bot.tree.command(name="play", description="Play a song from YouTube / SoundCloud / Spotify")
@app_commands.describe(query="Song name or URL (YouTube, SoundCloud, Spotify)")
async def play_cmd(interaction: discord.Interaction, query: str):
    guild_id = interaction.guild_id
    last_activity[guild_id] = datetime.now()

    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("You need to be in a voice channel to use this command.")
        return

    if not interaction.response.is_done():
        await interaction.response.defer(thinking=True)

    # ---------- Resolve the first item BEFORE connecting to voice ----------
    queued_any = False

    # Spotify links → map to YouTube and queue
    if is_spotify_url(query):
        sp, err = _get_spotify_client()
        if not sp:
            await interaction.followup.send(err)
            return

        m = SPOTIFY_TRACK_RE.search(query)
        if m:
            await _enqueue_spotify_track(interaction, sp, m.group(1))
            queued_any = True
        else:
            m_pl = SPOTIFY_PLAYLIST_RE.search(query)
            m_al = SPOTIFY_ALBUM_RE.search(query)
            if m_pl or m_al:
                kind = "playlist" if m_pl else "album"
                obj_id = (m_pl or m_al).group(1)

                # Pull the collection meta and queue the FIRST track immediately
                loop = asyncio.get_running_loop()
                def _first():
                    items = _collect_spotify_items(sp, kind, obj_id)
                    return items[0] if items else None

                first = await loop.run_in_executor(None, _first)
                if not first:
                    await interaction.followup.send(f"No playable items found in that Spotify {kind}.")
                    return

                name, artists = first
                query_first = f"{artists} - {_clean_title(name)}" if artists else _clean_title(name)
                yt_title, yt_watch = await _yt_search_watch_url(query_first)
                queues.setdefault(guild_id, []).append((yt_title, yt_watch))
                await interaction.followup.send(f"Added to queue: {artists} – {name} (via Spotify)")
                queued_any = True

                # Fetch the rest in the background
                asyncio.create_task(_process_spotify_collection(interaction, sp, kind, obj_id, skip_first=1))
            else:
                await interaction.followup.send("Unsupported Spotify URL.")
                return

    # SoundCloud links → feed straight to yt-dlp later (we only grab a title for UX)
    elif is_soundcloud_url(query):
        loop = asyncio.get_running_loop()
        try:
            # Get a nice title, but keep the URL as the SoundCloud page
            meta = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
            title = meta.get("title") or "SoundCloud track"
        except Exception:
            title = "SoundCloud track"
        queues.setdefault(guild_id, []).append((title, query))
        await interaction.followup.send(f"Added to queue: {title} (SoundCloud)")
        queued_any = True

    # YouTube link or plain search → original behavior
    else:
        source = query if is_youtube_url(query) else f"ytsearch1:{query}"
        ytdl_single = yt_dlp.YoutubeDL({**yt_dl_options, "noplaylist": True})
        loop = asyncio.get_running_loop()
        try:
            first_video = await loop.run_in_executor(
                None, lambda: ytdl_single.extract_info(source, download=False)
            )
            if 'entries' in first_video:
                first_video = first_video['entries'][0]
        except Exception as e:
            await interaction.followup.send(f"Search/extract failed: {e}")
            return

        queues.setdefault(guild_id, []).append((first_video["title"], first_video.get("webpage_url") or first_video.get("url")))
        await interaction.followup.send(f"Added to queue: {first_video['title']}")
        queued_any = True

    # ---------- Playlist expansion for native YouTube only ----------
    if queued_any and "list=" in query and is_youtube_url(query):
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
