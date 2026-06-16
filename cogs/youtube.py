"""
cogs/youtube.py
Slash group: /youtube
Advanced YouTube notification system.

Features:
  - Track multiple YouTube channels per Discord server
  - Sends a rich embed notification to a chosen Discord channel when a new
    video is uploaded
  - Per-subscription hashtag / keyword filters — a notification fires only
    if ANY of the configured filter words appear in the video title OR
    description (or if no filters are set, every video notifies)
  - Polls the public YouTube RSS feed every 5 minutes — no API key needed
  - Custom notification message per subscription
  - /youtube list   shows all tracked channels with their filters
  - Filter management: addfilter / removefilter / clearfilters

Data stored in youtube.json:
{
  "guild_id": {
    "yt_channel_id": {
      "yt_channel_id":   "UCxxxxxx",
      "yt_channel_name": "Channel Name",        # cached display name
      "discord_channel": 123456789,              # Discord channel ID
      "filters":         ["#shorts", "minecraft"],  # empty = notify all
      "custom_message":  "New video dropped!",   # optional ping/message
      "last_video_id":   "dQw4w9WgXcQ",          # tracks last seen video
    }
  }
}
"""

import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import Config
from utils.data import load, save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

YT_FILE        = "youtube.json"
POLL_INTERVAL  = 5          # minutes between feed checks
RSS_URL        = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
YT_WATCH_URL   = "https://www.youtube.com/watch?v={}"
YT_CHANNEL_URL = "https://www.youtube.com/channel/{}"

# Regex to pull channel ID from a YouTube channel URL
_CHANNEL_ID_RE = re.compile(
    r"(?:youtube\.com/(?:channel/|@))([\w-]+)"
)

# XML namespace used in YouTube's Atom feed
_NS = {
    "atom":   "http://www.w3.org/2005/Atom",
    "yt":     "http://www.youtube.com/xml/schemas/2015",
    "media":  "http://search.yahoo.com/mrss/",
}

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _load_guild(guild_id: int) -> dict:
    return load(YT_FILE).get(str(guild_id), {})


def _save_guild(guild_id: int, data: dict):
    full = load(YT_FILE)
    full[str(guild_id)] = data
    save(YT_FILE, full)


def _get_sub(guild_id: int, yt_channel_id: str) -> dict | None:
    return _load_guild(guild_id).get(yt_channel_id)


def _save_sub(guild_id: int, yt_channel_id: str, sub: dict):
    d = _load_guild(guild_id)
    d[yt_channel_id] = sub
    _save_guild(guild_id, d)


def _delete_sub(guild_id: int, yt_channel_id: str) -> bool:
    d = _load_guild(guild_id)
    if yt_channel_id in d:
        del d[yt_channel_id]
        _save_guild(guild_id, d)
        return True
    return False


# ---------------------------------------------------------------------------
# YouTube RSS helpers
# ---------------------------------------------------------------------------

async def _fetch_rss(session: aiohttp.ClientSession, yt_channel_id: str) -> str | None:
    url = RSS_URL.format(yt_channel_id)
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.text()
    except Exception:
        pass
    return None


