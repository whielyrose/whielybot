"""
WhielyBot - Custom Fluxer bot for the WhielyServer community.

Commands:
    !ping                     - Sanity check
    !weather <location>       - Weather forecast
    !poll "question" | opt1 | opt2 | opt3
                              - Create a reaction poll
    !stats                    - Server stats
    !kick @user [reason]      - Kick a member (moderator only)
    !ban @user [reason]       - Ban a member (moderator only)
    !purge <count>            - Delete recent messages (moderator only)
    !help                     - Show this help

The bot also exposes an HTTP webhook at /notify that posts messages to a
configured Fluxer channel. This is used by Jellyfin/Sonarr/Radarr for
new-content notifications.
"""

import asyncio
import os
import re
import sys
from typing import Optional

import fluxer
from aiohttp import web, ClientSession

# ─── Config from environment ────────────────────────────────────────────────
BOT_TOKEN = os.environ["FLUXER_BOT_TOKEN"]
OPENWEATHER_API_KEY = os.environ["OPENWEATHER_API_KEY"]
NOTIFY_CHANNEL_ID = os.environ.get("NOTIFY_CHANNEL_ID", "")  # set later once you have a channel for notifs
COMMAND_PREFIX = "!"

# ─── Fluxer client setup ────────────────────────────────────────────────────
intents = fluxer.Intents.default()
intents.message_content = True
intents.members = True

bot = fluxer.Bot(command_prefix=COMMAND_PREFIX, intents=intents)


# ─── Helpers ────────────────────────────────────────────────────────────────
async def fetch_weather(location: str) -> Optional[dict]:
    """Fetch current weather from OpenWeatherMap."""
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": location,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",  # Celsius, m/s
    }
    async with ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                return None
            return await resp.json()


def is_moderator(member) -> bool:
    """Check if the member has permission to run moderation commands.
    Right now: anyone with 'kick' or 'ban' permission on the server."""
    try:
        perms = member.guild_permissions
        return perms.kick_members or perms.ban_members or perms.administrator
    except AttributeError:
        return False


# ─── Commands ───────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ WhielyBot logged in as {bot.user.username}")
    print(f"   User ID: {bot.user.id}")
    print(f"   In {len(bot.guilds)} servers")
    sys.stdout.flush()


@bot.command(name="ping")
async def ping(ctx):
    """Sanity check."""
    await ctx.send("🏓 Pong!")


@bot.command(name="weather")
async def weather(ctx, *, location: str = ""):
    """Get weather for a location."""
    if not location:
        await ctx.send("Usage: `!weather <location>` — e.g. `!weather Brisbane`")
        return

    data = await fetch_weather(location)
    if not data:
        await ctx.send(f"❌ Couldn't find weather for `{location}`.")
        return

    name = data.get("name", location)
    country = data.get("sys", {}).get("country", "")
    temp = data["main"]["temp"]
    feels = data["main"]["feels_like"]
    humidity = data["main"]["humidity"]
    desc = data["weather"][0]["description"].capitalize()
    wind = data["wind"]["speed"]

    msg = (
        f"**Weather in {name}, {country}**\n"
        f"🌡️ {temp:.1f}°C (feels like {feels:.1f}°C)\n"
        f"☁️ {desc}\n"
        f"💧 Humidity: {humidity}%\n"
        f"💨 Wind: {wind} m/s"
    )
    await ctx.send(msg)


@bot.command(name="poll")
async def poll(ctx, *, args: str = ""):
    """Create a reaction poll.
    Usage: !poll question | option1 | option2 [| option3 ...]
    """
    if not args or "|" not in args:
        await ctx.send(
            "Usage: `!poll question | option1 | option2 [| option3 ...]`\n"
            "Example: `!poll What should we watch? | Movie | Show | Documentary`"
        )
        return

    parts = [p.strip() for p in args.split("|")]
    question, options = parts[0], parts[1:]

    if len(options) < 2:
        await ctx.send("A poll needs at least 2 options.")
        return
    if len(options) > 10:
        await ctx.send("A poll can have at most 10 options.")
        return

    number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    body = f"**📊 {question}**\n\n"
    for i, option in enumerate(options):
        body += f"{number_emojis[i]}  {option}\n"

    msg = await ctx.send(body)
    for i in range(len(options)):
        await msg.add_reaction(number_emojis[i])


