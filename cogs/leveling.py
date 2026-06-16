"""
cogs/leveling.py
Slash group: /leveling
Prefix commands still work with ~
"""

import discord
from discord.ext import commands
from discord import app_commands
import random
import math
import time
from datetime import datetime, timezone
from config import Config
from utils.data import load, save

XP_FILE = "levels.json"


def xp_for_level(level: int) -> int:
    return 5 * (level ** 2) + 50 * level + 100


def level_from_xp(total_xp: int) -> tuple[int, int, int]:
    level = 0
    xp = total_xp
    while xp >= xp_for_level(level):
        xp -= xp_for_level(level)
        level += 1
    return level, xp, xp_for_level(level)


def _get(guild_id: int, user_id: int) -> dict:
    data = load(XP_FILE)
    gk, uk = str(guild_id), str(user_id)
    data.setdefault(gk, {}).setdefault(uk, {"xp": 0, "level": 0, "total_xp": 0})
    return data[gk][uk]


def _save_xp(guild_id: int, user_id: int, user: dict):
    data = load(XP_FILE)
    data.setdefault(str(guild_id), {})[str(user_id)] = user
    save(XP_FILE, data)


def _guild_settings(guild_id: int) -> dict:
    return load("guild_settings.json").get(str(guild_id), {})


def _save_guild_settings(guild_id: int, gd: dict):
    data = load("guild_settings.json")
    data[str(guild_id)] = gd
    save("guild_settings.json", data)


def progress_bar(current: int, total: int, length: int = 20) -> str:
    filled = int((current / total) * length) if total else 0
    return "█" * filled + "░" * (length - filled)


