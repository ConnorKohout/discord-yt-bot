import pytest
import music

def test_get_queue_initializes_empty():
    guild_id = 12345
    if guild_id in music.queues:
        del music.queues[guild_id]
    queue = music.get_queue(guild_id)
    assert queue == []
    assert guild_id in music.queues

def test_add_to_queue_adds_song():
    guild_id = 12345
    music.queues[guild_id] = []
    title = "Test Song"
    url = "http://example.com"
    music.add_to_queue(guild_id, title, url)
    assert len(music.queues[guild_id]) == 1
    assert music.queues[guild_id][0] == (title, url)

def test_clear_queue_clears_songs():
    guild_id = 12345
    music.queues[guild_id] = [("Song 1", "url1"), ("Song 2", "url2")]
    result = music.clear_queue(guild_id)
    assert result is True
    assert music.queues[guild_id] == []

def test_remove_from_queue_valid_index():
    guild_id = 12345
    music.queues[guild_id] = [("Song 1", "url1"), ("Song 2", "url2")]
    removed_song = music.remove_from_queue(guild_id, 0)
    assert removed_song == ("Song 1", "url1")
    assert len(music.queues[guild_id]) == 1
    assert music.queues[guild_id][0] == ("Song 2", "url2")

def test_remove_from_queue_invalid_index():
    guild_id = 12345
    music.queues[guild_id] = [("Song 1", "url1")]
    removed_song = music.remove_from_queue(guild_id, 5)
    assert removed_song is None

def test_show_queue_returns_current_queue():
    guild_id = 12345
    queue_contents = [("Song A", "urlA"), ("Song B", "urlB")]
    music.queues[guild_id] = queue_contents
    queue = music.show_queue(guild_id)
    assert queue == queue_contents

def test_cleanup_guild_state_removes_guild_data():
    guild_id = 12345
    music.queues[guild_id] = [("Song", "url")]
    music.voice_clients[guild_id] = "DummyVoiceClient"
    music.playlist_processing_status[guild_id] = True
    music.cleanup_guild_state(guild_id)
    assert guild_id not in music.queues
    assert guild_id not in music.voice_clients
    assert guild_id not in music.playlist_processing_status
