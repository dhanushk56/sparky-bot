"""
cogs/antinuke.py
Complete anti-nuke protection with 22 event types, per-event whitelisting, 
customizable thresholds, punishments, and forbidden channels.
"""

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
from datetime import datetime, timedelta, timezone
from config import Config
from utils.data import load, save

ANTINUKE_FILE = "antinuke.json"

# ── Data helpers ──────────────────────────────────────

def _antinuke_data(guild_id: int) -> dict:
    return load(ANTINUKE_FILE).get(str(guild_id), {
        "enabled": False,
        "whitelist": {},          # {user_id: ["ban", "kick"]} — per-event whitelist
        "global_whitelist": [],   # [user_id] — whitelisted for everything
        "owner_id": None,
        "forbidden_channels": [],
        "thresholds": {
            "ban": 1, "kick": 1, "prune": 1, "bot_add": 1,
            "guild_update": 1, "channel_create": 1, "channel_delete": 1,
            "channel_update": 1, "role_create": 1, "role_delete": 1,
            "role_update": 1, "role_dangerous_perms": 1, "mention_everyone": 1,
            "webhook_create": 1, "webhook_update": 1, "webhook_delete": 1,
            "member_update": 1, "member_dangerous_perms": 1,
            "integration_add": 1, "sticker_update": 1, "emoji_update": 1,
        },
        "punishment": "ban",
        "duration": 1440,
        "log_channel": None,
    })

def _save_antinuke(guild_id: int, data: dict):
    full = load(ANTINUKE_FILE)
    full[str(guild_id)] = data
    save(ANTINUKE_FILE, full)

def _is_whitelisted(guild_id: int, user_id: int, event: str = None) -> bool:
    """Check if user is whitelisted. If event is provided, checks per-event whitelist too."""
    data = _antinuke_data(guild_id)
    # Server owner is always fully whitelisted
    if user_id == data.get("owner_id"):
        return True
    # Global whitelist — whitelisted for everything
    if user_id in data.get("global_whitelist", []):
        return True
    # Per-event whitelist
    if event:
        per_event = data.get("whitelist", {})
        allowed_events = per_event.get(str(user_id), [])
        if event in allowed_events:
            return True
    return False

ALL_EVENTS = [
    "ban", "kick", "prune", "bot_add", "guild_update",
    "channel_create", "channel_delete", "channel_update",
    "role_create", "role_delete", "role_update", "role_dangerous_perms",
    "mention_everyone", "webhook_create", "webhook_update", "webhook_delete",
    "member_update", "member_dangerous_perms", "integration_add",
    "sticker_update", "emoji_update",
]

def _mod_embed(title: str, description: str, color=Config.COLOR_ERR) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))

async def _log_action(guild: discord.Guild, data: dict, embed: discord.Embed):
    log_ch_id = data.get("log_channel")
    if log_ch_id:
        ch = guild.get_channel(int(log_ch_id))
        if ch:
            try:
                await ch.send(embed=embed)
            except Exception:
                pass

DANGEROUS_PERMISSIONS = [
    "administrator", "ban_members", "kick_members", "manage_guild",
    "manage_channels", "manage_roles", "manage_webhooks", "manage_emojis",
    "manage_nicknames", "moderate_members", "mention_everyone",
]


