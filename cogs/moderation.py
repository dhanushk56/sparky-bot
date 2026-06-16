"""
cogs/moderation.py
Slash group: /moderation
Prefix commands still work with ~
"""

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
from datetime import datetime, timedelta, timezone
from config import Config
from utils.data import load, save

WARNS_FILE    = "warnings.json"
JAIL_FILE     = "jail.json"

def mod_embed(title: str, description: str, color=Config.COLOR_MOD) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
    return e

async def log_action(guild: discord.Guild, embed: discord.Embed):
    data = load("guild_settings.json")
    gd = data.get(str(guild.id), {})
    ch_id = gd.get("mod_log_channel")
    if ch_id:
        ch = guild.get_channel(int(ch_id))
        if ch:
            try:
                await ch.send(embed=embed)
            except Exception:
                pass

def get_warns(guild_id: int, user_id: int) -> list:
    data = load(WARNS_FILE)
    return data.get(str(guild_id), {}).get(str(user_id), [])

def add_warn(guild_id: int, user_id: int, reason: str, mod: str):
    data = load(WARNS_FILE)
    data.setdefault(str(guild_id), {}).setdefault(str(user_id), [])
    data[str(guild_id)][str(user_id)].append({
        "reason": reason, "mod": mod,
        "time": datetime.now(timezone.utc).isoformat()
    })
    save(WARNS_FILE, data)

def clear_warns(guild_id: int, user_id: int):
    data = load(WARNS_FILE)
    if str(guild_id) in data:
        data[str(guild_id)].pop(str(user_id), None)
    save(WARNS_FILE, data)


def _jail_data(guild_id: int) -> dict:
    return load(JAIL_FILE).get(str(guild_id), {})

def _save_jail(guild_id: int, data: dict):
    full = load(JAIL_FILE)
    full[str(guild_id)] = data
    save(JAIL_FILE, full)

def _get_jail_config(guild_id: int) -> dict:
    return _jail_data(guild_id).get("config", {})

def _get_jailed(guild_id: int) -> dict:
    return _jail_data(guild_id).get("jailed", {})

def _set_jailed(guild_id: int, user_id: int, role_ids: list[int]):
    d = _jail_data(guild_id)
    d.setdefault("jailed", {})[str(user_id)] = role_ids
    _save_jail(guild_id, d)

def _remove_jailed(guild_id: int, user_id: int):
    d = _jail_data(guild_id)
    d.setdefault("jailed", {}).pop(str(user_id), None)
    _save_jail(guild_id, d)

def _has_jail_permission(interaction: discord.Interaction) -> bool:
    member = interaction.user
    guild  = interaction.guild

    if member.id == guild.owner_id:
        return True

    config     = _get_jail_config(guild.id)
    jail_role_id = config.get("role")

    if not jail_role_id:
        return member.guild_permissions.administrator

    jail_role = guild.get_role(int(jail_role_id))
    if not jail_role:
        return member.guild_permissions.administrator

    return any(r.position > jail_role.position for r in member.roles)


