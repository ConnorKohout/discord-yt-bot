import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import asyncio
import yt_dlp
import urllib.parse, urllib.request, re
from datetime import datetime, timedelta
import time, random

youtube_search_base = "https://www.youtube.com/results?"
queues = {}
voice_clients = {}
last_activity = {}  # Tracks the last activity time for each guild
playlist_processing_status = {}

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
finish = {
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

# YTDL and FFMPEG options
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
        'flat_playlist': True,  # Retrieve basic metadata only
        'verbose': True
    }

ytdl = yt_dlp.YoutubeDL(yt_dl_options)
opt1 = yt_dlp.YoutubeDL(first_ten)
opt2 = yt_dlp.YoutubeDL(eleventofifty)
opt3 = yt_dlp.YoutubeDL(fifty_one_to_one_hundred)
opt4 = yt_dlp.YoutubeDL(one_hundred_to_two_hundred)
opt5 = yt_dlp.YoutubeDL(two_hundred_to_three_hundred)
opt6 = yt_dlp.YoutubeDL(finish)


ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -filter:a "volume=0.25"'
}
youtube_base_url = 'https://www.youtube.com/'
youtube_results_url = youtube_base_url + 'results?'
youtube_watch_url = youtube_base_url + 'watch?v='

# Auto-disconnect timeout (in minutes)
IDLE_TIMEOUT = 30

# Queue management functions

def get_queue(guild_id):
    """Get the queue for a specific guild."""
    if guild_id not in queues:
        queues[guild_id] = []
    return queues[guild_id]

def add_to_queue(guild_id, title, url):
    """Add a song to the queue."""
    queue = get_queue(guild_id)
    queue.append((title, url))
    return queue

def clear_queue(guild_id):
    """Clear the queue for a specific guild."""
    if guild_id in queues:
        queues[guild_id].clear()
        return True
    return False

def remove_from_queue(guild_id, index):
    """Remove a specific song from the queue by index."""
    queue = get_queue(guild_id)
    if 0 <= index < len(queue):
        return queue.pop(index)
    return None

def show_queue(guild_id):
    """Get a list of songs in the queue."""
    return get_queue(guild_id)

