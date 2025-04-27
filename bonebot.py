import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
from roles import setup_roles
from music import setup_music_commands

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

# Use setup_hook for asynchronous initialization
class MyBot(commands.Bot):
    async def setup_hook(self):
        # Initialize roles and music commands asynchronously
        await setup_roles(self)
        await setup_music_commands(self)
        await self.load_extension("fantasy_registration")
        await self.load_extension("draft_modal")
        await self.tree.sync()
# Create an instance of the custom bot
bot = MyBot(command_prefix="!", intents=intents)

# Run the bot
bot.run(TOKEN)