class Leveling(commands.Cog):
    """⭐ XP & level system."""

    slash = app_commands.Group(name="leveling", description="XP and leveling commands")

    def __init__(self, bot):
        self.bot = bot
        self._cooldowns: dict[str, float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        settings = _guild_settings(message.guild.id)
        if message.channel.id in settings.get("xp_blacklist", []):
            return
        key = f"{message.guild.id}:{message.author.id}"
        now = time.time()
        if now - self._cooldowns.get(key, 0) < Config.XP_COOLDOWN_SECONDS:
            return
        self._cooldowns[key] = now
        xp_gain = random.randint(Config.XP_PER_MESSAGE_MIN, Config.XP_PER_MESSAGE_MAX)
        u = _get(message.guild.id, message.author.id)
        old_level = level_from_xp(u["total_xp"])[0]
        u["total_xp"] += xp_gain
        level, rem, needed = level_from_xp(u["total_xp"])
        u["level"] = level
        u["xp"] = rem
        _save_xp(message.guild.id, message.author.id, u)
        if level > old_level:
            lvl_ch_id = settings.get("level_channel")
            if lvl_ch_id:
                ch = message.guild.get_channel(int(lvl_ch_id)) or message.channel
            else:
                ch = message.channel
            e = discord.Embed(title="⬆️ Level Up!", description=f"🎉 You reached **Level {level}**!", color=Config.COLOR_GOLD)
            e.set_thumbnail(url=message.author.display_avatar.url)
            await ch.send(content=message.author.mention, embed=e)
            role_map = settings.get("level_roles", {})
            for lvl in range(old_level + 1, level + 1):
                role_id = role_map.get(str(lvl))
                if role_id:
                    role = message.guild.get_role(int(role_id))
                    if role and role not in message.author.roles:
                        try:
                            await message.author.add_roles(role, reason=f"Level {lvl} reward")
                        except Exception:
                            pass

    # ── RANK ──────────────────────────────────────────

    @commands.command(name="rank")
    async def rank(self, ctx, member: discord.Member = None):
        m = member or ctx.author
        u = _get(ctx.guild.id, m.id)
        level, rem, needed = level_from_xp(u["total_xp"])
        data = load(XP_FILE).get(str(ctx.guild.id), {})
        sorted_users = sorted(data.items(), key=lambda x: x[1].get("total_xp", 0), reverse=True)
        rank_pos = next((i + 1 for i, (uid, _) in enumerate(sorted_users) if uid == str(m.id)), "?")
        bar = progress_bar(rem, needed)
        e = discord.Embed(color=m.color or Config.COLOR_GOLD)
        e.set_author(name=str(m), icon_url=m.display_avatar.url)
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name="🏅 Level",    value=f"**{level}**")
        e.add_field(name="🏆 Rank",     value=f"**#{rank_pos}**")
        e.add_field(name="⭐ Total XP", value=f"**{u['total_xp']:,}**")
        e.add_field(name=f"Progress ({rem:,} / {needed:,} XP)", value=f"`{bar}` {int(rem / needed * 100) if needed else 0}%", inline=False)
        e.set_footer(text="OmniBot Levels")
        await ctx.reply(embed=e)

    @slash.command(name="rank", description="View your or another member's rank card.")
    @app_commands.describe(member="Member to check (leave empty for yourself)")
    async def rank_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.rank.callback(self, ctx, member)

    # ── LEADERBOARD ───────────────────────────────────

    @commands.command(name="levels", aliases=["xplb", "xpleaderboard", "levellb"])
    async def levels(self, ctx, page: int = 1):
        data = load(XP_FILE).get(str(ctx.guild.id), {})
        if not data:
            return await ctx.reply("No XP data yet. Start chatting to earn XP!")
        sorted_users = sorted(data.items(), key=lambda x: x[1].get("total_xp", 0), reverse=True)
        per_page     = 10
        total_pages  = max(1, math.ceil(len(sorted_users) / per_page))
        page         = max(1, min(page, total_pages))
        start        = (page - 1) * per_page
        chunk        = sorted_users[start:start + per_page]
        medals       = ["🥇","🥈","🥉"] + [f"`{i}.`" for i in range(4, 11)]
        lines = []
        for i, (uid, udata) in enumerate(chunk, start=start):
            member = ctx.guild.get_member(int(uid))
            name   = member.display_name if member else f"<@{uid}>"
            lvl, _, _ = level_from_xp(udata.get("total_xp", 0))
            medal  = medals[i - start] if i - start < 3 else f"`{i + 1}.`"
            lines.append(f"{medal} **{name}** — Level **{lvl}** | `{udata.get('total_xp', 0):,}` XP")
        e = discord.Embed(title=f"⭐ {ctx.guild.name} — XP Leaderboard", description="\n".join(lines) or "No data.", color=Config.COLOR_GOLD)
        user_rank = next((i + 1 for i, (uid, _) in enumerate(sorted_users) if uid == str(ctx.author.id)), None)
        if user_rank:
            user_xp   = data.get(str(ctx.author.id), {}).get("total_xp", 0)
            user_lvl, _, _ = level_from_xp(user_xp)
            e.set_footer(text=f"Your rank: #{user_rank} | Level {user_lvl} | {user_xp:,} XP — Page {page}/{total_pages}")
        else:
            e.set_footer(text=f"Page {page}/{total_pages} — Start chatting to earn XP!")
        if ctx.guild.icon:
            e.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.reply(embed=e)

    @slash.command(name="leaderboard", description="Show the XP leaderboard.")
    @app_commands.describe(page="Page number")
    async def levels_slash(self, interaction: discord.Interaction, page: int = 1):
        ctx = await commands.Context.from_interaction(interaction)
        await self.levels.callback(self, ctx, page)

    # ── SETLEVELCHANNEL ───────────────────────────────

    @commands.command(name="setlevelchannel")
    @commands.has_permissions(administrator=True)
    async def setlevelchannel(self, ctx, channel: discord.TextChannel):
        data = load("guild_settings.json")
        data.setdefault(str(ctx.guild.id), {})["level_channel"] = channel.id
        save("guild_settings.json", data)
        await ctx.reply(f"✅ Level-up messages will now be sent to {channel.mention}.")

    @slash.command(name="setlevelchannel", description="Set the channel where level-up messages are sent.")
    @app_commands.describe(channel="Channel for level-up notifications")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def setlevelchannel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        ctx = await commands.Context.from_interaction(interaction)
        await self.setlevelchannel.callback(self, ctx, channel)

    # ── RESETLEVELCHANNEL ─────────────────────────────

    @commands.command(name="resetlevelchannel")
    @commands.has_permissions(administrator=True)
    async def resetlevelchannel(self, ctx):
        data = load("guild_settings.json")
        data.setdefault(str(ctx.guild.id), {}).pop("level_channel", None)
        save("guild_settings.json", data)
        await ctx.reply("✅ Level-up messages will now appear in the channel where the message was sent.")

    @slash.command(name="resetlevelchannel", description="Reset level-up messages to show in place.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def resetlevelchannel_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.resetlevelchannel.callback(self, ctx)

    # ── SETXP ─────────────────────────────────────────

    @commands.command(name="setxp")
    @commands.has_permissions(administrator=True)
    async def setxp(self, ctx, member: discord.Member, xp: int):
        u = _get(ctx.guild.id, member.id)
        u["total_xp"] = max(0, xp)
        level, rem, needed = level_from_xp(u["total_xp"])
        u["level"] = level
        u["xp"] = rem
        _save_xp(ctx.guild.id, member.id, u)
        await ctx.reply(f"✅ Set {member.mention}'s XP to **{xp:,}** (Level {level}).")

    @slash.command(name="setxp", description="Set a user's total XP.")
    @app_commands.describe(member="Target member", xp="Total XP to set")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def setxp_slash(self, interaction: discord.Interaction, member: discord.Member, xp: int):
        ctx = await commands.Context.from_interaction(interaction)
        await self.setxp.callback(self, ctx, member, xp)

    # ── LEVELROLE ─────────────────────────────────────

    @commands.command(name="levelrole")
    @commands.has_permissions(administrator=True)
    async def levelrole(self, ctx, level: int, role: discord.Role):
        data = load("guild_settings.json")
        gd = data.setdefault(str(ctx.guild.id), {})
        gd.setdefault("level_roles", {})[str(level)] = role.id
        save("guild_settings.json", data)
        await ctx.reply(f"✅ Members who reach Level **{level}** will receive {role.mention}.")

    @slash.command(name="levelrole", description="Assign a role reward for reaching a level.")
    @app_commands.describe(level="Level that triggers the reward", role="Role to award")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def levelrole_slash(self, interaction: discord.Interaction, level: int, role: discord.Role):
        ctx = await commands.Context.from_interaction(interaction)
        await self.levelrole.callback(self, ctx, level, role)

    # ── REMOVELEVELROLE ───────────────────────────────

    @commands.command(name="removelevelrole")
    @commands.has_permissions(administrator=True)
    async def removelevelrole(self, ctx, level: int):
        data = load("guild_settings.json")
        role_map = data.setdefault(str(ctx.guild.id), {}).get("level_roles", {})
        if str(level) not in role_map:
            return await ctx.reply(f"❌ No role reward is set for Level {level}.")
        removed_id = role_map.pop(str(level))
        save("guild_settings.json", data)
        role = ctx.guild.get_role(int(removed_id))
        await ctx.reply(f"✅ Removed {role.mention if role else f'<@&{removed_id}>'} as the Level {level} reward.")

    @slash.command(name="removelevelrole", description="Remove a level role reward.")
    @app_commands.describe(level="Level whose reward to remove")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def removelevelrole_slash(self, interaction: discord.Interaction, level: int):
        ctx = await commands.Context.from_interaction(interaction)
        await self.removelevelrole.callback(self, ctx, level)

    # ── LEVELROLES ────────────────────────────────────

    @commands.command(name="levelroles")
    async def levelroles(self, ctx):
        settings = _guild_settings(ctx.guild.id)
        role_map = settings.get("level_roles", {})
        if not role_map:
            return await ctx.reply("No level role rewards configured. Use `~levelrole` to add some.")
        lines = []
        for lvl, role_id in sorted(role_map.items(), key=lambda x: int(x[0])):
            role = ctx.guild.get_role(int(role_id))
            lines.append(f"Level **{lvl}** → {role.mention if role else f'<@&{role_id}> *(deleted)*'}")
        e = discord.Embed(title="🎖️ Level Role Rewards", description="\n".join(lines), color=Config.COLOR_GOLD)
        await ctx.reply(embed=e)

    @slash.command(name="levelroles", description="List all configured level role rewards.")
    async def levelroles_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.levelroles.callback(self, ctx)

    # ── XPBLACKLIST ───────────────────────────────────

    @commands.command(name="xpblacklist")
    @commands.has_permissions(administrator=True)
    async def xpblacklist(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        data = load("guild_settings.json")
        gd = data.setdefault(str(ctx.guild.id), {})
        bl = gd.setdefault("xp_blacklist", [])
        if ch.id in bl:
            bl.remove(ch.id)
            msg = f"✅ XP gain **enabled** in {ch.mention}."
        else:
            bl.append(ch.id)
            msg = f"🚫 XP gain **disabled** in {ch.mention}."
        save("guild_settings.json", data)
        await ctx.reply(msg)

    @slash.command(name="xpblacklist", description="Toggle XP gain on/off in a channel.")
    @app_commands.describe(channel="Channel to toggle (defaults to current)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def xpblacklist_slash(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.xpblacklist.callback(self, ctx, channel)


async def setup(bot):
    await bot.add_cog(Leveling(bot))