async def setup_music_commands(bot):
    @tasks.loop(minutes=1)
    async def check_idle():
        now = datetime
        for guild_id, voice_client in list(voice_clients.items()):
            if guild_id in last_activity:
                if now - last_activity[guild_id] > timedelta(minutes=IDLE_TIMEOUT):
                    print(f"Auto-disconnecting from guild {guild_id} due to inactivity.")
                    await voice_client.disconnect()
                    del voice_clients[guild_id]
                    if guild_id in queues:
                        del queues[guild_id]

    # Music commands
    @bot.command(name="play")
    async def play(ctx, *, query):
        global last_activity
        last_activity[ctx.guild.id] = datetime.now()

        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send("You need to be in a voice channel to use this command.")
            return

        voice_channel = ctx.author.voice.channel
        if ctx.guild.id not in voice_clients or voice_clients[ctx.guild.id] is None or not voice_clients[ctx.guild.id].is_connected():
            voice_clients[ctx.guild.id] = await voice_channel.connect()
        else:
            voice_client = voice_clients[ctx.guild.id]
            if voice_client.channel != voice_channel:
                await voice_client.move_to(voice_channel)

        if ctx.guild.id not in queues:
            queues[ctx.guild.id] = []

        try:
            # Handle search query (if it's not a direct link)
            if not re.match(r"^(https?://)?(www\.)?(youtube\.com|youtu\.?be)/.+$", query):
                search_query = urllib.parse.urlencode({"search_query": query})
                search_url = f"{youtube_search_base}{search_query}"
                html_content = urllib.request.urlopen(search_url)
                search_results = re.findall(r"watch\?v=(\S{11})", html_content.read().decode())
                if not search_results:
                    await ctx.send("No search results found.")
                    return
                query = f"https://www.youtube.com/watch?v={search_results[0]}"

            # Save original query to detect playlists
            original_query = query

            # Setup yt-dlp downloaders
            ytdl_single = yt_dlp.YoutubeDL({**yt_dl_options, "noplaylist": True})
            ytdl_playlist = yt_dlp.YoutubeDL({**yt_dl_options, "noplaylist": False})

            loop = asyncio.get_event_loop()

            # Fetch the first video (single item)
            first_video = await loop.run_in_executor(None, lambda: ytdl_single.extract_info(query, download=False))
            if not first_video:
                await ctx.send("Failed to fetch video information. Please try again.")
                return

            queues[ctx.guild.id].append((first_video["title"], first_video["url"]))
            await ctx.send(f"Added to queue: {first_video['title']}")

            # Detect and process playlist (if applicable)
            if "list=" in original_query:
                await ctx.send("Playlist detected — fetching remaining songs...")

                async def handle_playlist():
                    try:
                        await process_remaining_playlist(ctx, original_query, ytdl_playlist)
                    except Exception as playlist_error:
                        print(f"Error processing playlist: {playlist_error}")
                        await ctx.send("An error occurred while processing the playlist. Continuing with available songs.")

                asyncio.create_task(handle_playlist())

            # Start playback if not already playing
            if not voice_clients[ctx.guild.id].is_playing():
                await play_next(ctx)

        except Exception as e:
            print(f"Error during play command: {e}")
            await ctx.send("An unexpected error occurred while processing your request.")


    async def process_remaining_playlist(ctx, link, ytdl):
        """Processes the remaining songs in a playlist asynchronously with retry logic."""
        playlist_processing_status[ctx.guild.id] = True
        try:
            loop = asyncio.get_event_loop()
            playlist_data = await loop.run_in_executor(None, lambda: opt1.extract_info(link, download=False))

            for entry in playlist_data["entries"][:]:
                if entry is None:
                    print("Skipped an unavailable or private video.")
                    continue
                queues[ctx.guild.id].append((entry["title"], entry["url"]))
                print(f"Added to queue: {entry['title']}")

            if len([e for e in playlist_data['entries'][:] if e]) != 0:
                await ctx.send(f"Queued {len([e for e in playlist_data['entries'][:] if e])} additional songs.")

            playlist_data2 = await loop.run_in_executor(None, lambda: opt2.extract_info(link, download=False))
            for entry in playlist_data2["entries"][:]:
                if entry is None:
                    print("Skipped an unavailable or private video.")
                    continue
                queues[ctx.guild.id].append((entry["title"], entry["url"]))
                print(f"Added to queue: {entry['title']}")

            if len([e for e in playlist_data2['entries'][:] if e]) != 0:
                await ctx.send(f"Queued {len([e for e in playlist_data2['entries'][:] if e])} additional songs.")

            playlist_data3 = await loop.run_in_executor(None, lambda: opt3.extract_info(link, download=False))
            for entry in playlist_data3["entries"][:]:
                if entry is None:
                    print("Skipped an unavailable or private video.")
                    continue
                queues[ctx.guild.id].append((entry["title"], entry["url"]))
                print(f"Added to queue: {entry['title']}")      

            if len([e for e in playlist_data3['entries'][:] if e]) != 0:
                await ctx.send(f"Queued {len([e for e in playlist_data3['entries'][:] if e])} additional songs.")

            playlist_data4 = await loop.run_in_executor(None, lambda: opt4.extract_info(link, download=False))
            for entry in playlist_data4["entries"][:]:
                if entry is None:
                    print("Skipped an unavailable or private video.")
                    continue
                queues[ctx.guild.id].append((entry["title"], entry["url"]))
                print(f"Added to queue: {entry['title']}")

            if len([e for e in playlist_data4['entries'][:] if e]) != 0:
                await ctx.send(f"Queued {len([e for e in playlist_data4['entries'][:] if e])} additional songs.")

            playlist_data5 = await loop.run_in_executor(None, lambda: opt5.extract_info(link, download=False))
            for entry in playlist_data5["entries"][:]:
                if entry is None:
                    print("Skipped an unavailable or private video.")
                    continue
                queues[ctx.guild.id].append((entry["title"], entry["url"]))
                print(f"Added to queue: {entry['title']}")

                if len([e for e in playlist_data5['entries'][:] if e]) != 0:
                    await ctx.send(f"Queued {len([e for e in playlist_data5['entries'][:] if e])} additional songs.")
        except Exception as e:
                print(f"Error processing playlist")



    async def play_next(ctx):
        global last_activity
        last_activity[ctx.guild.id] = datetime.now()

        # If already playing, do nothing
        if ctx.guild.id in voice_clients and voice_clients[ctx.guild.id].is_playing():
            return

        # Reconnect if bot somehow got disconnected (network dropout safety)
        if ctx.guild.id not in voice_clients or not voice_clients[ctx.guild.id].is_connected():
            try:
                voice_channel = ctx.author.voice.channel
                voice_clients[ctx.guild.id] = await voice_channel.connect()
                print(f"Reconnected to voice channel in {ctx.guild.id}")
            except Exception as e:
                print(f"Failed to reconnect to voice: {e}")
                return  # If we can't even reconnect, no point continuing

        # Queue handling — check if there's anything to play
        if ctx.guild.id not in queues or not queues[ctx.guild.id]:
            if not playlist_processing_status.get(ctx.guild.id, False):
                # No playlist being processed, fully idle, start 5 minute disconnect timer
                await asyncio.sleep(300)  # 5 minutes (was 1500s before, which is 25 minutes — too long)
                if ctx.guild.id in voice_clients and voice_clients[ctx.guild.id].is_connected() and not voice_clients[ctx.guild.id].is_playing():
                    await voice_clients[ctx.guild.id].disconnect()
                    cleanup_guild_state(ctx.guild.id)
                return

            # Playlist processing is ongoing — wait for queue to fill
            while playlist_processing_status.get(ctx.guild.id, False) and not queues[ctx.guild.id]:
                await asyncio.sleep(1)

        # Finally play the next song (if the queue got filled)
        if queues[ctx.guild.id]:
            next_song_title, next_song_url = queues[ctx.guild.id].pop(0)

            try:
                print(f"Playing next song: {next_song_title}")

                # Fetch stream URL with retries
                stream_url = await retry_with_backoff(fetch_stream_url, next_song_url)

                player = discord.FFmpegOpusAudio(stream_url, **ffmpeg_options)

                voice_clients[ctx.guild.id].play(
                    player,
                    after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop).result()
                )

                await ctx.send(f"Now playing: {next_song_title}")

            except Exception as e:
                print(f"Error playing {next_song_title}: {e}")
                await ctx.send(f"Error playing {next_song_title}. Skipping...")
                await play_next(ctx)

        else:
            # No songs left — wait 5 minutes, then disconnect if still idle
            await asyncio.sleep(300)
            if ctx.guild.id in voice_clients and voice_clients[ctx.guild.id].is_connected() and not voice_clients[ctx.guild.id].is_playing():
                await voice_clients[ctx.guild.id].disconnect()
                cleanup_guild_state(ctx.guild.id)

    async def fetch_stream_url(url):
        """Fetch the direct audio stream URL using yt-dlp."""
        data = ytdl.extract_info(url, download=False)
        if "url" not in data:
            raise Exception(f"Failed to fetch stream URL for {url}")
        return data["url"]

    async def retry_with_backoff(func, *args, retries=5, initial_delay=2):
        """Retry function with exponential backoff."""
        delay = initial_delay
        for attempt in range(retries):
            try:
                return await func(*args)
            except Exception as e:
                print(f"Attempt {attempt+1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    raise


    @bot.command(name="queue")
    async def show_queue_cmd(ctx):
        queue = get_queue(ctx.guild.id)
        if queue:
            queue_preview = queue[:10]
            queue_list = "\n".join([f"{i+1}. {title}" for i, (title, _) in enumerate(queue_preview)])
            remaining_count = len(queue) - 10

            if remaining_count > 0:
                await ctx.send(f"Current queue (next 10 songs):\n{queue_list}\n...and {remaining_count} more songs in the queue.")
            else:
                await ctx.send(f"Current queue (next {len(queue)} songs):\n{queue_list}")
        else:
            await ctx.send("The queue is currently empty.")

    @bot.command(name="remove")
    async def remove(ctx, index: int):
        try:
            removed_song = remove_from_queue(ctx.guild.id, index - 1)
            if removed_song:
                await ctx.send(f"Removed from queue: {removed_song[0]}")
            else:
                await ctx.send(f"No song found at position {index}.")
        except Exception as e:
            print(f"Error removing from queue: {e}")
            await ctx.send("An error occurred while removing the song from the queue.")

    @bot.command(name="clear")
    async def clear(ctx):
        if clear_queue(ctx.guild.id):
            await ctx.send("Queue cleared!")
        else:
            await ctx.send("The queue is already empty.")

    @bot.command(name="pause")
    async def pause(ctx):
        global last_activity
        last_activity[ctx.guild.id] = datetime

        try:
            voice_clients[ctx.guild.id].pause()
        except Exception as e:
            print(e)

    @bot.command(name="resume")
    async def resume(ctx):
        global last_activity
        last_activity[ctx.guild.id] = datetime

        try:
            voice_clients[ctx.guild.id].resume()
        except Exception as e:
            print(e)

    @bot.command(name="skip")
    async def skip(ctx):
        global last_activity
        last_activity[ctx.guild.id] = datetime

        if ctx.guild.id in voice_clients and voice_clients[ctx.guild.id].is_playing():
            # Stop the current song
            voice_clients[ctx.guild.id].stop()
            await ctx.send("Skipping the current song...")
        else:
            await ctx.send("No song is currently playing to skip.")

    @bot.command(name="stop")
    async def stop(ctx):
        global last_activity
        last_activity[ctx.guild.id] = datetime

        try:
            voice_clients[ctx.guild.id].stop()
            await voice_clients[ctx.guild.id].disconnect()
            del voice_clients[ctx.guild.id]
        except Exception as e:
            print(e)

    @bot.event
    async def on_voice_state_update(member, before, after):
        # Check if the bot is in a voice channel and alone
        if member == bot.user and before.channel is not None and after.channel is None:
                guild_id = before.channel.guild.id
                if guild_id in voice_clients:
                    del voice_clients[guild_id]
                if guild_id in queues:
                    del queues[guild_id]
                print(f"Bot was manually disconnected from {before.channel}. Cleaned up guild {guild_id}.")
                return  # Exit to avoid running the rest of the code when manually disconnected

        for guild_id, voice_client in list(voice_clients.items()):
            if voice_client.channel and len(voice_client.channel.members) == 1:  # Bot is alone
                print(f"Bot is alone in the voice channel for guild {guild_id}. Waiting 5 minutes before disconnecting...")
                await asyncio.sleep(1500)  # Wait 5 minutes
                # Recheck if the bot is still alone after waiting
                if len(voice_client.channel.members) == 1:
                    print(f"Bot is still alone in the voice channel for guild {guild_id}. Disconnecting...")
                    await voice_client.disconnect()
                    del voice_clients[guild_id]
                    if guild_id in queues:
                        del queues[guild_id]  # Clear the queue when disconnecting

    @tasks.loop(minutes=5)
    async def check_voice_channels():
        for guild_id, voice_client in list(voice_clients.items()):
            if voice_client.channel and len(voice_client.channel.members) == 1:  # Bot is alone
                print(f"Bot is alone in the voice channel for guild {guild_id}. Waiting 5 minutes before disconnecting...")
                await asyncio.sleep(1500)  # Wait 5 minutes
                if len(voice_client.channel.members) == 1:
                    print(f"Bot is still alone in the voice channel for guild {guild_id}. Disconnecting...")
                    await voice_client.disconnect()
                    del voice_clients[guild_id]
                    if guild_id in queues:
                        del queues[guild_id]  # Clear the queue when disconnecting
def cleanup_guild_state(guild_id):
        """Clean up all data related to a guild after disconnect."""
        if guild_id in queues:
            del queues[guild_id]
        if guild_id in voice_clients:
            del voice_clients[guild_id]
        if guild_id in playlist_processing_status:
            del playlist_processing_status[guild_id]
        print(f"Cleaned up guild {guild_id} after disconnect.")