class AntiNuke(commands.Cog):
    """🛡️ Complete anti-nuke protection with per-event whitelisting."""

    antinuke = app_commands.Group(name="antinuke", description="Anti-nuke protection commands")

    def __init__(self, bot):
        self.bot = bot
        self.cooldowns: dict[str, list[datetime]] = {}

    def _check_threshold(self, guild_id: int, user_id: int, event: str) -> bool:
        data = _antinuke_data(guild_id)
        if not data.get("enabled"):
            return False
        if _is_whitelisted(guild_id, user_id, event):
            return False
        threshold = data.get("thresholds", {}).get(event, 1)
        now = datetime.now(timezone.utc)
        key = f"{guild_id}_{user_id}_{event}"
        times = self.cooldowns.get(key, [])
        times = [t for t in times if (now - t).total_seconds() < 60]
        times.append(now)
        self.cooldowns[key] = times
        return len(times) >= threshold

    async def _punish(self, guild: discord.Guild, user_id: int, reason: str):
        data = _antinuke_data(guild.id)
        punishment = data.get("punishment", "ban")
        duration = data.get("duration", 1440)
        member = guild.get_member(user_id)
        if not member:
            return
        embed = _mod_embed("🛡️ Anti-Nuke Triggered", f"**User:** {member.mention}\n**Action:** {punishment}\n**Reason:** {reason}")
        await _log_action(guild, data, embed)
        if punishment == "ban":
            try:
                await member.ban(reason=f"Anti-nuke: {reason}", delete_message_days=7)
            except Exception:
                pass
            if duration > 0:
                await asyncio.sleep(duration * 60)
                try:
                    await guild.unban(discord.Object(user_id), reason="Anti-nuke punishment expired")
                except Exception:
                    pass
        elif punishment == "kick":
            try:
                await member.kick(reason=f"Anti-nuke: {reason}")
            except Exception:
                pass
        elif punishment == "timeout":
            try:
                until = discord.utils.utcnow() + timedelta(minutes=duration)
                await member.timeout(until, reason=f"Anti-nuke: {reason}")
            except Exception:
                pass

    # ═══════════════════════════════════════════════════
    # FORBIDDEN CHANNEL & @everyone
    # ═══════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.author.id == message.guild.owner_id:
            return
        data = _antinuke_data(message.guild.id)
        if not data.get("enabled"):
            return
        if message.channel.id in data.get("forbidden_channels", []):
            if _is_whitelisted(message.guild.id, message.author.id):
                return
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await message.author.send(embed=_mod_embed("🚫 Forbidden Channel", f"You were banned from **{message.guild.name}** for sending a message in {message.channel.mention}.", Config.COLOR_ERR))
            except Exception:
                pass
            try:
                await message.author.ban(reason=f"Forbidden channel: #{message.channel.name}", delete_message_days=1)
            except Exception:
                pass
            embed = _mod_embed("🚫 Forbidden Channel Violation", f"**User:** {message.author.mention}\n**Channel:** {message.channel.mention}\n**Action:** Banned", Config.COLOR_ERR)
            await _log_action(message.guild, data, embed)
            return
        if message.mention_everyone:
            if self._check_threshold(message.guild.id, message.author.id, "mention_everyone"):
                try:
                    await message.delete()
                except Exception:
                    pass
                await self._punish(message.guild, message.author.id, "@everyone mention detected")
                self.cooldowns.pop(f"{message.guild.id}_{message.author.id}_mention_everyone", None)

    # ═══════════════════════════════════════════════════
    # EVENT LISTENERS (all 22)
    # ═══════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        await asyncio.sleep(0.5)
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
                if entry.user and entry.user.id != self.bot.user.id:
                    if self._check_threshold(guild.id, entry.user.id, "ban"):
                        await self._punish(guild, entry.user.id, "Mass banning detected")
                        self.cooldowns.pop(f"{guild.id}_{entry.user.id}_ban", None)
                break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await asyncio.sleep(0.5)
        # Check for kick
        try:
            async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
                if entry.user and entry.target and entry.target.id == member.id:
                    if entry.user.id != self.bot.user.id:
                        if self._check_threshold(member.guild.id, entry.user.id, "kick"):
                            await self._punish(member.guild, entry.user.id, "Mass kicking detected")
                            self.cooldowns.pop(f"{member.guild.id}_{entry.user.id}_kick", None)
                    break
        except Exception:
            pass
        # Check for prune
        try:
            async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_prune):
                if entry.user and entry.user.id != self.bot.user.id:
                    if self._check_threshold(member.guild.id, entry.user.id, "prune"):
                        await self._punish(member.guild, entry.user.id, "Mass prune detected")
                        self.cooldowns.pop(f"{member.guild.id}_{entry.user.id}_prune", None)
                break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.bot:
            return
        await asyncio.sleep(0.5)
        try:
            async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
                if entry.user and entry.user.id != self.bot.user.id:
                    if self._check_threshold(member.guild.id, entry.user.id, "bot_add"):
                        try:
                            await member.ban(reason="Anti-nuke: Unauthorized bot added", delete_message_days=1)
                        except Exception:
                            pass
                        await self._punish(member.guild, entry.user.id, "Unauthorized bot added")
                        self.cooldowns.pop(f"{member.guild.id}_{entry.user.id}_bot_add", None)
                break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        await asyncio.sleep(0.5)
        try:
            async for entry in after.audit_logs(limit=1, action=discord.AuditLogAction.guild_update):
                if entry.user and entry.user.id != self.bot.user.id:
                    if self._check_threshold(after.id, entry.user.id, "guild_update"):
                        if before.name != after.name:
                            try:
                                await after.edit(name=before.name)
                            except Exception:
                                pass
                        if before.icon and before.icon != after.icon:
                            try:
                                await after.edit(icon=await before.icon.read())
                            except Exception:
                                pass
                        await self._punish(after, entry.user.id, "Server settings changed")
                        self.cooldowns.pop(f"{after.id}_{entry.user.id}_guild_update", None)
                break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        await asyncio.sleep(0.5)
        try:
            async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
                if entry.user and entry.user.id != self.bot.user.id:
                    if self._check_threshold(channel.guild.id, entry.user.id, "channel_create"):
                        try:
                            await channel.delete()
                        except Exception:
                            pass
                        await self._punish(channel.guild, entry.user.id, "Unauthorized channel created")
                        self.cooldowns.pop(f"{channel.guild.id}_{entry.user.id}_channel_create", None)
                break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        await asyncio.sleep(0.5)
        try:
            async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
                if entry.user and entry.user.id != self.bot.user.id:
                    if self._check_threshold(channel.guild.id, entry.user.id, "channel_delete"):
                        await self._punish(channel.guild, entry.user.id, "Channel deleted")
                        self.cooldowns.pop(f"{channel.guild.id}_{entry.user.id}_channel_delete", None)
                break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        await asyncio.sleep(0.5)
        try:
            async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_update):
                if entry.user and entry.user.id != self.bot.user.id:
                    if self._check_threshold(after.guild.id, entry.user.id, "channel_update"):
                        await self._punish(after.guild, entry.user.id, "Channel settings modified")
                        self.cooldowns.pop(f"{after.guild.id}_{entry.user.id}_channel_update", None)
                break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await asyncio.sleep(0.5)
        try:
            async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create):
                if entry.user and entry.user.id != self.bot.user.id:
                    if self._check_threshold(role.guild.id, entry.user.id, "role_create"):
                        try:
                            await role.delete()
                        except Exception:
                            pass
                        await self._punish(role.guild, entry.user.id, "Unauthorized role created")
                        self.cooldowns.pop(f"{role.guild.id}_{entry.user.id}_role_create", None)
                break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await asyncio.sleep(0.5)
        try:
            async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
                if entry.user and entry.user.id != self.bot.user.id:
                    if self._check_threshold(role.guild.id, entry.user.id, "role_delete"):
                        await self._punish(role.guild, entry.user.id, "Role deleted")
                        self.cooldowns.pop(f"{role.guild.id}_{entry.user.id}_role_delete", None)
                break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        await asyncio.sleep(0.5)
        try:
            async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_update):
                if entry.user and entry.user.id != self.bot.user.id:
                    new_perms = set([p for p, v in after.permissions if v])
                    for perm in DANGEROUS_PERMISSIONS:
                        if perm in new_perms and perm not in set([p for p, v in before.permissions if v]):
                            if self._check_threshold(after.guild.id, entry.user.id, "role_dangerous_perms"):
                                try:
                                    await after.edit(permissions=before.permissions)
                                except Exception:
                                    pass
                                await self._punish(after.guild, entry.user.id, f"Dangerous permission added: {perm}")
                                self.cooldowns.pop(f"{after.guild.id}_{entry.user.id}_role_dangerous_perms", None)
                                return
                    if self._check_threshold(after.guild.id, entry.user.id, "role_update"):
                        await self._punish(after.guild, entry.user.id, "Role modified")
                        self.cooldowns.pop(f"{after.guild.id}_{entry.user.id}_role_update", None)
                break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        await asyncio.sleep(0.5)
        try:
            async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.webhook_create):
                if entry.user and entry.user.id != self.bot.user.id:
                    if self._check_threshold(channel.guild.id, entry.user.id, "webhook_create"):
                        webhooks = await channel.webhooks()
                        for wh in webhooks:
                            try:
                                await wh.delete()
                            except Exception:
                                pass
                        await self._punish(channel.guild, entry.user.id, "Unauthorized webhook created")
                        self.cooldowns.pop(f"{channel.guild.id}_{entry.user.id}_webhook_create", None)
                break
        except Exception:
            pass
        try:
            async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.webhook_update):
                if entry.user and entry.user.id != self.bot.user.id:
                    if self._check_threshold(channel.guild.id, entry.user.id, "webhook_update"):
                        await self._punish(channel.guild, entry.user.id, "Webhook modified")
                        self.cooldowns.pop(f"{channel.guild.id}_{entry.user.id}_webhook_update", None)
                break
        except Exception:
            pass
        try:
            async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.webhook_delete):
                if entry.user and entry.user.id != self.bot.user.id:
                    if self._check_threshold(channel.guild.id, entry.user.id, "webhook_delete"):
                        await self._punish(channel.guild, entry.user.id, "Webhook deleted")
                        self.cooldowns.pop(f"{channel.guild.id}_{entry.user.id}_webhook_delete", None)
                break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        await asyncio.sleep(0.5)
        try:
            async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
                if entry.user and entry.user.id != self.bot.user.id:
                    new_roles = set(after.roles) - set(before.roles)
                    for role in new_roles:
                        if any(getattr(role.permissions, p, False) for p in DANGEROUS_PERMISSIONS):
                            if self._check_threshold(after.guild.id, entry.user.id, "member_dangerous_perms"):
                                try:
                                    await after.remove_roles(role)
                                except Exception:
                                    pass
                                await self._punish(after.guild, entry.user.id, f"Dangerous role given to {after.display_name}: {role.name}")
                                self.cooldowns.pop(f"{after.guild.id}_{entry.user.id}_member_dangerous_perms", None)
                                return
                    if self._check_threshold(after.guild.id, entry.user.id, "member_update"):
                        await self._punish(after.guild, entry.user.id, f"Member updated: {after.display_name}")
                        self.cooldowns.pop(f"{after.guild.id}_{entry.user.id}_member_update", None)
                break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_integrations_update(self, guild: discord.Guild):
        await asyncio.sleep(0.5)
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.integration_create):
                if entry.user and entry.user.id != self.bot.user.id:
                    if self._check_threshold(guild.id, entry.user.id, "integration_add"):
                        await self._punish(guild, entry.user.id, "Unauthorized integration added")
                        self.cooldowns.pop(f"{guild.id}_{entry.user.id}_integration_add", None)
                break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild: discord.Guild, before, after):
        await asyncio.sleep(0.5)
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.sticker_create):
                if entry.user and entry.user.id != self.bot.user.id:
                    if self._check_threshold(guild.id, entry.user.id, "sticker_update"):
                        await self._punish(guild, entry.user.id, "Sticker modified")
                        self.cooldowns.pop(f"{guild.id}_{entry.user.id}_sticker_update", None)
                break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before, after):
        await asyncio.sleep(0.5)
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.emoji_create):
                if entry.user and entry.user.id != self.bot.user.id:
                    if self._check_threshold(guild.id, entry.user.id, "emoji_update"):
                        await self._punish(guild, entry.user.id, "Emoji modified")
                        self.cooldowns.pop(f"{guild.id}_{entry.user.id}_emoji_update", None)
                break
        except Exception:
            pass

    # ═══════════════════════════════════════════════════
    # SLASH COMMANDS
    # ═══════════════════════════════════════════════════

    @antinuke.command(name="enable", description="Enable anti-nuke protection.")
    @app_commands.default_permissions(administrator=True)
    async def enable(self, interaction: discord.Interaction):
        data = _antinuke_data(interaction.guild.id)
        data["enabled"] = True
        data["owner_id"] = interaction.guild.owner_id
        _save_antinuke(interaction.guild.id, data)
        await interaction.response.send_message("🛡️ Anti-nuke **enabled**.", ephemeral=True)

    @antinuke.command(name="disable", description="Disable anti-nuke protection.")
    @app_commands.default_permissions(administrator=True)
    async def disable(self, interaction: discord.Interaction):
        data = _antinuke_data(interaction.guild.id)
        data["enabled"] = False
        _save_antinuke(interaction.guild.id, data)
        await interaction.response.send_message("🛡️ Anti-nuke **disabled**.", ephemeral=True)

    @antinuke.command(name="status", description="View current anti-nuke settings.")
    @app_commands.default_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction):
        data = _antinuke_data(interaction.guild.id)
        t = data.get("thresholds", {})
        lines = [
            f"**Enabled:** {data.get('enabled', False)}",
            f"**Punishment:** {data.get('punishment', 'ban')} ({data.get('duration', 1440)} min)",
            "",
            "**Thresholds:**",
        ]
        for e in ALL_EVENTS:
            lines.append(f"• {e}: {t.get(e, 1)}")
        lines.append(f"\n**Global Whitelist:** {len(data.get('global_whitelist', []))} users")
        lines.append(f"**Per-Event Whitelist:** {len(data.get('whitelist', {}))} users")
        lines.append(f"**Forbidden Channels:** {len(data.get('forbidden_channels', []))}")
        embed = discord.Embed(title="🛡️ Anti-Nuke Status", description="\n".join(lines), color=Config.COLOR_INFO)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @antinuke.command(name="punishment", description="Set punishment type and duration.")
    @app_commands.describe(action="Punishment type", duration="Minutes (0=permanent)")
    @app_commands.choices(action=[
        app_commands.Choice(name="Ban", value="ban"),
        app_commands.Choice(name="Kick", value="kick"),
        app_commands.Choice(name="Timeout", value="timeout"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def punishment(self, interaction: discord.Interaction, action: str, duration: int = 1440):
        data = _antinuke_data(interaction.guild.id)
        data["punishment"] = action
        data["duration"] = duration
        _save_antinuke(interaction.guild.id, data)
        dur_str = f"{duration} min" if duration > 0 else "permanent"
        await interaction.response.send_message(f"Punishment: **{action}** for **{dur_str}**.", ephemeral=True)

    @antinuke.command(name="threshold", description="Set threshold for an event.")
    @app_commands.describe(event="Event type", threshold="Events in 60s to trigger")
    @app_commands.choices(event=[app_commands.Choice(name=e.replace("_", " ").title(), value=e) for e in ALL_EVENTS])
    @app_commands.default_permissions(administrator=True)
    async def threshold(self, interaction: discord.Interaction, event: str, threshold: int):
        if threshold < 1 or threshold > 50:
            return await interaction.response.send_message("Threshold must be 1-50.", ephemeral=True)
        data = _antinuke_data(interaction.guild.id)
        data.setdefault("thresholds", {})[event] = threshold
        _save_antinuke(interaction.guild.id, data)
        await interaction.response.send_message(f"**{event}** → **{threshold}**/60s.", ephemeral=True)

    @antinuke.command(name="setlog", description="Set anti-nuke log channel.")
    @app_commands.describe(channel="Log channel")
    @app_commands.default_permissions(administrator=True)
    async def setlog(self, interaction: discord.Interaction, channel: discord.TextChannel):
        data = _antinuke_data(interaction.guild.id)
        data["log_channel"] = channel.id
        _save_antinuke(interaction.guild.id, data)
        await interaction.response.send_message(f"Logs → {channel.mention}.", ephemeral=True)

    @antinuke.command(name="whitelist", description="Whitelist a user for ALL events or specific events only.")
    @app_commands.describe(user="User to whitelist", action="Add or remove", events="Specific events (comma-separated, e.g. ban,kick). Leave empty for ALL.")
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def whitelist(self, interaction: discord.Interaction, user: discord.User, action: str, events: str = None):
        data = _antinuke_data(interaction.guild.id)
        
        if action == "add":
            if events:
                # Per-event whitelist
                event_list = [e.strip().lower() for e in events.split(",") if e.strip().lower() in ALL_EVENTS]
                if not event_list:
                    return await interaction.response.send_message(f"Invalid events. Use: {', '.join(ALL_EVENTS[:5])}...", ephemeral=True)
                per_event = data.setdefault("whitelist", {})
                per_event[str(user.id)] = event_list
                _save_antinuke(interaction.guild.id, data)
                await interaction.response.send_message(f"✅ {user.mention} whitelisted for: **{', '.join(event_list)}**.", ephemeral=True)
            else:
                # Global whitelist
                global_wl = data.setdefault("global_whitelist", [])
                if user.id in global_wl:
                    return await interaction.response.send_message(f"{user.mention} already globally whitelisted.", ephemeral=True)
                global_wl.append(user.id)
                _save_antinuke(interaction.guild.id, data)
                await interaction.response.send_message(f"✅ {user.mention} globally whitelisted (all events).", ephemeral=True)
        else:
            # Remove
            global_wl = data.setdefault("global_whitelist", [])
            per_event = data.setdefault("whitelist", {})
            removed = False
            if user.id in global_wl:
                global_wl.remove(user.id)
                removed = True
            if str(user.id) in per_event:
                del per_event[str(user.id)]
                removed = True
            if not removed:
                return await interaction.response.send_message(f"{user.mention} is not whitelisted.", ephemeral=True)
            _save_antinuke(interaction.guild.id, data)
            await interaction.response.send_message(f"✅ {user.mention} removed from whitelist.", ephemeral=True)

    @antinuke.command(name="whitelistinfo", description="View whitelist status for a user.")
    @app_commands.describe(user="User to check")
    @app_commands.default_permissions(manage_guild=True)
    async def whitelistinfo(self, interaction: discord.Interaction, user: discord.User):
        data = _antinuke_data(interaction.guild.id)
        global_wl = data.get("global_whitelist", [])
        per_event = data.get("whitelist", {})
        
        lines = [f"**{user.mention}**"]
        if user.id == interaction.guild.owner_id:
            lines.append("• Server Owner — fully whitelisted")
        elif user.id in global_wl:
            lines.append("• Global whitelist — all events")
        elif str(user.id) in per_event:
            events = per_event[str(user.id)]
            lines.append(f"• Per-event whitelist: **{', '.join(events)}**")
        else:
            lines.append("• Not whitelisted")
        
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @antinuke.command(name="forbidchannel", description="Add/remove a forbidden channel.")
    @app_commands.describe(channel="Channel", action="Add or remove")
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def forbidchannel(self, interaction: discord.Interaction, channel: discord.TextChannel, action: str):
        data = _antinuke_data(interaction.guild.id)
        forbidden = data.setdefault("forbidden_channels", [])
        if action == "add":
            if channel.id in forbidden:
                return await interaction.response.send_message(f"{channel.mention} already forbidden.", ephemeral=True)
            forbidden.append(channel.id)
            _save_antinuke(interaction.guild.id, data)
            await interaction.response.send_message(f"🚫 {channel.mention} forbidden.", ephemeral=True)
        else:
            if channel.id not in forbidden:
                return await interaction.response.send_message(f"{channel.mention} not forbidden.", ephemeral=True)
            forbidden.remove(channel.id)
            _save_antinuke(interaction.guild.id, data)
            await interaction.response.send_message(f"✅ {channel.mention} no longer forbidden.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AntiNuke(bot))