def _parse_latest_video(xml_text: str) -> dict | None:
    """
    Parse the YouTube Atom feed and return the most recent video's metadata,
    or None if the feed is empty / unparseable.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    entries = root.findall("atom:entry", _NS)
    if not entries:
        return None

    entry = entries[0]  # first entry = most recent video

    def _text(el, path):
        node = el.find(path, _NS)
        return node.text.strip() if node is not None and node.text else ""

    video_id    = _text(entry, "yt:videoId")
    title       = _text(entry, "atom:title")
    published   = _text(entry, "atom:published")
    author_name = _text(root,  "atom:author/atom:name")
    channel_id  = _text(root,  "yt:channelId")

    # Description lives inside media:group > media:description
    media_group  = entry.find("media:group", _NS)
    description  = ""
    thumbnail    = ""
    if media_group is not None:
        desc_node = media_group.find("media:description", _NS)
        if desc_node is not None and desc_node.text:
            description = desc_node.text.strip()
        thumb_node = media_group.find("media:thumbnail", _NS)
        if thumb_node is not None:
            thumbnail = thumb_node.attrib.get("url", "")

    return {
        "video_id":    video_id,
        "title":       title,
        "description": description,
        "thumbnail":   thumbnail,
        "author":      author_name,
        "channel_id":  channel_id,
        "published":   published,
    }


def _channel_name_from_feed(xml_text: str) -> str:
    """Extract the channel display name from the feed."""
    try:
        root = ET.fromstring(xml_text)
        node = root.find("atom:author/atom:name", _NS)
        if node is not None and node.text:
            return node.text.strip()
    except Exception:
        pass
    return ""


def _passes_filters(video: dict, filters: list[str]) -> bool:
    """
    Return True if the video should trigger a notification.
    - If filters is empty → always notify.
    - Otherwise → at least one filter word/hashtag must appear (case-insensitive)
      in the video title OR description.
    """
    if not filters:
        return True
    haystack = (video["title"] + " " + video["description"]).lower()
    for f in filters:
        if f.lower() in haystack:
            return True
    return False


async def _scrape_channel_id(
    session: aiohttp.ClientSession, url: str
) -> str | None:
    """
    Fetch a YouTube channel page and scrape the UC channel ID from the HTML.
    Works for @handles, /c/ slugs, and /channel/ URLs.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with session.get(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=15), allow_redirects=True
        ) as resp:
            if resp.status != 200:
                return None
            html = await resp.text(errors="ignore")
    except Exception:
        return None

    patterns = [
        r'"channelId"\s*:\s*"(UC[\w-]{22})"',
        r'"externalChannelId"\s*:\s*"(UC[\w-]{22})"',
        r'"browseId"\s*:\s*"(UC[\w-]{22})"',
        r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"',
    ]
    for pattern in patterns:
        m = re.search(pattern, html)
        if m:
            return m.group(1)
    return None


async def _resolve_channel_id(
    session: aiohttp.ClientSession, query: str
) -> tuple[str | None, str | None]:
    """
    Accept any of the following and return (channel_id, display_name):
      - Bare UC channel ID:     UCX6OQ3DkcsbYNE6H8uQQuVA
      - Full channel URL:       https://youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA
      - Handle URL:             https://youtube.com/@MrBeast
      - Bare handle with @:     @MrBeast
      - Bare name without @:    MrBeast  (tried as @handle)
    Returns (None, None) on failure.
    """
    query = query.strip().rstrip("/")

    # 1. Already a raw UC ID
    if re.fullmatch(r"UC[\w-]{22}", query):
        xml = await _fetch_rss(session, query)
        if xml:
            return query, _channel_name_from_feed(xml)
        return None, None

    # 2. Full /channel/UC... URL
    m = re.search(r"youtube\.com/channel/(UC[\w-]{22})", query)
    if m:
        uc_id = m.group(1)
        xml = await _fetch_rss(session, uc_id)
        if xml:
            return uc_id, _channel_name_from_feed(xml)
        return None, None

    # 3. Handle / slug / full handle URL — scrape the page
    if "youtube.com" in query:
        page_url = query if query.startswith("http") else "https://" + query
    elif query.startswith("@"):
        page_url = f"https://www.youtube.com/{query}"
    else:
        page_url = f"https://www.youtube.com/@{query}"

    uc_id = await _scrape_channel_id(session, page_url)
    if not uc_id:
        return None, None

    xml = await _fetch_rss(session, uc_id)
    if xml:
        return uc_id, _channel_name_from_feed(xml)
    return uc_id, None


# ---------------------------------------------------------------------------
# Embed builder for notifications
# ---------------------------------------------------------------------------

