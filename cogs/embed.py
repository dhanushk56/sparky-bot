"""
cogs/embed.py
Slash group: /embed
Full-featured embed builder (inspired by Discohook) + scheduled DM-all.
"""

import asyncio
import re
import json
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone, timedelta
from config import Config
from utils.data import load, save

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")

def parse_color(value: str | None) -> int:
    """Parse a hex color string to an integer. Falls back to Config.COLOR_INFO."""
    if not value:
        return Config.COLOR_INFO
    m = HEX_RE.match(value.strip())
    if m:
        return int(m.group(1), 16)
    return Config.COLOR_INFO


def _scheduled_dm_key(guild_id: int) -> str:
    return f"scheduled_dm_{guild_id}"


# ─────────────────────────────────────────────────────────────────────────────
# Modals
# ─────────────────────────────────────────────────────────────────────────────

class EmbedBuilderModal(discord.ui.Modal, title="📝 Embed Builder"):
    embed_title = discord.ui.TextInput(
        label="Title",
        placeholder="Your embed title…",
        required=False,
        max_length=256,
    )
    embed_description = discord.ui.TextInput(
        label="Description",
        placeholder="Main body text. Markdown supported.",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=4000,
    )
    embed_color = discord.ui.TextInput(
        label="Color (hex, e.g. #5865F2)",
        placeholder="#5865F2",
        required=False,
        max_length=7,
    )
    embed_footer = discord.ui.TextInput(
        label="Footer text",
        required=False,
        max_length=2048,
    )
    embed_image_url = discord.ui.TextInput(
        label="Image URL (optional)",
        placeholder="https://example.com/image.png",
        required=False,
        max_length=512,
    )

    def __init__(self, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        e = discord.Embed(color=parse_color(self.embed_color.value or None))
        if self.embed_title.value:
            e.title = self.embed_title.value
        if self.embed_description.value:
            e.description = self.embed_description.value
        if self.embed_footer.value:
            e.set_footer(text=self.embed_footer.value)
        if self.embed_image_url.value:
            e.set_image(url=self.embed_image_url.value)
        e.timestamp = discord.utils.utcnow()
        await self.channel.send(embed=e)
        await interaction.response.send_message(
            f"✅ Embed sent to {self.channel.mention}.", ephemeral=True
        )


class EmbedEditModal(discord.ui.Modal, title="✏️ Edit Embed"):
    embed_title = discord.ui.TextInput(
        label="New Title (leave blank to keep)",
        required=False,
        max_length=256,
    )
    embed_description = discord.ui.TextInput(
        label="New Description (leave blank to keep)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=4000,
    )
    embed_color = discord.ui.TextInput(
        label="New Color hex (leave blank to keep)",
        required=False,
        max_length=7,
    )
    embed_footer = discord.ui.TextInput(
        label="New Footer (leave blank to keep)",
        required=False,
        max_length=2048,
    )

    def __init__(self, message: discord.Message):
        super().__init__()
        self.target_message = message

    async def on_submit(self, interaction: discord.Interaction):
        if not self.target_message.embeds:
            await interaction.response.send_message("❌ That message has no embeds.", ephemeral=True)
            return
        old = self.target_message.embeds[0]
        e = old.copy()
        if self.embed_title.value:
            e.title = self.embed_title.value
        if self.embed_description.value:
            e.description = self.embed_description.value
        if self.embed_color.value:
            e.colour = parse_color(self.embed_color.value)
        if self.embed_footer.value:
            e.set_footer(text=self.embed_footer.value)
        await self.target_message.edit(embed=e)
        await interaction.response.send_message("✅ Embed updated.", ephemeral=True)


class DmAllModal(discord.ui.Modal, title="📨 Schedule DM-All"):
    dm_message = discord.ui.TextInput(
        label="DM Message",
        placeholder="Enter the message every member will receive…",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000,
    )
    send_at = discord.ui.TextInput(
        label="Send at (YYYY-MM-DD HH:MM UTC)",
        placeholder="2026-05-31 09:00",
        required=True,
        max_length=20,
    )
    embed_title = discord.ui.TextInput(
        label="Embed Title (optional)",
        required=False,
        max_length=256,
    )
    embed_color = discord.ui.TextInput(
        label="Embed Color hex (optional, e.g. #5865F2)",
        required=False,
        max_length=7,
    )

    def __init__(self, guild: discord.Guild, cog):
        super().__init__()
        self.guild = guild
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.send_at.value.strip()
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid date format. Use `YYYY-MM-DD HH:MM` (UTC).", ephemeral=True
            )
            return

        now = datetime.now(timezone.utc)
        if dt <= now:
            await interaction.response.send_message(
                "❌ Scheduled time must be in the future.", ephemeral=True
            )
            return

        key = _scheduled_dm_key(self.guild.id)
        data = load(str(self.guild.id))
        data[key] = {
            "message":      self.dm_message.value,
            "send_at":      dt.isoformat(),
            "embed_title":  self.embed_title.value or None,
            "embed_color":  self.embed_color.value or None,
            "scheduled_by": interaction.user.id,
        }
        save(str(self.guild.id), data)
        self.cog._reload_pending()

        delay_seconds = (dt - now).total_seconds()
        hours, rem = divmod(int(delay_seconds), 3600)
        minutes = rem // 60

        await interaction.response.send_message(
            f"✅ DM scheduled for **{dt.strftime('%Y-%m-%d %H:%M UTC')}**\n"
            f"⏳ That's in **{hours}h {minutes}m**.\n"
            f"Every member of this server will receive the message at that time.",
            ephemeral=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class EmbedCog(commands.Cog, name="Embed"):
    """📨 Embed builder, editor, and scheduled DM-all — inspired by Discohook."""

    slash = app_commands.Group(name="embed", description="Embed creation and DM tools")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._pending: dict[int, dict] = {}
        self._check_scheduled_dms.start()

    def cog_unload(self):
        self._check_scheduled_dms.cancel()

    # ── Internal helpers ──────────────────────────────

    def _reload_pending(self):
        """Refresh in-memory pending DMs from all guilds the bot knows about."""
        self._pending.clear()
        for guild in self.bot.guilds:
            data = load(str(guild.id))
            key = _scheduled_dm_key(guild.id)
            if key in data and data[key]:
                self._pending[guild.id] = data[key]

    @tasks.loop(seconds=30)
    async def _check_scheduled_dms(self):
        now = datetime.now(timezone.utc)
        fired = []
        for guild_id, entry in list(self._pending.items()):
            try:
                send_at = datetime.fromisoformat(entry["send_at"])
            except (KeyError, ValueError):
                fired.append(guild_id)
                continue
            if now >= send_at:
                fired.append(guild_id)
                asyncio.create_task(self._fire_dm_all(guild_id, entry))

        for gid in fired:
            self._pending.pop(gid, None)
            data = load(str(gid))
            key = _scheduled_dm_key(gid)
            data.pop(key, None)
            save(str(gid), data)

    @_check_scheduled_dms.before_loop
    async def _before_check(self):
        await self.bot.wait_until_ready()
        self._reload_pending()

    async def _fire_dm_all(self, guild_id: int, entry: dict):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        msg_text  = entry.get("message", "")
        title     = entry.get("embed_title")
        color     = parse_color(entry.get("embed_color"))
        use_embed = bool(title or entry.get("embed_color"))

        success = fail = 0
        await guild.chunk()
        for member in guild.members:
            if member.bot:
                continue
            try:
                if use_embed:
                    e = discord.Embed(
                        title=title,
                        description=msg_text,
                        color=color,
                        timestamp=discord.utils.utcnow(),
                    )
                    e.set_footer(text=f"From {guild.name}")
                    await member.send(embed=e)
                else:
                    await member.send(msg_text)
                success += 1
            except (discord.Forbidden, discord.HTTPException):
                fail += 1
            await asyncio.sleep(0.5)

        scheduled_by_id = entry.get("scheduled_by")
        if scheduled_by_id:
            try:
                user = await self.bot.fetch_user(scheduled_by_id)
                await user.send(
                    f"✅ Scheduled DM-all for **{guild.name}** completed.\n"
                    f"📨 Delivered to **{success}** members. Failed: **{fail}**."
                )
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────
    # /embed send
    # ─────────────────────────────────────────────────────────────────────

    @slash.command(name="send", description="Open the embed builder and send a rich embed to a channel.")
    @app_commands.describe(channel="Channel to send the embed to (defaults to current)")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed_send(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        await interaction.response.send_modal(EmbedBuilderModal(ch))

    # ─────────────────────────────────────────────────────────────────────
    # /embed quick
    # ─────────────────────────────────────────────────────────────────────

    @slash.command(name="quick", description="Send a quick embed with title and description inline.")
    @app_commands.describe(
        title="Embed title",
        description="Embed body text",
        color="Hex color, e.g. #5865F2 (optional)",
        channel="Target channel (defaults to current)",
        footer="Footer text (optional)",
        image="Image URL (optional)",
        thumbnail="Thumbnail URL (optional)",
        timestamp="Attach current timestamp? (default: yes)",
    )
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed_quick(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        color: str = None,
        channel: discord.TextChannel = None,
        footer: str = None,
        image: str = None,
        thumbnail: str = None,
        timestamp: bool = True,
    ):
        ch = channel or interaction.channel
        e = discord.Embed(
            title=title,
            description=description,
            color=parse_color(color),
        )
        if footer:
            e.set_footer(text=footer)
        if image:
            e.set_image(url=image)
        if thumbnail:
            e.set_thumbnail(url=thumbnail)
        if timestamp:
            e.timestamp = discord.utils.utcnow()
        await ch.send(embed=e)
        await interaction.response.send_message(f"✅ Embed sent to {ch.mention}.", ephemeral=True)

    # ─────────────────────────────────────────────────────────────────────
    # /embed edit
    # ─────────────────────────────────────────────────────────────────────

    @slash.command(name="edit", description="Edit an existing embed sent by the bot.")
    @app_commands.describe(
        message_id="ID of the message containing the embed",
        channel="Channel where the message is (defaults to current)",
    )
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed_edit(
        self,
        interaction: discord.Interaction,
        message_id: str,
        channel: discord.TextChannel = None,
    ):
        ch = channel or interaction.channel
        try:
            msg = await ch.fetch_message(int(message_id))
        except (discord.NotFound, ValueError):
            await interaction.response.send_message("❌ Message not found.", ephemeral=True)
            return
        if msg.author != self.bot.user:
            await interaction.response.send_message(
                "❌ I can only edit my own messages.", ephemeral=True
            )
            return
        await interaction.response.send_modal(EmbedEditModal(msg))

    # ─────────────────────────────────────────────────────────────────────
    # /embed addfield
    # ─────────────────────────────────────────────────────────────────────

    @slash.command(name="addfield", description="Add a field to an existing embed sent by the bot.")
    @app_commands.describe(
        message_id="ID of the message containing the embed",
        name="Field name",
        value="Field value",
        inline="Show fields side by side? (default: False)",
        channel="Channel where the message is",
    )
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed_addfield(
        self,
        interaction: discord.Interaction,
        message_id: str,
        name: str,
        value: str,
        inline: bool = False,
        channel: discord.TextChannel = None,
    ):
        ch = channel or interaction.channel
        try:
            msg = await ch.fetch_message(int(message_id))
        except (discord.NotFound, ValueError):
            await interaction.response.send_message("❌ Message not found.", ephemeral=True)
            return
        if msg.author != self.bot.user:
            await interaction.response.send_message("❌ I can only edit my own messages.", ephemeral=True)
            return
        if not msg.embeds:
            await interaction.response.send_message("❌ That message has no embeds.", ephemeral=True)
            return
        e = msg.embeds[0].copy()
        if len(e.fields) >= 25:
            await interaction.response.send_message("❌ Embeds can have at most 25 fields.", ephemeral=True)
            return
        e.add_field(name=name, value=value, inline=inline)
        await msg.edit(embed=e)
        await interaction.response.send_message("✅ Field added.", ephemeral=True)

    # ─────────────────────────────────────────────────────────────────────
    # /embed clearfields
    # ─────────────────────────────────────────────────────────────────────

    @slash.command(name="clearfields", description="Remove all fields from an existing embed.")
    @app_commands.describe(
        message_id="ID of the message containing the embed",
        channel="Channel where the message is",
    )
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed_clearfields(
        self,
        interaction: discord.Interaction,
        message_id: str,
        channel: discord.TextChannel = None,
    ):
        ch = channel or interaction.channel
        try:
            msg = await ch.fetch_message(int(message_id))
        except (discord.NotFound, ValueError):
            await interaction.response.send_message("❌ Message not found.", ephemeral=True)
            return
        if msg.author != self.bot.user:
            await interaction.response.send_message("❌ I can only edit my own messages.", ephemeral=True)
            return
        if not msg.embeds:
            await interaction.response.send_message("❌ That message has no embeds.", ephemeral=True)
            return
        e = msg.embeds[0].copy()
        e.clear_fields()
        await msg.edit(embed=e)
        await interaction.response.send_message("✅ All fields cleared.", ephemeral=True)

    # ─────────────────────────────────────────────────────────────────────
    # /embed setauthor
    # ─────────────────────────────────────────────────────────────────────

    @slash.command(name="setauthor", description="Set the author line on an existing embed.")
    @app_commands.describe(
        message_id="ID of the message containing the embed",
        name="Author name",
        icon_url="Author icon URL (optional)",
        url="Author URL link (optional)",
        channel="Channel where the message is",
    )
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed_setauthor(
        self,
        interaction: discord.Interaction,
        message_id: str,
        name: str,
        icon_url: str = None,
        url: str = None,
        channel: discord.TextChannel = None,
    ):
        ch = channel or interaction.channel
        try:
            msg = await ch.fetch_message(int(message_id))
        except (discord.NotFound, ValueError):
            await interaction.response.send_message("❌ Message not found.", ephemeral=True)
            return
        if msg.author != self.bot.user:
            await interaction.response.send_message("❌ I can only edit my own messages.", ephemeral=True)
            return
        if not msg.embeds:
            await interaction.response.send_message("❌ That message has no embeds.", ephemeral=True)
            return
        e = msg.embeds[0].copy()
        e.set_author(name=name, icon_url=icon_url, url=url)
        await msg.edit(embed=e)
        await interaction.response.send_message("✅ Author set.", ephemeral=True)

    # ─────────────────────────────────────────────────────────────────────
    # /embed json
    # ─────────────────────────────────────────────────────────────────────

    @slash.command(name="json", description="Send an embed from a Discohook-compatible JSON payload.")
    @app_commands.describe(
        payload="JSON string representing a Discord embed object",
        channel="Target channel (defaults to current)",
    )
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed_json(
        self,
        interaction: discord.Interaction,
        payload: str,
        channel: discord.TextChannel = None,
    ):
        ch = channel or interaction.channel
        try:
            data = json.loads(payload)
            if isinstance(data, dict) and "embeds" in data:
                embeds = [discord.Embed.from_dict(em) for em in data["embeds"]]
            elif isinstance(data, dict):
                embeds = [discord.Embed.from_dict(data)]
            elif isinstance(data, list):
                embeds = [discord.Embed.from_dict(em) for em in data]
            else:
                raise ValueError("Unknown payload format")
        except (json.JSONDecodeError, Exception) as exc:
            await interaction.response.send_message(
                f"❌ Failed to parse JSON: {exc}", ephemeral=True
            )
            return
        if len(embeds) > 10:
            await interaction.response.send_message(
                "❌ Maximum 10 embeds per message.", ephemeral=True
            )
            return
        await ch.send(embeds=embeds)
        await interaction.response.send_message(
            f"✅ {len(embeds)} embed(s) sent to {ch.mention}.", ephemeral=True
        )

    # ─────────────────────────────────────────────────────────────────────
    # /embed preview
    # ─────────────────────────────────────────────────────────────────────

    @slash.command(name="preview", description="Preview an embed privately before sending it.")
    @app_commands.describe(
        title="Title",
        description="Body text",
        color="Hex color (optional)",
        footer="Footer text (optional)",
        image="Image URL (optional)",
        thumbnail="Thumbnail URL (optional)",
    )
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed_preview(
        self,
        interaction: discord.Interaction,
        title: str = None,
        description: str = None,
        color: str = None,
        footer: str = None,
        image: str = None,
        thumbnail: str = None,
    ):
        if not title and not description:
            await interaction.response.send_message(
                "❌ Provide at least a title or description.", ephemeral=True
            )
            return
        e = discord.Embed(
            title=title,
            description=description,
            color=parse_color(color),
            timestamp=discord.utils.utcnow(),
        )
        if footer:
            e.set_footer(text=footer)
        if image:
            e.set_image(url=image)
        if thumbnail:
            e.set_thumbnail(url=thumbnail)
        await interaction.response.send_message(
            "👀 Here's how your embed will look:", embed=e, ephemeral=True
        )

    # ─────────────────────────────────────────────────────────────────────
    # /embed dmall
    # ─────────────────────────────────────────────────────────────────────

    @slash.command(
        name="dmall",
        description="Schedule a custom DM to be sent to every member at a specific date/time.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def embed_dmall(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            DmAllModal(guild=interaction.guild, cog=self)
        )

    # ─────────────────────────────────────────────────────────────────────
    # /embed dmall_cancel
    # ─────────────────────────────────────────────────────────────────────

    @slash.command(name="dmall_cancel", description="Cancel a pending scheduled DM-all for this server.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def embed_dmall_cancel(self, interaction: discord.Interaction):
        gid = interaction.guild_id
        key = _scheduled_dm_key(gid)
        data = load(str(gid))
        entry = data.get(key)
        if not entry:
            await interaction.response.send_message(
                "ℹ️ No DM-all is currently scheduled for this server.", ephemeral=True
            )
            return
        data.pop(key, None)
        save(str(gid), data)
        self._pending.pop(gid, None)
        send_at = entry.get("send_at", "unknown time")
        await interaction.response.send_message(
            f"✅ Scheduled DM-all (was set for `{send_at}`) has been cancelled.", ephemeral=True
        )

    # ─────────────────────────────────────────────────────────────────────
    # /embed dmall_status
    # ─────────────────────────────────────────────────────────────────────

    @slash.command(name="dmall_status", description="Check the status of the scheduled DM-all for this server.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def embed_dmall_status(self, interaction: discord.Interaction):
        gid = interaction.guild_id
        key = _scheduled_dm_key(gid)
        data = load(str(gid))
        entry = data.get(key)
        if not entry:
            await interaction.response.send_message(
                "ℹ️ No DM-all is scheduled.", ephemeral=True
            )
            return
        send_at = entry.get("send_at", "unknown")
        preview = (entry.get("message") or "")[:100]
        title   = entry.get("embed_title") or "*(plain text)*"
        by_id   = entry.get("scheduled_by")
        by_str  = f"<@{by_id}>" if by_id else "unknown"
        e = discord.Embed(
            title="📨 Scheduled DM-All",
            color=Config.COLOR_INFO,
        )
        e.add_field(name="Send At (UTC)", value=f"`{send_at}`", inline=False)
        e.add_field(name="Scheduled By", value=by_str, inline=True)
        e.add_field(name="Embed Title", value=title, inline=True)
        e.add_field(
            name="Message Preview",
            value=f"{preview}{'…' if len(entry.get('message', '')) > 100 else ''}",
            inline=False,
        )
        await interaction.response.send_message(embed=e, ephemeral=True)


# ─────────────────────────────────────────────────────────────────────────────
# Rules Dropdown System
# ─────────────────────────────────────────────────────────────────────────────
#
# Admins build a named "rules panel" with up to 25 labelled items.
# /embed rules post  sends a persistent Select menu to a channel.
# Clicking an option shows that rule as an ephemeral message — exactly like
# Sapphire's rules feature.
#
# Data stored in rules.json:
#   { guild_id: { panel_name: { title, description, items: [{label, content}], posted: [{channel_id, message_id}] } } }
# ─────────────────────────────────────────────────────────────────────────────

RULES_FILE = "rules.json"


def _load_rules(guild_id: int) -> dict:
    return load(RULES_FILE).get(str(guild_id), {})


def _save_rules(guild_id: int, data: dict):
    full = load(RULES_FILE)
    full[str(guild_id)] = data
    save(RULES_FILE, full)


def _get_panel(guild_id: int, name: str) -> dict | None:
    return _load_rules(guild_id).get(name.lower())


def _save_panel(guild_id: int, name: str, panel: dict):
    d = _load_rules(guild_id)
    d[name.lower()] = panel
    _save_rules(guild_id, d)


def _all_rules_panels() -> list[dict]:
    """Return every panel across all guilds for persistent view re-registration."""
    data = load(RULES_FILE)
    out = []
    for guild_data in data.values():
        for panel in guild_data.values():
            out.append(panel)
    return out


# ---------------------------------------------------------------------------
# Persistent Rules Select View
# ---------------------------------------------------------------------------

class RulesSelect(discord.ui.Select):
    def __init__(self, panel_name: str, items: list[dict]):
        self.panel_name = panel_name
        options = [
            discord.SelectOption(
                label=item["label"][:100],
                value=str(i),
                # Use the short hint if set, otherwise first 100 chars of content
                description=(item.get("hint") or item["content"])[:100] or None,
            )
            for i, item in enumerate(items[:25])
        ]
        super().__init__(
            custom_id=f"rules_select:{panel_name}",
            placeholder="Select a rule to view…",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        # Re-load panel fresh so edits are reflected without restart
        panel = _get_panel(interaction.guild_id, self.panel_name)
        if not panel:
            await interaction.response.send_message(
                "❌ This rules panel no longer exists.", ephemeral=True
            )
            return
        items = panel.get("items", [])
        idx = int(self.values[0])
        if idx >= len(items):
            await interaction.response.send_message(
                "❌ That option is no longer available.", ephemeral=True
            )
            return
        item = items[idx]
        e = discord.Embed(
            title=item["label"],
            description=item["content"],
            color=Config.COLOR_INFO,
        )
        panel_title = panel.get("title")
        if panel_title:
            e.set_author(name=panel_title)
        await interaction.response.send_message(embed=e, ephemeral=True)


class RulesView(discord.ui.View):
    """Persistent view — one per panel_name, registered on startup."""

    def __init__(self, panel_name: str, items: list[dict]):
        super().__init__(timeout=None)
        self.panel_name = panel_name
        self.add_item(RulesSelect(panel_name, items))


# ---------------------------------------------------------------------------
# Rules Modals
# ---------------------------------------------------------------------------

class RulesCreateModal(discord.ui.Modal, title="Create Rules Panel"):
    panel_name = discord.ui.TextInput(
        label="Panel name (internal ID, e.g. server-rules)",
        placeholder="server-rules",
        max_length=50,
    )
    panel_title = discord.ui.TextInput(
        label="Embed title",
        placeholder="Server Rules",
        max_length=256,
    )
    panel_description = discord.ui.TextInput(
        label="Embed description (optional)",
        placeholder="Select a rule from the dropdown to read it.",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=2000,
    )

    def __init__(self, guild_id: int, bot):
        super().__init__()
        self.guild_id = guild_id
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        name = self.panel_name.value.strip().lower().replace(" ", "-")
        if _get_panel(self.guild_id, name):
            await interaction.response.send_message(
                f"❌ A panel called `{name}` already exists.", ephemeral=True
            )
            return
        _save_panel(self.guild_id, name, {
            "name":        name,
            "title":       self.panel_title.value.strip(),
            "description": self.panel_description.value.strip(),
            "items":       [],
            "posted":      [],
        })
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"✅ Panel `{name}` created",
                description=(
                    f"**Title:** {self.panel_title.value.strip()}\n"
                    f"Add items with `/rules additem name:{name}`\n"
                    f"Then post with `/rules post name:{name}`"
                ),
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )


class RulesAddItemModal(discord.ui.Modal, title="Add Rule Item"):
    item_label = discord.ui.TextInput(
        label="Dropdown label (shown in the menu)",
        placeholder="Rule 1 — Be Respectful",
        max_length=100,
    )
    item_description = discord.ui.TextInput(
        label="Dropdown hint (shown under label, optional)",
        placeholder="Short one-line summary",
        required=False,
        max_length=100,
    )
    item_content = discord.ui.TextInput(
        label="Full rule text (shown when selected)",
        placeholder="Treat all members with respect...",
        style=discord.TextStyle.paragraph,
        max_length=4000,
    )

    def __init__(self, guild_id: int, panel_name: str):
        super().__init__()
        self.guild_id   = guild_id
        self.panel_name = panel_name

    async def on_submit(self, interaction: discord.Interaction):
        panel = _get_panel(self.guild_id, self.panel_name)
        if not panel:
            await interaction.response.send_message(
                f"❌ Panel `{self.panel_name}` not found.", ephemeral=True
            )
            return
        if len(panel["items"]) >= 25:
            await interaction.response.send_message(
                "❌ A panel can have at most 25 items (Discord dropdown limit).", ephemeral=True
            )
            return
        label   = self.item_label.value.strip()
        hint    = self.item_description.value.strip()
        content = self.item_content.value.strip()
        panel["items"].append({"label": label, "hint": hint, "content": content})
        _save_panel(self.guild_id, self.panel_name, panel)
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"✅ Item added to `{self.panel_name}`",
                description=f"**{label}**\n{content[:200]}{'…' if len(content) > 200 else ''}",
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )


class RulesEditItemModal(discord.ui.Modal, title="Edit Rule Item"):
    item_label = discord.ui.TextInput(
        label="Dropdown label (blank = keep current)",
        required=False,
        max_length=100,
    )
    item_description = discord.ui.TextInput(
        label="Dropdown hint (blank = keep current)",
        required=False,
        max_length=100,
    )
    item_content = discord.ui.TextInput(
        label="Full rule text (blank = keep current)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=4000,
    )

    def __init__(self, guild_id: int, panel_name: str, item_index: int, current: dict):
        super().__init__()
        self.guild_id   = guild_id
        self.panel_name = panel_name
        self.item_index = item_index
        # Pre-fill with current values
        self.item_label.default       = current.get("label", "")[:100]
        self.item_description.default = current.get("hint",  "")[:100]
        self.item_content.default     = current.get("content", "")[:4000]

    async def on_submit(self, interaction: discord.Interaction):
        panel = _get_panel(self.guild_id, self.panel_name)
        if not panel or self.item_index >= len(panel.get("items", [])):
            await interaction.response.send_message("❌ Item not found.", ephemeral=True)
            return
        item = panel["items"][self.item_index]
        if self.item_label.value.strip():
            item["label"]   = self.item_label.value.strip()
        if self.item_description.value.strip():
            item["hint"]    = self.item_description.value.strip()
        if self.item_content.value.strip():
            item["content"] = self.item_content.value.strip()
        panel["items"][self.item_index] = item
        _save_panel(self.guild_id, self.panel_name, panel)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Item updated",
                description=f"**{item['label']}** has been updated.",
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )


class RulesPostModal(discord.ui.Modal, title="Post Rules Panel"):
    custom_title = discord.ui.TextInput(
        label="Embed title (blank = keep panel title)",
        required=False,
        max_length=256,
    )
    custom_description = discord.ui.TextInput(
        label="Embed description (blank = keep panel)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=2000,
    )

    def __init__(self, guild_id: int, panel_name: str, channel: discord.TextChannel, bot):
        super().__init__()
        self.guild_id   = guild_id
        self.panel_name = panel_name
        self.channel    = channel
        self.bot        = bot

    async def on_submit(self, interaction: discord.Interaction):
        panel = _get_panel(self.guild_id, self.panel_name)
        if not panel:
            await interaction.response.send_message(
                f"❌ Panel `{self.panel_name}` not found.", ephemeral=True
            )
            return
        items = panel.get("items", [])
        if not items:
            await interaction.response.send_message(
                "❌ This panel has no items. Add some with `/rules additem` first.",
                ephemeral=True,
            )
            return

        title = self.custom_title.value.strip() or panel.get("title", self.panel_name)
        desc  = self.custom_description.value.strip() or panel.get("description") or "Select a rule from the dropdown below."

        e = discord.Embed(title=title, description=desc, color=Config.COLOR_INFO)
        e.set_footer(text=f"{len(items)} rule(s) available")

        view = RulesView(self.panel_name, items)
        self.bot.add_view(view)
        msg = await self.channel.send(embed=e, view=view)

        panel.setdefault("posted", []).append({
            "channel_id": self.channel.id,
            "message_id": msg.id,
        })
        _save_panel(self.guild_id, self.panel_name, panel)

        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Rules panel posted",
                description=f"Posted `{self.panel_name}` in {self.channel.mention}.",
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Rules Cog
# ---------------------------------------------------------------------------

class RulesCog(commands.Cog, name="Rules"):
    """📋 Sapphire-style rules dropdown panels."""

    slash = app_commands.Group(
        name="rules",
        description="Create and manage rules dropdown panels",
        parent=None,
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -- /rules create --------------------------------------------------------

    @slash.command(name="create", description="Create a new rules panel (opens a modal).")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rules_create(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            RulesCreateModal(interaction.guild_id, self.bot)
        )

    # -- /rules additem -------------------------------------------------------

    @slash.command(name="additem", description="Add a rule item to a panel (opens a modal).")
    @app_commands.describe(name="Panel name to add a rule to")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rules_additem(self, interaction: discord.Interaction, name: str):
        panel = _get_panel(interaction.guild_id, name.lower())
        if not panel:
            await interaction.response.send_message(f"❌ Panel `{name}` not found.", ephemeral=True)
            return
        if len(panel.get("items", [])) >= 25:
            await interaction.response.send_message(
                "❌ This panel already has 25 items (Discord dropdown limit).", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            RulesAddItemModal(interaction.guild_id, name.lower())
        )

    # -- /rules edititem ------------------------------------------------------

    @slash.command(name="edititem", description="Edit an existing rule item (opens a modal).")
    @app_commands.describe(name="Panel name", number="Item number (see /rules preview)")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rules_edititem(self, interaction: discord.Interaction, name: str, number: int):
        panel = _get_panel(interaction.guild_id, name.lower())
        if not panel:
            await interaction.response.send_message(f"❌ Panel `{name}` not found.", ephemeral=True)
            return
        idx = number - 1
        if idx < 0 or idx >= len(panel.get("items", [])):
            await interaction.response.send_message("❌ Invalid item number.", ephemeral=True)
            return
        await interaction.response.send_modal(
            RulesEditItemModal(interaction.guild_id, name.lower(), idx, panel["items"][idx])
        )

    # -- /rules removeitem ----------------------------------------------------

    @slash.command(name="removeitem", description="Remove a rule item from a panel.")
    @app_commands.describe(name="Panel name", number="Item number (see /rules preview)")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rules_removeitem(self, interaction: discord.Interaction, name: str, number: int):
        panel = _get_panel(interaction.guild_id, name.lower())
        if not panel:
            await interaction.response.send_message(f"❌ Panel `{name}` not found.", ephemeral=True)
            return
        idx = number - 1
        if idx < 0 or idx >= len(panel["items"]):
            await interaction.response.send_message("❌ Invalid item number.", ephemeral=True)
            return
        removed = panel["items"].pop(idx)
        _save_panel(interaction.guild_id, name.lower(), panel)
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"✅ Removed item from `{name}`",
                description=f"Removed: **{removed['label']}**",
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

    # -- /rules preview -------------------------------------------------------

    @slash.command(name="preview", description="Preview a rules panel privately.")
    @app_commands.describe(name="Panel name")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rules_preview(self, interaction: discord.Interaction, name: str):
        panel = _get_panel(interaction.guild_id, name.lower())
        if not panel:
            await interaction.response.send_message(f"❌ Panel `{name}` not found.", ephemeral=True)
            return
        items = panel.get("items", [])
        e = discord.Embed(
            title=panel.get("title", name),
            description=panel.get("description") or "No description set.",
            color=Config.COLOR_INFO,
        )
        if not items:
            e.add_field(name="Items", value="No items yet. Use `/rules additem`.", inline=False)
        else:
            for i, item in enumerate(items):
                val = item["content"][:200] + ("…" if len(item["content"]) > 200 else "")
                if item.get("hint"):
                    val = f"*{item['hint']}*\n{val}"
                e.add_field(name=f"{i + 1}. {item['label']}", value=val, inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # -- /rules list ----------------------------------------------------------

    @slash.command(name="list", description="List all rules panels in this server.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rules_list(self, interaction: discord.Interaction):
        panels = _load_rules(interaction.guild_id)
        if not panels:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="No rules panels yet. Use `/rules create` to make one.",
                    color=Config.COLOR_INFO,
                ),
                ephemeral=True,
            )
            return
        e = discord.Embed(title=f"Rules Panels ({len(panels)})", color=Config.COLOR_INFO)
        for pname, panel in panels.items():
            item_count = len(panel.get("items", []))
            posted     = len(panel.get("posted", []))
            e.add_field(
                name=pname,
                value=f"{item_count} item(s) | {posted} posted message(s)",
                inline=True,
            )
        await interaction.response.send_message(embed=e, ephemeral=True)

    # -- /rules post ----------------------------------------------------------

    @slash.command(name="post", description="Post a rules dropdown panel to a channel (opens a modal).")
    @app_commands.describe(
        name="Panel name",
        channel="Channel to post in (defaults to current)",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rules_post(
        self,
        interaction: discord.Interaction,
        name: str,
        channel: discord.TextChannel = None,
    ):
        panel = _get_panel(interaction.guild_id, name.lower())
        if not panel:
            await interaction.response.send_message(f"❌ Panel `{name}` not found.", ephemeral=True)
            return
        if not panel.get("items"):
            await interaction.response.send_message(
                "❌ This panel has no items. Add some with `/rules additem` first.", ephemeral=True
            )
            return
        ch = channel or interaction.channel
        await interaction.response.send_modal(
            RulesPostModal(interaction.guild_id, name.lower(), ch, self.bot)
        )

    # -- /rules delete --------------------------------------------------------

    @slash.command(name="delete", description="Permanently delete a rules panel.")
    @app_commands.describe(name="Panel name")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def rules_delete(self, interaction: discord.Interaction, name: str):
        d = _load_rules(interaction.guild_id)
        if name.lower() not in d:
            await interaction.response.send_message(f"❌ Panel `{name}` not found.", ephemeral=True)
            return
        del d[name.lower()]
        _save_rules(interaction.guild_id, d)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Deleted",
                description=f"Panel `{name}` has been deleted.",
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedCog(bot))
    await bot.add_cog(RulesCog(bot))

    # Re-register all persistent RulesView instances so dropdowns survive restarts
    registered: set[str] = set()
    for panel in _all_rules_panels():
        pname = panel.get("name", "")
        items = panel.get("items", [])
        if pname and pname not in registered and items:
            bot.add_view(RulesView(pname, items))
            registered.add(pname)