class Moderation(commands.Cog):
    """🔨 Full-featured moderation suite."""

    slash = app_commands.Group(name="moderation", description="Moderation commands")

    def __init__(self, bot):
        self.bot = bot

    # ── KICK ─────────────────────────────────────────

    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        if member == ctx.author:
            return await ctx.reply("❌ You can't kick yourself.")
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.reply("❌ You can't kick someone with an equal or higher role.")
        try:
            await member.send(embed=mod_embed("👢 Kicked", f"You were kicked from **{ctx.guild.name}**\n**Reason:** {reason}", Config.COLOR_WARN))
        except Exception:
            pass
        await member.kick(reason=f"{ctx.author} — {reason}")
        e = mod_embed("👢 Member Kicked", f"**Member:** {member.mention}\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}")
        await ctx.reply(embed=e)
        await log_action(ctx.guild, e)

    @slash.command(name="kick", description="Kick a member from the server.")
    @app_commands.describe(member="Member to kick", reason="Reason for kick")
    @app_commands.default_permissions(kick_members=True)
    async def kick_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        await interaction.response.defer()
        if member == interaction.user:
            return await interaction.followup.send("❌ You can't kick yourself.", ephemeral=True)
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            return await interaction.followup.send("❌ You can't kick someone with an equal or higher role.", ephemeral=True)
        try:
            await member.send(embed=mod_embed("👢 Kicked", f"You were kicked from **{interaction.guild.name}**\n**Reason:** {reason}", Config.COLOR_WARN))
        except Exception:
            pass
        await member.kick(reason=f"{interaction.user} — {reason}")
        e = mod_embed("👢 Member Kicked", f"**Member:** {member.mention}\n**Moderator:** {interaction.user.mention}\n**Reason:** {reason}")
        await interaction.followup.send(embed=e)
        await log_action(interaction.guild, e)

    # ── BAN ──────────────────────────────────────────

    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, delete_days: int = 0, *, reason: str = "No reason provided"):
        if member == ctx.author:
            return await ctx.reply("❌ You can't ban yourself.")
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.reply("❌ You can't ban someone with an equal or higher role.")
        delete_days = max(0, min(7, delete_days))
        try:
            await member.send(embed=mod_embed("🔨 Banned", f"You were banned from **{ctx.guild.name}**\n**Reason:** {reason}", Config.COLOR_ERR))
        except Exception:
            pass
        await member.ban(reason=f"{ctx.author} — {reason}", delete_message_days=delete_days)
        e = mod_embed("🔨 Member Banned", f"**Member:** {member.mention}\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}")
        await ctx.reply(embed=e)
        await log_action(ctx.guild, e)

    @slash.command(name="ban", description="Ban a member from the server.")
    @app_commands.describe(member="Member to ban", delete_days="Days of messages to delete (0-7)", reason="Reason")
    @app_commands.default_permissions(ban_members=True)
    async def ban_slash(self, interaction: discord.Interaction, member: discord.Member, delete_days: int = 0, reason: str = "No reason provided"):
        await interaction.response.defer()
        if member == interaction.user:
            return await interaction.followup.send("❌ You can't ban yourself.", ephemeral=True)
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            return await interaction.followup.send("❌ You can't ban someone with an equal or higher role.", ephemeral=True)
        delete_days = max(0, min(7, delete_days))
        try:
            await member.send(embed=mod_embed("🔨 Banned", f"You were banned from **{interaction.guild.name}**\n**Reason:** {reason}", Config.COLOR_ERR))
        except Exception:
            pass
        await member.ban(reason=f"{interaction.user} — {reason}", delete_message_days=delete_days)
        e = mod_embed("🔨 Member Banned", f"**Member:** {member.mention}\n**Moderator:** {interaction.user.mention}\n**Reason:** {reason}")
        await interaction.followup.send(embed=e)
        await log_action(interaction.guild, e)

    # ── UNBAN ─────────────────────────────────────────

    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: str, *, reason: str = "No reason provided"):
        try:
            uid = int(user_id)
        except ValueError:
            return await ctx.reply("❌ Provide a valid user ID.")
        try:
            user = await self.bot.fetch_user(uid)
            await ctx.guild.unban(user, reason=f"{ctx.author} — {reason}")
            e = mod_embed("✅ Member Unbanned", f"**User:** `{user}`\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}", Config.COLOR_OK)
            await ctx.reply(embed=e)
            await log_action(ctx.guild, e)
        except discord.NotFound:
            await ctx.reply("❌ That user is not banned or doesn't exist.")

    @slash.command(name="unban", description="Unban a user by their ID.")
    @app_commands.describe(user_id="User ID to unban", reason="Reason")
    @app_commands.default_permissions(ban_members=True)
    async def unban_slash(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        await interaction.response.defer()
        try:
            uid = int(user_id)
        except ValueError:
            return await interaction.followup.send("❌ Provide a valid user ID.", ephemeral=True)
        try:
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user, reason=f"{interaction.user} — {reason}")
            e = mod_embed("✅ Member Unbanned", f"**User:** `{user}`\n**Moderator:** {interaction.user.mention}\n**Reason:** {reason}", Config.COLOR_OK)
            await interaction.followup.send(embed=e)
            await log_action(interaction.guild, e)
        except discord.NotFound:
            await interaction.followup.send("❌ That user is not banned or doesn't exist.", ephemeral=True)

    # ── SOFTBAN ───────────────────────────────────────

    @commands.command(name="softban")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def softban(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        await member.ban(reason=f"Softban — {ctx.author}: {reason}", delete_message_days=7)
        await ctx.guild.unban(member, reason="Softban — removing ban after message wipe")
        e = mod_embed("🧹 Member Softbanned", f"**Member:** {member.mention}\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}", Config.COLOR_WARN)
        await ctx.reply(embed=e)
        await log_action(ctx.guild, e)

    @slash.command(name="softban", description="Ban then immediately unban (clears messages).")
    @app_commands.describe(member="Member to softban", reason="Reason")
    @app_commands.default_permissions(ban_members=True)
    async def softban_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        await interaction.response.defer()
        await member.ban(reason=f"Softban — {interaction.user}: {reason}", delete_message_days=7)
        await interaction.guild.unban(member, reason="Softban — removing ban after message wipe")
        e = mod_embed("🧹 Member Softbanned", f"**Member:** {member.mention}\n**Moderator:** {interaction.user.mention}\n**Reason:** {reason}", Config.COLOR_WARN)
        await interaction.followup.send(embed=e)
        await log_action(interaction.guild, e)

    # ── MUTE ──────────────────────────────────────────

    @commands.command(name="mute")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def mute(self, ctx, member: discord.Member, duration: int = 10, *, reason: str = "No reason provided"):
        if duration < 1 or duration > 40320:
            return await ctx.reply("❌ Duration must be between 1 and 40320 minutes (28 days).")
        until = discord.utils.utcnow() + timedelta(minutes=duration)
        await member.timeout(until, reason=f"{ctx.author} — {reason}")
        e = mod_embed("🔇 Member Muted", f"**Member:** {member.mention}\n**Duration:** {duration} minutes\n**Reason:** {reason}", Config.COLOR_WARN)
        await ctx.reply(embed=e)
        await log_action(ctx.guild, e)

    @slash.command(name="mute", description="Timeout a member (Discord native mute).")
    @app_commands.describe(member="Member to mute", duration="Duration in minutes", reason="Reason")
    @app_commands.default_permissions(moderate_members=True)
    async def mute_slash(self, interaction: discord.Interaction, member: discord.Member, duration: int = 10, reason: str = "No reason provided"):
        await interaction.response.defer()
        if duration < 1 or duration > 40320:
            return await interaction.followup.send("❌ Duration must be between 1 and 40320 minutes.", ephemeral=True)
        until = discord.utils.utcnow() + timedelta(minutes=duration)
        await member.timeout(until, reason=f"{interaction.user} — {reason}")
        e = mod_embed("🔇 Member Muted", f"**Member:** {member.mention}\n**Duration:** {duration} minutes\n**Reason:** {reason}", Config.COLOR_WARN)
        await interaction.followup.send(embed=e)
        await log_action(interaction.guild, e)

    # ── UNMUTE ────────────────────────────────────────

    @commands.command(name="unmute")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def unmute(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        await member.timeout(None, reason=f"{ctx.author} — {reason}")
        e = mod_embed("🔊 Member Unmuted", f"**Member:** {member.mention}\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}", Config.COLOR_OK)
        await ctx.reply(embed=e)
        await log_action(ctx.guild, e)

    @slash.command(name="unmute", description="Remove timeout from a member.")
    @app_commands.describe(member="Member to unmute", reason="Reason")
    @app_commands.default_permissions(moderate_members=True)
    async def unmute_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        await interaction.response.defer()
        await member.timeout(None, reason=f"{interaction.user} — {reason}")
        e = mod_embed("🔊 Member Unmuted", f"**Member:** {member.mention}\n**Moderator:** {interaction.user.mention}\n**Reason:** {reason}", Config.COLOR_OK)
        await interaction.followup.send(embed=e)
        await log_action(interaction.guild, e)

    # ── WARN ──────────────────────────────────────────

    @commands.command(name="warn")
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        add_warn(ctx.guild.id, member.id, reason, str(ctx.author))
        warns = get_warns(ctx.guild.id, member.id)
        e = mod_embed("⚠️ Member Warned", f"**Member:** {member.mention}\n**Reason:** {reason}\n**Total Warnings:** {len(warns)}", Config.COLOR_WARN)
        await ctx.reply(embed=e)
        try:
            await member.send(embed=mod_embed("⚠️ Warning Received", f"You received a warning in **{ctx.guild.name}**\n**Reason:** {reason}\n**Total Warnings:** {len(warns)}", Config.COLOR_WARN))
        except Exception:
            pass
        await log_action(ctx.guild, e)

    @slash.command(name="warn", description="Warn a member.")
    @app_commands.describe(member="Member to warn", reason="Reason")
    @app_commands.default_permissions(manage_messages=True)
    async def warn_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        await interaction.response.defer()
        add_warn(interaction.guild.id, member.id, reason, str(interaction.user))
        warns = get_warns(interaction.guild.id, member.id)
        e = mod_embed("⚠️ Member Warned", f"**Member:** {member.mention}\n**Reason:** {reason}\n**Total Warnings:** {len(warns)}", Config.COLOR_WARN)
        await interaction.followup.send(embed=e)
        await log_action(interaction.guild, e)

    # ── WARNINGS ──────────────────────────────────────

    @commands.command(name="warnings")
    @commands.has_permissions(manage_messages=True)
    async def warnings(self, ctx, member: discord.Member):
        warns = get_warns(ctx.guild.id, member.id)
        if not warns:
            return await ctx.reply(f"✅ {member.mention} has no warnings.")
        desc = "\n".join([f"`{i+1}.` {w['reason']} — by {w['mod']} on {w['time'][:10]}" for i, w in enumerate(warns)])
        e = mod_embed(f"⚠️ Warnings for {member}", desc, Config.COLOR_WARN)
        await ctx.reply(embed=e)

    @slash.command(name="warnings", description="View warnings for a member.")
    @app_commands.describe(member="Member to check")
    @app_commands.default_permissions(manage_messages=True)
    async def warnings_slash(self, interaction: discord.Interaction, member: discord.Member):
        warns = get_warns(interaction.guild.id, member.id)
        if not warns:
            return await interaction.response.send_message(f"✅ {member.mention} has no warnings.", ephemeral=True)
        desc = "\n".join([f"`{i+1}.` {w['reason']} — by {w['mod']} on {w['time'][:10]}" for i, w in enumerate(warns)])
        e = mod_embed(f"⚠️ Warnings for {member}", desc, Config.COLOR_WARN)
        await interaction.response.send_message(embed=e)

    # ── CLEARWARNS ────────────────────────────────────

    @commands.command(name="clearwarns")
    @commands.has_permissions(manage_guild=True)
    async def clearwarns(self, ctx, member: discord.Member):
        clear_warns(ctx.guild.id, member.id)
        await ctx.reply(f"✅ Cleared all warnings for {member.mention}.")

    @slash.command(name="clearwarns", description="Clear all warnings for a member.")
    @app_commands.describe(member="Member to clear warnings for")
    @app_commands.default_permissions(manage_guild=True)
    async def clearwarns_slash(self, interaction: discord.Interaction, member: discord.Member):
        clear_warns(interaction.guild.id, member.id)
        await interaction.response.send_message(f"✅ Cleared all warnings for {member.mention}.", ephemeral=True)

    # ── PURGE ─────────────────────────────────────────

        # ── PURGE ─────────────────────────────────────────

    @commands.command(name="purge")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int, member: discord.Member = None):
        if not 1 <= amount <= 500:
            return await ctx.reply("❌ Amount must be between 1 and 500.")
        try:
            await ctx.message.delete()
        except Exception:
            pass
        if member:
            deleted = await ctx.channel.purge(limit=amount, check=lambda m: m.author == member, bulk=True)
        else:
            deleted = await ctx.channel.purge(limit=amount, bulk=True)
        confirm = await ctx.channel.send(f"🗑️ Deleted **{len(deleted)}** messages{f' from {member.mention}' if member else ''}.")
        await asyncio.sleep(5)
        try:
            await confirm.delete()
        except Exception:
            pass

    @slash.command(name="purge", description="Bulk delete messages.")
    @app_commands.describe(amount="Number of messages to delete (1-500)", member="Only delete from this member")
    @app_commands.default_permissions(manage_messages=True)
    async def purge_slash(self, interaction: discord.Interaction, amount: int, member: discord.Member = None):
        if not 1 <= amount <= 500:
            return await interaction.response.send_message("❌ Amount must be between 1 and 500.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        if member:
            check = lambda m: m.author == member
        else:
            check = lambda m: True
        deleted = await interaction.channel.purge(limit=amount, check=check, bulk=True)
        await interaction.followup.send(f"🗑️ Deleted **{len(deleted)}** messages{f' from {member.mention}' if member else ''}.", ephemeral=True)

    # ── SLOWMODE ──────────────────────────────────────

    @commands.command(name="slowmode")
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: int = 0):
        if not 0 <= seconds <= 21600:
            return await ctx.reply("❌ Seconds must be between 0 and 21600.")
        await ctx.channel.edit(slowmode_delay=seconds)
        msg = "⏱️ Slowmode **disabled**." if seconds == 0 else f"⏱️ Slowmode set to **{seconds}s**."
        await ctx.reply(msg)

    @slash.command(name="slowmode", description="Set slowmode delay (0 to disable).")
    @app_commands.describe(seconds="Delay in seconds (0-21600)")
    @app_commands.default_permissions(manage_channels=True)
    async def slowmode_slash(self, interaction: discord.Interaction, seconds: int = 0):
        if not 0 <= seconds <= 21600:
            return await interaction.response.send_message("❌ Seconds must be between 0 and 21600.", ephemeral=True)
        await interaction.channel.edit(slowmode_delay=seconds)
        msg = "⏱️ Slowmode **disabled**." if seconds == 0 else f"⏱️ Slowmode set to **{seconds}s**."
        await interaction.response.send_message(msg)

    # ── LOCK / UNLOCK ─────────────────────────────────

    @commands.command(name="lock")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lock(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        ow = ch.overwrites_for(ctx.guild.default_role)
        ow.send_messages = False
        await ch.edit(overwrites={ctx.guild.default_role: ow})
        await ctx.reply(f"🔒 {ch.mention} has been **locked**.")

    @slash.command(name="lock", description="Lock the current channel.")
    @app_commands.describe(channel="Channel to lock (defaults to current)")
    @app_commands.default_permissions(manage_channels=True)
    async def lock_slash(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        ow = ch.overwrites_for(interaction.guild.default_role)
        ow.send_messages = False
        await ch.edit(overwrites={interaction.guild.default_role: ow})
        await interaction.response.send_message(f"🔒 {ch.mention} has been **locked**.")

    @commands.command(name="unlock")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unlock(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        ow = ch.overwrites_for(ctx.guild.default_role)
        ow.send_messages = None
        await ch.edit(overwrites={ctx.guild.default_role: ow})
        await ctx.reply(f"🔓 {ch.mention} has been **unlocked**.")

    @slash.command(name="unlock", description="Unlock the current channel.")
    @app_commands.describe(channel="Channel to unlock (defaults to current)")
    @app_commands.default_permissions(manage_channels=True)
    async def unlock_slash(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        ow = ch.overwrites_for(interaction.guild.default_role)
        ow.send_messages = None
        await ch.edit(overwrites={interaction.guild.default_role: ow})
        await interaction.response.send_message(f"🔓 {ch.mention} has been **unlocked**.")

    # ── LOCKDOWN ──────────────────────────────────────

    @commands.command(name="lockdown")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lockdown(self, ctx, *, reason: str = "Emergency lockdown"):
        count = 0
        for ch in ctx.guild.text_channels:
            ov = ch.overwrites_for(ctx.guild.default_role)
            ov.send_messages = False
            await ch.edit(overwrites={ctx.guild.default_role: ov})
            count += 1
        e = mod_embed("🔒 SERVER LOCKDOWN", f"**{count}** channels locked.\n**Reason:** {reason}\n**Moderator:** {ctx.author.mention}", Config.COLOR_ERR)
        await ctx.reply(embed=e)
        await log_action(ctx.guild, e)

    @slash.command(name="lockdown", description="Lock ALL channels (emergency use).")
    @app_commands.describe(reason="Reason for lockdown")
    @app_commands.default_permissions(administrator=True)
    async def lockdown_slash(self, interaction: discord.Interaction, reason: str = "Emergency lockdown"):
        await interaction.response.defer()
        count = 0
        for ch in interaction.guild.text_channels:
            ov = ch.overwrites_for(interaction.guild.default_role)
            ov.send_messages = False
            await ch.edit(overwrites={interaction.guild.default_role: ov})
            count += 1
        e = mod_embed("🔒 SERVER LOCKDOWN", f"**{count}** channels locked.\n**Reason:** {reason}\n**Moderator:** {interaction.user.mention}", Config.COLOR_ERR)
        await interaction.followup.send(embed=e)
        await log_action(interaction.guild, e)

    @commands.command(name="unlockdown")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unlockdown(self, ctx):
        count = 0
        for ch in ctx.guild.text_channels:
            ov = ch.overwrites_for(ctx.guild.default_role)
            ov.send_messages = None
            await ch.edit(overwrites={ctx.guild.default_role: ov})
            count += 1
        e = mod_embed("🔓 Lockdown Lifted", f"**{count}** channels unlocked.\n**Moderator:** {ctx.author.mention}", Config.COLOR_OK)
        await ctx.reply(embed=e)
        await log_action(ctx.guild, e)

    @slash.command(name="unlockdown", description="Lift server lockdown.")
    @app_commands.default_permissions(administrator=True)
    async def unlockdown_slash(self, interaction: discord.Interaction):
        await interaction.response.defer()
        count = 0
        for ch in interaction.guild.text_channels:
            ov = ch.overwrites_for(interaction.guild.default_role)
            ov.send_messages = None
            await ch.edit(overwrites={interaction.guild.default_role: ov})
            count += 1
        e = mod_embed("🔓 Lockdown Lifted", f"**{count}** channels unlocked.\n**Moderator:** {interaction.user.mention}", Config.COLOR_OK)
        await interaction.followup.send(embed=e)
        await log_action(interaction.guild, e)

    # ── NICK ──────────────────────────────────────────

    @commands.command(name="nick")
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def nick(self, ctx, member: discord.Member, *, nickname: str = None):
        await member.edit(nick=nickname)
        if nickname:
            await ctx.reply(f"✏️ Changed {member.mention}'s nickname to **{nickname}**.")
        else:
            await ctx.reply(f"✏️ Reset {member.mention}'s nickname.")

    @slash.command(name="nick", description="Change a member's nickname.")
    @app_commands.describe(member="Member to edit", nickname="New nickname (leave empty to reset)")
    @app_commands.default_permissions(manage_nicknames=True)
    async def nick_slash(self, interaction: discord.Interaction, member: discord.Member, nickname: str = None):
        await member.edit(nick=nickname)
        if nickname:
            await interaction.response.send_message(f"✏️ Changed {member.mention}'s nickname to **{nickname}**.")
        else:
            await interaction.response.send_message(f"✏️ Reset {member.mention}'s nickname.")

    # ── ROLE ──────────────────────────────────────────

    @commands.command(name="role")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role(self, ctx, member: discord.Member, role: discord.Role):
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.reply(f"➖ Removed **{role.name}** from {member.mention}.")
        else:
            await member.add_roles(role)
            await ctx.reply(f"➕ Added **{role.name}** to {member.mention}.")

    @slash.command(name="role", description="Add or remove a role from a member.")
    @app_commands.describe(member="Target member", role="Role to add/remove")
    @app_commands.default_permissions(manage_roles=True)
    async def role_slash(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if role in member.roles:
            await member.remove_roles(role)
            await interaction.response.send_message(f"➖ Removed **{role.name}** from {member.mention}.")
        else:
            await member.add_roles(role)
            await interaction.response.send_message(f"➕ Added **{role.name}** to {member.mention}.")

    # ── SETMODLOG ─────────────────────────────────────

    @commands.command(name="setmodlog")
    @commands.has_permissions(administrator=True)
    async def setmodlog(self, ctx, channel: discord.TextChannel):
        data = load("guild_settings.json")
        data.setdefault(str(ctx.guild.id), {})["mod_log_channel"] = channel.id
        save("guild_settings.json", data)
        await ctx.reply(f"✅ Mod log channel set to {channel.mention}.")

    @slash.command(name="setmodlog", description="Set the channel for mod log events.")
    @app_commands.describe(channel="Channel to send mod logs to")
    @app_commands.default_permissions(administrator=True)
    async def setmodlog_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        data = load("guild_settings.json")
        data.setdefault(str(interaction.guild.id), {})["mod_log_channel"] = channel.id
        save("guild_settings.json", data)
        await interaction.response.send_message(f"✅ Mod log channel set to {channel.mention}.", ephemeral=True)

    # ── JAIL SETUP ────────────────────────────────────

    @slash.command(name="setjailrole", description="Set the role assigned when a member is jailed.")
    @app_commands.describe(role="The jail role to assign (should have very limited permissions)")
    @app_commands.default_permissions(administrator=True)
    async def setjailrole(self, interaction: discord.Interaction, role: discord.Role):
        d = _jail_data(interaction.guild.id)
        d.setdefault("config", {})["role"] = role.id
        _save_jail(interaction.guild.id, d)
        await interaction.response.send_message(
            embed=mod_embed("✅ Jail Role Set", f"Jailed members will be assigned {role.mention}.", Config.COLOR_OK),
            ephemeral=True,
        )

    @slash.command(name="setjailchannel", description="Set the channel jailed members are restricted to.")
    @app_commands.describe(channel="The channel jailed members can see and talk in")
    @app_commands.default_permissions(administrator=True)
    async def setjailchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        d = _jail_data(interaction.guild.id)
        d.setdefault("config", {})["channel"] = channel.id
        _save_jail(interaction.guild.id, d)
        await interaction.response.send_message(
            embed=mod_embed("✅ Jail Channel Set", f"Jailed members will be directed to {channel.mention}.", Config.COLOR_OK),
            ephemeral=True,
        )

    # ── JAIL ──────────────────────────────────────────

    @slash.command(name="jail", description="Jail a member — strips all roles and assigns the jail role.")
    @app_commands.describe(member="Member to jail", reason="Reason for jailing")
    @app_commands.default_permissions(administrator=True)
    async def jail(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        guild  = interaction.guild
        invoker = interaction.user

        invoker_has_permission = _has_jail_permission(interaction)

        if not invoker_has_permission:
            target  = guild.get_member(invoker.id)
            reason  = f"Attempted to jail {member.display_name} without sufficient permissions"
            note    = f"⚠️ {invoker.mention} tried to jail {member.mention} but lacks the required role. **They have been jailed instead.**"
        else:
            target = member
            note   = None

        config = _get_jail_config(guild.id)
        if not config.get("role"):
            return await interaction.response.send_message("❌ No jail role set. Use `/moderation setjailrole` first.", ephemeral=True)

        jail_role = guild.get_role(int(config["role"]))
        if not jail_role:
            return await interaction.response.send_message("❌ The configured jail role no longer exists. Please set it again.", ephemeral=True)

        if str(target.id) in _get_jailed(guild.id):
            return await interaction.response.send_message(f"❌ {target.mention} is already jailed.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        roles_to_save = [r.id for r in target.roles if r != guild.default_role and r != jail_role and r.is_assignable()]
        _set_jailed(guild.id, target.id, roles_to_save)

        removable = [r for r in target.roles if r != guild.default_role and r.is_assignable()]
        if removable:
            try:
                await target.remove_roles(*removable, reason=f"Jailed by {invoker} — {reason}")
            except discord.Forbidden:
                pass

        try:
            await target.add_roles(jail_role, reason=f"Jailed by {invoker} — {reason}")
        except discord.Forbidden:
            _remove_jailed(guild.id, target.id)
            return await interaction.followup.send("❌ I don't have permission to assign the jail role.", ephemeral=True)

        jail_ch_id = config.get("channel")
        if jail_ch_id:
            jail_ch = guild.get_channel(int(jail_ch_id))
            if jail_ch:
                try:
                    await jail_ch.send(f"🔒 {target.mention} has been jailed.\n**Reason:** {reason}")
                except Exception:
                    pass

        try:
            await target.send(embed=mod_embed("🔒 You have been Jailed", f"**Server:** {guild.name}\n**Moderator:** {invoker}\n**Reason:** {reason}", Config.COLOR_ERR))
        except Exception:
            pass

        desc = f"**Member:** {target.mention}\n**Moderator:** {invoker.mention}\n**Reason:** {reason}\n**Roles saved:** {len(roles_to_save)}"
        if note:
            desc = note + "\n\n" + desc
        e = mod_embed("🔒 Member Jailed", desc, Config.COLOR_ERR)
        await log_action(guild, e)
        await interaction.followup.send(embed=e, ephemeral=False)

    # ── UNJAIL ────────────────────────────────────────

    @slash.command(name="unjail", description="Release a jailed member and restore their roles.")
    @app_commands.describe(member="Member to unjail", reason="Reason for unjailing")
    @app_commands.default_permissions(administrator=True)
    async def unjail(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        guild   = interaction.guild
        invoker = interaction.user

        if not _has_jail_permission(interaction):
            return await interaction.response.send_message("❌ You don't have permission to unjail members.", ephemeral=True)

        jailed = _get_jailed(guild.id)
        if str(member.id) not in jailed:
            return await interaction.response.send_message(f"❌ {member.mention} is not currently jailed.", ephemeral=True)

        config = _get_jail_config(guild.id)
        if not config.get("role"):
            return await interaction.response.send_message("❌ No jail role configured.", ephemeral=True)

        jail_role = guild.get_role(int(config["role"]))
        await interaction.response.defer(ephemeral=True)

        if jail_role and jail_role in member.roles:
            try:
                await member.remove_roles(jail_role, reason=f"Unjailed by {invoker} — {reason}")
            except discord.Forbidden:
                pass

        saved_ids = jailed[str(member.id)]
        restored = []
        failed = []
        for role_id in saved_ids:
            role = guild.get_role(role_id)
            if role and role.is_assignable():
                try:
                    await member.add_roles(role, reason=f"Unjailed by {invoker} — {reason}")
                    restored.append(role.name)
                except Exception:
                    failed.append(str(role_id))
            else:
                failed.append(str(role_id))

        _remove_jailed(guild.id, member.id)

        try:
            await member.send(embed=mod_embed("🔓 You have been Unjailed", f"**Server:** {guild.name}\n**Moderator:** {invoker}\n**Reason:** {reason}\n**Roles restored:** {len(restored)}", Config.COLOR_OK))
        except Exception:
            pass

        desc = f"**Member:** {member.mention}\n**Moderator:** {invoker.mention}\n**Reason:** {reason}\n**Roles restored:** {len(restored)}"
        if failed:
            desc += f"\n**Could not restore:** {len(failed)} role(s)"
        e = mod_embed("🔓 Member Unjailed", desc, Config.COLOR_OK)
        await log_action(guild, e)
        await interaction.followup.send(embed=e, ephemeral=False)

    # ── JAILLIST ──────────────────────────────────────

    @slash.command(name="jaillist", description="Show all currently jailed members.")
    @app_commands.default_permissions(manage_guild=True)
    async def jaillist(self, interaction: discord.Interaction):
        jailed = _get_jailed(interaction.guild.id)
        if not jailed:
            return await interaction.response.send_message(embed=mod_embed("🔒 Jail List", "No members are currently jailed.", Config.COLOR_INFO), ephemeral=True)
        lines = []
        for uid, roles in jailed.items():
            member = interaction.guild.get_member(int(uid))
            name = member.mention if member else f"`{uid}`"
            lines.append(f"• {name} — {len(roles)} role(s) saved")
        e = mod_embed("🔒 Currently Jailed", "\n".join(lines), Config.COLOR_WARN)
        await interaction.response.send_message(embed=e, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Moderation(bot))