def _build_notification_embed(video: dict, sub: dict) -> discord.Embed:
    e = discord.Embed(
        title=video["title"],
        url=YT_WATCH_URL.format(video["video_id"]),
        color=0xFF0000,  # YouTube red
    )
    e.set_author(
        name=video["author"],
        url=YT_CHANNEL_URL.format(video["channel_id"]),
        icon_url="https://www.youtube.com/favicon.ico",
    )
    if video["thumbnail"]:
        e.set_image(url=video["thumbnail"])

    desc = video["description"]
    if desc:
        e.description = desc[:300] + ("…" if len(desc) > 300 else "")

    if video["published"]:
        try:
            dt = datetime.fromisoformat(video["published"].replace("Z", "+00:00"))
            e.timestamp = dt
        except ValueError:
            pass

    active_filters = sub.get("filters", [])
    if active_filters:
        e.set_footer(text="Matched filters: " + ", ".join(active_filters))
    else:
        e.set_footer(text="YouTube Notifications")

    return e


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class YouTubeCog(commands.Cog, name="YouTube"):
    """🎬 YouTube upload notifications with hashtag/keyword filtering."""

    slash = app_commands.Group(name="youtube", description="YouTube notification commands")

    def __init__(self, bot: commands.Bot):
        self.bot     = bot
        self.session: aiohttp.ClientSession | None = None
        self._poll_feeds.start()

    def cog_unload(self):
        self._poll_feeds.cancel()
        if self.session and not self.session.closed:
            asyncio.create_task(self.session.close())

    # ── Internal poll loop ────────────────────────────────────────────────

    @tasks.loop(minutes=POLL_INTERVAL)
    async def _poll_feeds(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

        all_data = load(YT_FILE)
        for guild_id_str, subs in all_data.items():
            guild_id = int(guild_id_str)
            guild    = self.bot.get_guild(guild_id)
            if not guild:
                continue

            for yt_channel_id, sub in subs.items():
                xml = await _fetch_rss(self.session, yt_channel_id)
                if not xml:
                    continue

                video = _parse_latest_video(xml)
                if not video or not video["video_id"]:
                    continue

                # Skip if we've already seen this video
                if video["video_id"] == sub.get("last_video_id"):
                    continue

                # Update last seen video ID immediately to prevent double-posting
                sub["last_video_id"] = video["video_id"]
                _save_sub(guild_id, yt_channel_id, sub)

                # Apply filters
                if not _passes_filters(video, sub.get("filters", [])):
                    continue

                # Send notification
                discord_channel = guild.get_channel(sub["discord_channel"])
                if not discord_channel:
                    continue

                try:
                    embed       = _build_notification_embed(video, sub)
                    custom_msg  = sub.get("custom_message") or ""
                    video_url   = YT_WATCH_URL.format(video["video_id"])
                    # Send the plain URL so Discord auto-generates the video preview,
                    # then append the custom message (e.g. @everyone) on a new line
                    content = f"{video_url}"
                    if custom_msg:
                        content = f"{custom_msg}\n{video_url}"
                    await discord_channel.send(content=content, embed=embed)
                except (discord.Forbidden, discord.HTTPException):
                    pass

                # Slight delay between guilds to avoid rate limits
                await asyncio.sleep(0.5)

    @_poll_feeds.before_loop
    async def _before_poll(self):
        await self.bot.wait_until_ready()

    # ── /youtube add ──────────────────────────────────────────────────────

    @slash.command(name="add", description="Track a YouTube channel and post new video notifications.")
    @app_commands.describe(
        channel_id="YouTube channel ID, @handle, or full channel URL",
        discord_channel="Discord channel to send notifications to",
        custom_message="Optional message sent above each notification (e.g. @everyone)",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def yt_add(
        self,
        interaction: discord.Interaction,
        channel_id: str,
        discord_channel: discord.TextChannel,
        custom_message: str = None,
    ):
        await interaction.response.defer(ephemeral=True)

        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

        yt_id, display_name = await _resolve_channel_id(self.session, channel_id)
        if not yt_id:
            await interaction.followup.send(
                "❌ Could not find that YouTube channel.\n"
                "You can enter any of these:\n"
                "• `@MrBeast` — bare handle\n"
                "• `https://youtube.com/@MrBeast` — full URL\n"
                "• `UCX6OQ3DkcsbYNE6H8uQQuVA` — raw channel ID\n\n"
                "If it still fails, paste the full channel URL from your browser.",
                ephemeral=True,
            )
            return

        if _get_sub(interaction.guild_id, yt_id):
            await interaction.followup.send(
                f"❌ Already tracking **{display_name or yt_id}**.", ephemeral=True
            )
            return

        # Grab the current latest video ID so we don't notify for old videos
        xml = await _fetch_rss(self.session, yt_id)
        last_video_id = ""
        if xml:
            v = _parse_latest_video(xml)
            if v:
                last_video_id = v["video_id"]

        sub = {
            "yt_channel_id":   yt_id,
            "yt_channel_name": display_name or yt_id,
            "discord_channel": discord_channel.id,
            "filters":         [],
            "custom_message":  custom_message or "",
            "last_video_id":   last_video_id,
        }
        _save_sub(interaction.guild_id, yt_id, sub)

        e = discord.Embed(
            title="✅ Now tracking YouTube channel",
            color=0xFF0000,
        )
        e.add_field(name="Channel",          value=f"[{display_name or yt_id}]({YT_CHANNEL_URL.format(yt_id)})", inline=True)
        e.add_field(name="Notifications →",  value=discord_channel.mention, inline=True)
        e.add_field(name="Filters",          value="None (all videos)", inline=True)
        if custom_message:
            e.add_field(name="Custom Message", value=custom_message, inline=False)
        e.set_footer(text="Use /youtube addfilter to filter by hashtag or keyword")
        await interaction.followup.send(embed=e, ephemeral=True)

    # ── /youtube remove ───────────────────────────────────────────────────

    @slash.command(name="remove", description="Stop tracking a YouTube channel.")
    @app_commands.describe(channel_id="YouTube channel ID to remove")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def yt_remove(self, interaction: discord.Interaction, channel_id: str):
        sub = _get_sub(interaction.guild_id, channel_id)
        if not sub:
            # Try matching by name (case-insensitive)
            subs = _load_guild(interaction.guild_id)
            for yt_id, s in subs.items():
                if s.get("yt_channel_name", "").lower() == channel_id.lower():
                    sub = s
                    channel_id = yt_id
                    break
        if not sub:
            await interaction.response.send_message(
                f"❌ No subscription found for `{channel_id}`.", ephemeral=True
            )
            return
        name = sub.get("yt_channel_name", channel_id)
        _delete_sub(interaction.guild_id, channel_id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Removed",
                description=f"No longer tracking **{name}**.",
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

    # ── /youtube list ─────────────────────────────────────────────────────

    @slash.command(name="list", description="List all tracked YouTube channels for this server.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def yt_list(self, interaction: discord.Interaction):
        subs = _load_guild(interaction.guild_id)
        if not subs:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="No YouTube channels tracked yet. Use `/youtube add` to start.",
                    color=Config.COLOR_INFO,
                ),
                ephemeral=True,
            )
            return

        e = discord.Embed(
            title=f"YouTube Subscriptions ({len(subs)})",
            color=0xFF0000,
        )
        for yt_id, sub in subs.items():
            ch    = interaction.guild.get_channel(sub["discord_channel"])
            ch_str = ch.mention if ch else f"<deleted channel {sub['discord_channel']}>"
            filters = sub.get("filters", [])
            filter_str = ", ".join(f"`{f}`" for f in filters) if filters else "All videos"
            e.add_field(
                name=sub.get("yt_channel_name", yt_id),
                value=f"→ {ch_str}\nFilters: {filter_str}",
                inline=False,
            )
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── /youtube addfilter ────────────────────────────────────────────────

    @slash.command(name="addfilter", description="Add a keyword or hashtag filter to a YouTube subscription.")
    @app_commands.describe(
        channel_id="YouTube channel ID",
        filter_word="Keyword or hashtag (e.g. #shorts or minecraft). Case-insensitive.",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def yt_addfilter(
        self,
        interaction: discord.Interaction,
        channel_id: str,
        filter_word: str,
    ):
        sub = _get_sub(interaction.guild_id, channel_id)
        if not sub:
            await interaction.response.send_message(
                f"❌ No subscription found for `{channel_id}`.", ephemeral=True
            )
            return

        filter_word = filter_word.strip().lower()
        if filter_word in [f.lower() for f in sub.get("filters", [])]:
            await interaction.response.send_message(
                f"❌ Filter `{filter_word}` already exists for this channel.", ephemeral=True
            )
            return
        if len(sub.get("filters", [])) >= 25:
            await interaction.response.send_message(
                "❌ Maximum 25 filters per subscription.", ephemeral=True
            )
            return

        sub.setdefault("filters", []).append(filter_word)
        _save_sub(interaction.guild_id, channel_id, sub)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Filter added",
                description=(
                    f"Added `{filter_word}` to **{sub.get('yt_channel_name', channel_id)}**.\n"
                    f"Notifications will only fire when the title or description contains this word."
                ),
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

    # ── /youtube removefilter ─────────────────────────────────────────────

    @slash.command(name="removefilter", description="Remove a keyword/hashtag filter from a subscription.")
    @app_commands.describe(
        channel_id="YouTube channel ID",
        filter_word="Filter to remove",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def yt_removefilter(
        self,
        interaction: discord.Interaction,
        channel_id: str,
        filter_word: str,
    ):
        sub = _get_sub(interaction.guild_id, channel_id)
        if not sub:
            await interaction.response.send_message(
                f"❌ No subscription found for `{channel_id}`.", ephemeral=True
            )
            return

        filter_word = filter_word.strip().lower()
        filters     = [f.lower() for f in sub.get("filters", [])]
        if filter_word not in filters:
            await interaction.response.send_message(
                f"❌ Filter `{filter_word}` not found.", ephemeral=True
            )
            return

        sub["filters"] = [f for f in sub["filters"] if f.lower() != filter_word]
        _save_sub(interaction.guild_id, channel_id, sub)
        remaining = sub["filters"]
        note = "All videos will now trigger notifications." if not remaining else f"Remaining: {', '.join(f'`{f}`' for f in remaining)}"
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Filter removed",
                description=f"Removed `{filter_word}` from **{sub.get('yt_channel_name', channel_id)}**.\n{note}",
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

    # ── /youtube clearfilters ─────────────────────────────────────────────

    @slash.command(name="clearfilters", description="Remove all filters from a subscription (notify for every video).")
    @app_commands.describe(channel_id="YouTube channel ID")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def yt_clearfilters(self, interaction: discord.Interaction, channel_id: str):
        sub = _get_sub(interaction.guild_id, channel_id)
        if not sub:
            await interaction.response.send_message(
                f"❌ No subscription found for `{channel_id}`.", ephemeral=True
            )
            return
        sub["filters"] = []
        _save_sub(interaction.guild_id, channel_id, sub)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Filters cleared",
                description=f"All filters removed from **{sub.get('yt_channel_name', channel_id)}**. Every new video will now notify.",
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

    # ── /youtube filters ──────────────────────────────────────────────────

    @slash.command(name="filters", description="Show all active filters for a tracked YouTube channel.")
    @app_commands.describe(channel_id="YouTube channel ID")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def yt_filters(self, interaction: discord.Interaction, channel_id: str):
        sub = _get_sub(interaction.guild_id, channel_id)
        if not sub:
            await interaction.response.send_message(
                f"❌ No subscription found for `{channel_id}`.", ephemeral=True
            )
            return
        filters = sub.get("filters", [])
        e = discord.Embed(
            title=f"Filters — {sub.get('yt_channel_name', channel_id)}",
            color=0xFF0000,
        )
        if filters:
            e.description = "\n".join(f"• `{f}`" for f in filters)
            e.set_footer(text="A video must match at least one filter to trigger a notification.")
        else:
            e.description = "No filters set — every new video triggers a notification."
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── /youtube setmessage ───────────────────────────────────────────────

    @slash.command(name="setmessage", description="Set a custom message posted above each notification (e.g. @everyone).")
    @app_commands.describe(
        channel_id="YouTube channel ID",
        message="Message text (leave blank to clear)",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def yt_setmessage(
        self,
        interaction: discord.Interaction,
        channel_id: str,
        message: str = "",
    ):
        sub = _get_sub(interaction.guild_id, channel_id)
        if not sub:
            await interaction.response.send_message(
                f"❌ No subscription found for `{channel_id}`.", ephemeral=True
            )
            return
        sub["custom_message"] = message.strip()
        _save_sub(interaction.guild_id, channel_id, sub)
        if message.strip():
            desc = f"Custom message set to: `{message.strip()}`"
        else:
            desc = "Custom message cleared."
        await interaction.response.send_message(
            embed=discord.Embed(title="✅ Updated", description=desc, color=Config.COLOR_OK),
            ephemeral=True,
        )

    # ── /youtube setchannel ───────────────────────────────────────────────

    @slash.command(name="setchannel", description="Change the Discord channel where notifications are sent.")
    @app_commands.describe(
        channel_id="YouTube channel ID",
        discord_channel="New Discord channel",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def yt_setchannel(
        self,
        interaction: discord.Interaction,
        channel_id: str,
        discord_channel: discord.TextChannel,
    ):
        sub = _get_sub(interaction.guild_id, channel_id)
        if not sub:
            await interaction.response.send_message(
                f"❌ No subscription found for `{channel_id}`.", ephemeral=True
            )
            return
        sub["discord_channel"] = discord_channel.id
        _save_sub(interaction.guild_id, channel_id, sub)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Updated",
                description=f"Notifications for **{sub.get('yt_channel_name', channel_id)}** will now go to {discord_channel.mention}.",
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def setup(bot: commands.Bot):
    await bot.add_cog(YouTubeCog(bot))