@bot.command(name="stats")
async def stats(ctx):
    """Show server stats."""
    guild = ctx.guild
    if not guild:
        await ctx.send("This command must be run in a server.")
        return

    total_members = guild.member_count
    text_channels = len([c for c in guild.channels if c.type == fluxer.ChannelType.text])
    voice_channels = len([c for c in guild.channels if c.type == fluxer.ChannelType.voice])
    roles = len(guild.roles)

    msg = (
        f"**📈 {guild.name} stats**\n"
        f"👥 Members: {total_members}\n"
        f"💬 Text channels: {text_channels}\n"
        f"🔊 Voice channels: {voice_channels}\n"
        f"🎭 Roles: {roles}\n"
    )
    await ctx.send(msg)


@bot.command(name="kick")
async def kick(ctx, member: fluxer.Member, *, reason: str = "No reason provided"):
    """Kick a member. Moderators only."""
    if not is_moderator(ctx.author):
        await ctx.send("❌ You need kick permissions.")
        return
    try:
        await member.kick(reason=reason)
        await ctx.send(f"👢 Kicked **{member.name}** — {reason}")
    except Exception as e:
        await ctx.send(f"❌ Failed to kick: {e}")


@bot.command(name="ban")
async def ban(ctx, member: fluxer.Member, *, reason: str = "No reason provided"):
    """Ban a member. Moderators only."""
    if not is_moderator(ctx.author):
        await ctx.send("❌ You need ban permissions.")
        return
    try:
        await member.ban(reason=reason)
        await ctx.send(f"🔨 Banned **{member.name}** — {reason}")
    except Exception as e:
        await ctx.send(f"❌ Failed to ban: {e}")


@bot.command(name="purge")
async def purge(ctx, count: int = 0):
    """Delete recent messages. Moderators only."""
    if not is_moderator(ctx.author):
        await ctx.send("❌ You need manage_messages permission.")
        return
    if count < 1 or count > 100:
        await ctx.send("Count must be between 1 and 100.")
        return
    try:
        deleted = await ctx.channel.purge(limit=count + 1)  # +1 for the command message
        msg = await ctx.send(f"🧹 Deleted {len(deleted) - 1} messages.")
        await asyncio.sleep(3)
        await msg.delete()
    except Exception as e:
        await ctx.send(f"❌ Failed to purge: {e}")


@bot.command(name="help")
async def help_cmd(ctx):
    """Show help."""
    msg = (
        "**WhielyBot Commands**\n\n"
        "`!ping` — sanity check\n"
        "`!weather <location>` — weather forecast\n"
        "`!poll question | opt1 | opt2 [| opt3 ...]` — create a reaction poll\n"
        "`!stats` — server stats\n"
        "`!kick @user [reason]` — kick a member (mod)\n"
        "`!ban @user [reason]` — ban a member (mod)\n"
        "`!purge <count>` — delete recent messages (mod)\n"
        "`!help` — this message\n"
    )
    await ctx.send(msg)


# ─── HTTP webhook for Jellyfin/Sonarr/Radarr notifications ────────────────
async def webhook_handler(request):
    """Receive a webhook POST and forward as a message to NOTIFY_CHANNEL_ID.

    Expected JSON body:
        { "content": "message to post" }
    """
    if not NOTIFY_CHANNEL_ID:
        return web.json_response({"error": "NOTIFY_CHANNEL_ID not set"}, status=500)

    try:
        data = await request.json()
        content = data.get("content", "")
        if not content:
            return web.json_response({"error": "content required"}, status=400)

        channel = bot.get_channel(int(NOTIFY_CHANNEL_ID))
        if not channel:
            channel = await bot.fetch_channel(int(NOTIFY_CHANNEL_ID))

        await channel.send(content)
        return web.json_response({"status": "posted"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def start_webhook_server():
    """Run the aiohttp webhook server alongside the bot."""
    app = web.Application()
    app.router.add_post("/notify", webhook_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 9997)
    await site.start()
    print("✅ Webhook server listening on 0.0.0.0:9997/notify")
    sys.stdout.flush()


# ─── Main ───────────────────────────────────────────────────────────────────
async def main():
    async with bot:
        await start_webhook_server()
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
