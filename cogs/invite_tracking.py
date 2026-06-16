"""
cogs/invite_tracking.py
Slash group: /invites
Tracks who invited who using Discord invite links.
Also tracks per-member message statistics.
Prefix commands still work with ~

NOTE: This file is a complete structural rewrite of the original.
The original had severe bugs: __init__ defined after listeners,
several commands defined outside the class body, and MSG_FILE/helpers
defined at the bottom of the file. All issues are fixed here.
"""

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone, date
from config import Config
from utils.data import load, save

INV_FILE = "invites.json"
MSG_FILE = "message_stats.json"


# ── Invite data helpers ────────────────────────────────

def _get_guild(guild_id: int) -> dict:
    return load(INV_FILE).get(str(guild_id), {})


def _save_guild(guild_id: int, gd: dict):
    data = load(INV_FILE)
    data[str(guild_id)] = gd
    save(INV_FILE, data)


def _get_user(guild_id: int, user_id: int) -> dict:
    gd = _get_guild(guild_id)
    return gd.get(str(user_id), {
        "total":           0,
        "real":            0,
        "left":            0,
        "fake":            0,
        "invited_by":      None,
        "invited_members": [],
    })


def _save_user(guild_id: int, user_id: int, udata: dict):
    data = load(INV_FILE)
    data.setdefault(str(guild_id), {})[str(user_id)] = udata
    save(INV_FILE, data)


# ── Message stats helpers ──────────────────────────────

def _get_msg(guild_id: int, user_id: int) -> dict:
    data = load(MSG_FILE)
    return data.setdefault(str(guild_id), {}).setdefault(str(user_id), {
        "total": 0, "today": 0, "week": 0, "last_date": None
    })


def _save_msg(guild_id: int, user_id: int, udata: dict):
    data = load(MSG_FILE)
    data.setdefault(str(guild_id), {})[str(user_id)] = udata
    save(MSG_FILE, data)


