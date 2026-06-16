"""
cogs/logging_cog.py
Slash group: /logging
Logs server events to a configured channel.
Prefix commands still work with ~
"""

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
from config import Config
from utils.data import load, save

LOG_EVENTS = [
    "message_delete", "message_edit", "member_join", "member_leave",
    "member_ban", "member_unban", "role_create", "role_delete",
    "role_update", "channel_create", "channel_delete", "channel_update",
    "voice_join", "voice_leave", "voice_move", "nickname_change",
    "member_role_update", "invite_create", "invite_delete",
]


def _settings(guild_id: int) -> dict:
    data = load("guild_settings.json")
    return data.get(str(guild_id), {}).get("logging", {})


async def _log(guild: discord.Guild, embed: discord.Embed, event: str):
    s = _settings(guild.id)
    if not s.get("enabled", False):
        return
    if not s.get(event, True):
        return
    ch_id = s.get("channel")
    if not ch_id:
        return
    ch = guild.get_channel(int(ch_id))
    if ch:
        try:
            await ch.send(embed=embed)
        except Exception:
            pass


def log_embed(title: str, color: int, **fields) -> discord.Embed:
    e = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
    for k, v in fields.items():
        e.add_field(name=k, value=str(v)[:1024], inline=True)
    return e


class Logging(commands.Cog):
    """📝 Server event logging."""

    slash = app_commands.Group(name="logging", description="Server logging configuration")

    def __init__(self, bot):
        self.bot = bot
        self._invite_cache: dict[int, dict[str, int]] = {}

    async def _cache_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self._invite_cache[guild.id] = {i.code: i.uses for i in invites}
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._cache_invites(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self._cache_invites(guild)

    # ── Message Events ────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        e = log_embed("🗑️ Message Deleted", Config.COLOR_ERR,
            Author=f"{message.author} ({message.author.id})",
            Channel=message.channel.mention,
            Content=message.content[:1024] or "*[No text / attachment]*"
        )
        await _log(message.guild, e, "message_delete")

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild:
            return
        if before.content == after.content:
            return
        e = log_embed("✏️ Message Edited", Config.COLOR_WARN,
            Author=f"{before.author} ({before.author.id})",
            Channel=before.channel.mention,
            Before=before.content[:512] or "*empty*",
            After=after.content[:512] or "*empty*"
        )
        e.add_field(name="Jump", value=f"[Link]({after.jump_url})", inline=False)
        await _log(before.guild, e, "message_edit")

    # ── Member Events ─────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        e = log_embed("📥 Member Joined", Config.COLOR_OK,
            Member=f"{member} ({member.id})",
            Created=discord.utils.format_dt(member.created_at, "R"),
            MemberCount=member.guild.member_count
        )
        e.set_thumbnail(url=member.display_avatar.url)
        try:
            new_invites = await member.guild.invites()
            old_cache   = self._invite_cache.get(member.guild.id, {})
            for inv in new_invites:
                if old_cache.get(inv.code, 0) < inv.uses:
                    e.add_field(name="Invite Used", value=f"`{inv.code}` by {inv.inviter}", inline=False)
                    break
            self._invite_cache[member.guild.id] = {i.code: i.uses for i in new_invites}
        except Exception:
            pass
        await _log(member.guild, e, "member_join")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        roles = [r.mention for r in member.roles if r != member.guild.default_role]
        e = log_embed("📤 Member Left", Config.COLOR_ERR,
            Member=f"{member} ({member.id})",
            Roles=", ".join(roles[:10]) or "None",
            Joined=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Unknown"
        )
        e.set_thumbnail(url=member.display_avatar.url)
        await _log(member.guild, e, "member_leave")

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        e = log_embed("🔨 Member Banned", Config.COLOR_ERR, User=f"{user} ({user.id})")
        await _log(guild, e, "member_ban")

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        e = log_embed("✅ Member Unbanned", Config.COLOR_OK, User=f"{user} ({user.id})")
        await _log(guild, e, "member_unban")

    # ── Role / Nickname Events ─────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick != after.nick:
            e = log_embed("✏️ Nickname Changed", Config.COLOR_INFO,
                Member=f"{after} ({after.id})",
                Before=before.nick or after.name,
                After=after.nick or after.name
            )
            await _log(after.guild, e, "nickname_change")
        added   = [r for r in after.roles  if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if added or removed:
            parts = []
            if added:   parts.append("**Added:** " + ", ".join(r.mention for r in added))
            if removed: parts.append("**Removed:** " + ", ".join(r.mention for r in removed))
            e = log_embed("🎭 Member Roles Updated", Config.COLOR_INFO, Member=f"{after} ({after.id})")
            e.add_field(name="Changes", value="\n".join(parts), inline=False)
            await _log(after.guild, e, "member_role_update")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        e = log_embed("➕ Role Created", Config.COLOR_OK,
            Role=f"{role.name} ({role.id})",
            Color=str(role.color),
            Mentionable="Yes" if role.mentionable else "No"
        )
        await _log(role.guild, e, "role_create")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        e = log_embed("➖ Role Deleted", Config.COLOR_ERR, Role=f"{role.name} ({role.id})")
        await _log(role.guild, e, "role_delete")

    # ── Channel Events ────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        e = log_embed("➕ Channel Created", Config.COLOR_OK,
            Channel=f"#{channel.name} ({channel.id})",
            Type=str(channel.type),
            Category=channel.category.name if channel.category else "None"
        )
        await _log(channel.guild, e, "channel_create")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        e = log_embed("➖ Channel Deleted", Config.COLOR_ERR,
            Channel=f"#{channel.name} ({channel.id})",
            Type=str(channel.type)
        )
        await _log(channel.guild, e, "channel_delete")

    # ── Voice Events ──────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if before.channel == after.channel:
            return
        if before.channel is None:
            e = log_embed("🔊 Voice Joined", Config.COLOR_OK,
                Member=f"{member} ({member.id})", Channel=after.channel.name)
            await _log(member.guild, e, "voice_join")
        elif after.channel is None:
            e = log_embed("🔇 Voice Left", Config.COLOR_ERR,
                Member=f"{member} ({member.id})", Channel=before.channel.name)
            await _log(member.guild, e, "voice_leave")
        else:
            e = log_embed("🔄 Voice Moved", Config.COLOR_WARN,
                Member=f"{member} ({member.id})", From=before.channel.name, To=after.channel.name)
            await _log(member.guild, e, "voice_move")

    # ── Invite Events ─────────────────────────────────

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        e = log_embed("🔗 Invite Created", Config.COLOR_INFO,
            Code=invite.code,
            Creator=str(invite.inviter),
            Channel=f"#{invite.channel}",
            MaxUses=invite.max_uses or "∞",
            Expires=discord.utils.format_dt(invite.expires_at, "R") if invite.expires_at else "Never"
        )
        if invite.guild:
            await _log(invite.guild, e, "invite_create")

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        e = log_embed("🗑️ Invite Deleted", Config.COLOR_ERR, Code=invite.code)
        if invite.guild:
            await _log(invite.guild, e, "invite_delete")

    # ── Config Commands ───────────────────────────────

    @commands.command(name="setlogchannel")
    @commands.has_permissions(administrator=True)
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        data = load("guild_settings.json")
        gd = data.setdefault(str(ctx.guild.id), {})
        gd.setdefault("logging", {})["channel"] = channel.id
        gd["logging"]["enabled"] = True
        save("guild_settings.json", data)
        await ctx.reply(f"✅ Logging channel set to {channel.mention}. All events will be logged.")

    @slash.command(name="setchannel", description="Set the log channel and enable logging.")
    @app_commands.describe(channel="Channel to send logs to")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def setlogchannel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        ctx = await commands.Context.from_interaction(interaction)
        await self.setlogchannel.callback(self, ctx, channel)

    @commands.command(name="logconfig")
    @commands.has_permissions(administrator=True)
    async def logconfig(self, ctx, event: str, enabled: bool):
        if event not in LOG_EVENTS:
            evts = ", ".join(f"`{e}`" for e in LOG_EVENTS)
            return await ctx.reply(f"❌ Unknown event. Options:\n{evts}")
        data = load("guild_settings.json")
        data.setdefault(str(ctx.guild.id), {}).setdefault("logging", {})[event] = enabled
        save("guild_settings.json", data)
        await ctx.reply(f"✅ Logging `{event}`: **{'on' if enabled else 'off'}**.")

    @slash.command(name="config", description="Toggle a specific log event on or off.")
    @app_commands.describe(event="Event name to configure", enabled="True to enable, False to disable")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def logconfig_slash(self, interaction: discord.Interaction, event: str, enabled: bool):
        ctx = await commands.Context.from_interaction(interaction)
        await self.logconfig.callback(self, ctx, event, enabled)

    @commands.command(name="logtoggle")
    @commands.has_permissions(administrator=True)
    async def logtoggle(self, ctx):
        data = load("guild_settings.json")
        lg = data.setdefault(str(ctx.guild.id), {}).setdefault("logging", {})
        lg["enabled"] = not lg.get("enabled", False)
        save("guild_settings.json", data)
        await ctx.reply(f"📝 Logging: **{'enabled' if lg['enabled'] else 'disabled'}**.")

    @slash.command(name="toggle", description="Enable or disable all logging.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def logtoggle_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.logtoggle.callback(self, ctx)


async def setup(bot):
    await bot.add_cog(Logging(bot))