class InviteTracking(commands.Cog):
    """📨 Invite tracking & message stats system."""

    slash = app_commands.Group(name="invites", description="Invite tracking commands")

    def __init__(self, bot):
        self.bot = bot
        self._invite_cache: dict[int, dict[str, int]] = {}

    # ── Internal helpers ──────────────────────────────

    async def _cache_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self._invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except Exception:
            pass

    # ── Listeners ─────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._cache_invites(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._cache_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild:
            self._invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if invite.guild:
            self._invite_cache.get(invite.guild.id, {}).pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        try:
            new_invites = await guild.invites()
        except Exception:
            return

        old_cache = self._invite_cache.get(guild.id, {})
        inviter   = None
        used_code = None

        for inv in new_invites:
            if inv.uses > old_cache.get(inv.code, 0):
                inviter   = inv.inviter
                used_code = inv.code
                break

        self._invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}

        if inviter and inviter.id != member.id:
            inv_data = _get_user(guild.id, inviter.id)
            inv_data["total"] = inv_data.get("total", 0) + 1
            inv_data["real"]  = inv_data.get("real", 0) + 1
            inv_data.setdefault("invited_members", []).append({
                "id":     member.id,
                "name":   str(member),
                "joined": datetime.now(timezone.utc).isoformat(),
                "left":   False,
            })
            _save_user(guild.id, inviter.id, inv_data)

            mem_data = _get_user(guild.id, member.id)
            mem_data["invited_by"] = inviter.id
            _save_user(guild.id, member.id, mem_data)

            settings = load("guild_settings.json").get(str(guild.id), {})
            log_id   = settings.get("invite_log_channel")
            if log_id:
                ch = guild.get_channel(int(log_id))
                if ch:
                    e = discord.Embed(
                        title="📨 Member Joined",
                        description=(
                            f"**{member.mention}** joined using invite `{used_code}` by {inviter.mention}\n"
                            f"{inviter.mention} now has **{inv_data['real']}** invite(s)."
                        ),
                        color=Config.COLOR_OK,
                        timestamp=datetime.now(timezone.utc)
                    )
                    e.set_thumbnail(url=member.display_avatar.url)
                    await ch.send(embed=e)
        else:
            mem_data = _get_user(guild.id, member.id)
            mem_data["invited_by"] = None
            _save_user(guild.id, member.id, mem_data)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild    = member.guild
        mem_data = _get_user(guild.id, member.id)
        inviter_id = mem_data.get("invited_by")

        if inviter_id:
            inv_data         = _get_user(guild.id, inviter_id)
            inv_data["left"] = inv_data.get("left", 0) + 1
            inv_data["real"] = max(0, inv_data.get("real", 0) - 1)
            for m in inv_data.get("invited_members", []):
                if m["id"] == member.id:
                    m["left"] = True
                    break
            _save_user(guild.id, inviter_id, inv_data)

            settings = load("guild_settings.json").get(str(guild.id), {})
            log_id   = settings.get("invite_log_channel")
            if log_id:
                inviter = guild.get_member(inviter_id)
                ch      = guild.get_channel(int(log_id))
                if ch:
                    inv_mention = inviter.mention if inviter else f"<@{inviter_id}>"
                    e = discord.Embed(
                        title="📤 Invited Member Left",
                        description=(
                            f"**{member}** (invited by {inv_mention}) has left.\n"
                            f"{inv_mention} now has **{inv_data['real']}** invite(s)."
                        ),
                        color=Config.COLOR_ERR,
                        timestamp=datetime.now(timezone.utc)
                    )
                    await ch.send(embed=e)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        today = str(date.today())
        udata = _get_msg(message.guild.id, message.author.id)
        if udata.get("last_date") != today:
            udata["today"] = 0
            if date.today().weekday() == 0:
                udata["week"] = 0
        udata["total"]     = udata.get("total", 0) + 1
        udata["today"]     = udata.get("today", 0) + 1
        udata["week"]      = udata.get("week", 0) + 1
        udata["last_date"] = today
        _save_msg(message.guild.id, message.author.id, udata)

    # ── INVITES ───────────────────────────────────────

    @commands.command(name="invites")
    async def invites(self, ctx, member: discord.Member = None):
        m     = member or ctx.author
        udata = _get_user(ctx.guild.id, m.id)

        real       = udata.get("real", 0)
        total      = udata.get("total", 0)
        left       = udata.get("left", 0)
        invited_by = udata.get("invited_by")
        inv_mention = f"<@{invited_by}>" if invited_by else "Unknown / Vanity URL"

        e = discord.Embed(title=f"📨 {m.display_name}'s Invites", color=Config.COLOR_INFO, timestamp=datetime.now(timezone.utc))
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name="✅ Active Invites", value=f"**{real}**")
        e.add_field(name="👥 Total Invited",  value=f"**{total}**")
        e.add_field(name="📤 Members Left",   value=f"**{left}**")
        e.add_field(name="🤝 Invited By",     value=inv_mention, inline=False)

        invited = udata.get("invited_members", [])
        if invited:
            lines = [f"<@{x['id']}>{' **(left)**' if x.get('left') else ''}" for x in invited]
            value = "\n".join(lines)
            if len(value) > 1024:
                value = value[:1020] + "\n..."
            e.add_field(name="📋 Invited Members", value=value, inline=False)
        await ctx.reply(embed=e)

    @slash.command(name="check", description="Check invite stats for a member.")
    @app_commands.describe(member="Member to check (leave empty for yourself)")
    async def invites_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.invites.callback(self, ctx, member)

    # ── INVITESTATS ───────────────────────────────────

    @commands.command(name="invitestats")
    async def invitestats(self, ctx):
        gd = _get_guild(ctx.guild.id)
        if not gd:
            return await ctx.reply("No invite data yet. Members need to join using invite links first!")
        ranked = sorted(
            ((uid, udata.get("real", 0), udata.get("total", 0)) for uid, udata in gd.items()),
            key=lambda x: x[1], reverse=True
        )[:10]
        medals = ["🥇","🥈","🥉"] + [f"`{i}.`" for i in range(4, 11)]
        lines = []
        for i, (uid, real, total) in enumerate(ranked):
            member = ctx.guild.get_member(int(uid))
            name   = member.display_name if member else f"<@{uid}>"
            lines.append(f"{medals[i]} **{name}** — **{real}** active ({total} total)")
        e = discord.Embed(
            title=f"📨 {ctx.guild.name} — Invite Leaderboard",
            description="\n".join(lines) or "No data.",
            color=Config.COLOR_GOLD
        )
        if ctx.guild.icon:
            e.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.reply(embed=e)

    @slash.command(name="leaderboard", description="Show the invite leaderboard.")
    async def invitestats_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.invitestats.callback(self, ctx)

    # ── INVITEINFO ────────────────────────────────────

    @commands.command(name="inviteinfo")
    async def inviteinfo(self, ctx, code: str):
        try:
            invite = await self.bot.fetch_invite(code, with_counts=True)
        except discord.NotFound:
            return await ctx.reply("❌ Invite not found or invalid.")
        e = discord.Embed(title=f"🔗 Invite Info — {code}", color=Config.COLOR_INFO, timestamp=datetime.now(timezone.utc))
        e.add_field(name="Code",            value=f"`{invite.code}`")
        e.add_field(name="Guild",           value=invite.guild.name if invite.guild else "Unknown")
        e.add_field(name="Inviter",         value=str(invite.inviter) if invite.inviter else "Unknown")
        e.add_field(name="Channel",         value=f"#{invite.channel}" if invite.channel else "Unknown")
        e.add_field(name="Uses",            value=invite.uses if invite.uses is not None else "Unknown")
        e.add_field(name="Max Uses",        value=invite.max_uses or "∞")
        e.add_field(name="Expires",         value=discord.utils.format_dt(invite.expires_at, "R") if invite.expires_at else "Never")
        e.add_field(name="Approx Members",  value=invite.approximate_member_count or "Unknown")
        await ctx.reply(embed=e)

    @slash.command(name="info", description="Show info about a Discord invite code.")
    @app_commands.describe(code="Invite code (without discord.gg/)")
    async def inviteinfo_slash(self, interaction: discord.Interaction, code: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.inviteinfo.callback(self, ctx, code)

    # ── INVITEDMEMBERS ────────────────────────────────

    @commands.command(name="invitedmembers")
    async def invitedmembers(self, ctx, member: discord.Member = None):
        m       = member or ctx.author
        udata   = _get_user(ctx.guild.id, m.id)
        invited = udata.get("invited_members", [])

        if not invited:
            return await ctx.reply(f"**{m.display_name}** hasn't invited anyone yet.")

        per_page = 20
        chunks   = [invited[i:i + per_page] for i in range(0, len(invited), per_page)]
        pages    = []
        for chunk in chunks:
            lines = [f"<@{x['id']}>{' **(left)**' if x.get('left') else ''}" for x in chunk]
            e = discord.Embed(
                title=f"📋 Members Invited by {m.display_name}",
                description="\n".join(lines),
                color=Config.COLOR_INFO,
                timestamp=datetime.now(timezone.utc)
            )
            e.set_thumbnail(url=m.display_avatar.url)
            still_here = sum(1 for x in invited if not x.get("left"))
            left_count = sum(1 for x in invited if x.get("left"))
            e.set_footer(text=f"{len(invited)} total • {still_here} still here • {left_count} left")
            pages.append(e)

        if len(pages) == 1:
            return await ctx.reply(embed=pages[0])

        current = 0

        class NavView(discord.ui.View):
            def __init__(self_inner):
                super().__init__(timeout=60)

            @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
            async def prev(self_inner, interaction: discord.Interaction, button: discord.ui.Button):
                nonlocal current
                if interaction.user != ctx.author:
                    return await interaction.response.defer()
                current = (current - 1) % len(pages)
                await interaction.response.edit_message(embed=pages[current])

            @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
            async def next(self_inner, interaction: discord.Interaction, button: discord.ui.Button):
                nonlocal current
                if interaction.user != ctx.author:
                    return await interaction.response.defer()
                current = (current + 1) % len(pages)
                await interaction.response.edit_message(embed=pages[current])

        for i, p in enumerate(pages):
            still_here = sum(1 for x in invited if not x.get("left"))
            left_count = sum(1 for x in invited if x.get("left"))
            p.set_footer(text=f"Page {i+1}/{len(pages)} • {len(invited)} total • {still_here} still here • {left_count} left")

        await ctx.reply(embed=pages[0], view=NavView())

    @slash.command(name="members", description="View all members invited by a user.")
    @app_commands.describe(member="Member to check (leave empty for yourself)")
    async def invitedmembers_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.invitedmembers.callback(self, ctx, member)

    # ── RESETINVITES ──────────────────────────────────

    @commands.command(name="resetinvites")
    @commands.has_permissions(administrator=True)
    async def resetinvites(self, ctx, member: discord.Member):
        data = load(INV_FILE)
        gd   = data.get(str(ctx.guild.id), {})
        if str(member.id) in gd:
            gd[str(member.id)] = {
                "total":           0,
                "real":            0,
                "left":            0,
                "fake":            0,
                "invited_by":      gd[str(member.id)].get("invited_by"),
                "invited_members": [],
            }
            data[str(ctx.guild.id)] = gd
            save(INV_FILE, data)
        await ctx.reply(f"✅ Reset invite count for {member.mention}.")

    @slash.command(name="reset", description="Reset a member's invite count.")
    @app_commands.describe(member="Member to reset")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def resetinvites_slash(self, interaction: discord.Interaction, member: discord.Member):
        ctx = await commands.Context.from_interaction(interaction)
        await self.resetinvites.callback(self, ctx, member)

    # ── SETINVITELOG ──────────────────────────────────

    @commands.command(name="setinvitelog")
    @commands.has_permissions(administrator=True)
    async def setinvitelog(self, ctx, channel: discord.TextChannel):
        data = load("guild_settings.json")
        data.setdefault(str(ctx.guild.id), {})["invite_log_channel"] = channel.id
        save("guild_settings.json", data)
        await ctx.reply(f"✅ Invite logs will be sent to {channel.mention}.")

    @slash.command(name="setlogchannel", description="Set the invite log channel.")
    @app_commands.describe(channel="Channel for invite logs")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def setinvitelog_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        ctx = await commands.Context.from_interaction(interaction)
        await self.setinvitelog.callback(self, ctx, channel)

    # ── MESSAGE STATS ─────────────────────────────────

    @commands.command(name="messagestats")
    async def messagestats(self, ctx, member: discord.Member = None):
        """View message stats for yourself or another member."""
        m     = member or ctx.author
        udata = _get_msg(ctx.guild.id, m.id)
        e = discord.Embed(title=f"💬 {m.display_name}'s Message Stats", color=Config.COLOR_INFO)
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name="📊 Total Messages", value=f"**{udata.get('total', 0):,}**")
        e.add_field(name="📅 Today",          value=f"**{udata.get('today', 0):,}**")
        e.add_field(name="📆 This Week",      value=f"**{udata.get('week', 0):,}**")
        await ctx.reply(embed=e)

    @slash.command(name="messagestats", description="View message statistics for a member.")
    @app_commands.describe(member="Member to check (leave empty for yourself)")
    async def messagestats_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.messagestats.callback(self, ctx, member)

    @commands.command(name="msgleaderboard")
    async def msgleaderboard(self, ctx, period: str = "total"):
        """Show the message leaderboard. Periods: total, today, week"""
        period = period.lower()
        if period not in ("total", "today", "week"):
            return await ctx.reply("❌ Period must be `total`, `today`, or `week`.")
        data = load(MSG_FILE).get(str(ctx.guild.id), {})
        if not data:
            return await ctx.reply("No message data yet!")
        ranked = sorted(data.items(), key=lambda x: x[1].get(period, 0), reverse=True)[:10]
        medals = ["🥇","🥈","🥉"] + [f"`{i}.`" for i in range(4, 11)]
        lines  = []
        for i, (uid, udata) in enumerate(ranked):
            member = ctx.guild.get_member(int(uid))
            name   = member.display_name if member else f"<@{uid}>"
            count  = udata.get(period, 0)
            lines.append(f"{medals[i]} **{name}** — `{count:,}` messages")
        period_label = {"total": "All Time", "today": "Today", "week": "This Week"}[period]
        e = discord.Embed(
            title=f"💬 {ctx.guild.name} — Message Leaderboard ({period_label})",
            description="\n".join(lines) or "No data.",
            color=Config.COLOR_GOLD
        )
        if ctx.guild.icon:
            e.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.reply(embed=e)

    @slash.command(name="msgleaderboard", description="Show the message leaderboard.")
    @app_commands.describe(period="Period: total, today, or week")
    @app_commands.choices(period=[
        app_commands.Choice(name="All Time", value="total"),
        app_commands.Choice(name="Today",    value="today"),
        app_commands.Choice(name="This Week", value="week"),
    ])
    async def msgleaderboard_slash(self, interaction: discord.Interaction, period: str = "total"):
        ctx = await commands.Context.from_interaction(interaction)
        await self.msgleaderboard.callback(self, ctx, period)

    @commands.command(name="msgreset")
    @commands.has_permissions(administrator=True)
    async def msgreset(self, ctx, member: discord.Member):
        """Reset a member's message stats."""
        data = load(MSG_FILE)
        gd   = data.get(str(ctx.guild.id), {})
        if str(member.id) in gd:
            del gd[str(member.id)]
            data[str(ctx.guild.id)] = gd
            save(MSG_FILE, data)
        await ctx.reply(f"✅ Reset message stats for {member.mention}.")

    @commands.command(name="msgstatsserver")
    async def msgstatsserver(self, ctx):
        """Show overall server message statistics."""
        data = load(MSG_FILE).get(str(ctx.guild.id), {})
        if not data:
            return await ctx.reply("No message data yet!")
        total_msgs = sum(u.get("total", 0) for u in data.values())
        today_msgs = sum(u.get("today", 0) for u in data.values())
        week_msgs  = sum(u.get("week", 0)  for u in data.values())
        top_user   = max(data.items(), key=lambda x: x[1].get("total", 0), default=None)
        e = discord.Embed(title=f"💬 {ctx.guild.name} — Server Message Stats", color=Config.COLOR_INFO)
        e.add_field(name="📊 Total Messages",  value=f"**{total_msgs:,}**")
        e.add_field(name="📅 Today",           value=f"**{today_msgs:,}**")
        e.add_field(name="📆 This Week",       value=f"**{week_msgs:,}**")
        e.add_field(name="👥 Tracked Members", value=f"**{len(data):,}**")
        if top_user:
            member = ctx.guild.get_member(int(top_user[0]))
            name   = member.display_name if member else f"<@{top_user[0]}>"
            e.add_field(name="🏆 Most Active", value=f"**{name}** ({top_user[1].get('total', 0):,} msgs)", inline=False)
        if ctx.guild.icon:
            e.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.reply(embed=e)


async def setup(bot):
    await bot.add_cog(InviteTracking(bot))
