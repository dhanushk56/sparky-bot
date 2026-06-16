"""
cogs/giveaway.py
Slash group: /giveaway
Prefix commands still work with ~
"""

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random
from datetime import datetime, timezone, timedelta
from config import Config
from utils.data import load, save

GW_FILE = "giveaways.json"


def _parse_time(s: str):
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    unit = s[-1].lower()
    if unit not in units or not s[:-1].isdigit():
        return None
    return int(s[:-1]) * units[unit]


def gw_embed(prize, ends_at, winners, host, entries=0):
    e = discord.Embed(
        title=f"🎉 {prize}",
        description=(
            f"React with {Config.GIVEAWAY_EMOJI} to enter!\n\n"
            f"**Ends:** {discord.utils.format_dt(ends_at, 'R')}\n"
            f"**Winners:** {winners}\n"
            f"**Hosted by:** {host.mention}\n"
            f"**Entries:** {entries}"
        ),
        color=Config.COLOR_GOLD,
        timestamp=ends_at
    )
    e.set_footer(text="Ends at")
    return e


async def _end_giveaway(bot, guild_id, channel_id, message_id):
    data = load(GW_FILE)
    gw = data.get(str(guild_id), {}).get(str(message_id))
    if not gw or gw.get("ended"):
        return
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    channel = guild.get_channel(channel_id)
    if not channel:
        return
    try:
        msg = await channel.fetch_message(message_id)
    except Exception:
        return
    reaction = discord.utils.get(msg.reactions, emoji=Config.GIVEAWAY_EMOJI)
    users = [u async for u in reaction.users() if not u.bot] if reaction else []
    prize = gw.get("prize", "Mystery Prize")
    host_id = gw.get("host_id")
    num_winners = gw.get("winners", 1)
    winner_mentions = "No valid entries"
    if not users:
        await channel.send(f"🎉 Giveaway for **{prize}** ended with no valid entries.")
    else:
        winners = random.sample(users, min(num_winners, len(users)))
        winner_mentions = ", ".join(w.mention for w in winners)
        e = discord.Embed(
            title=f"🎉 Giveaway Ended — {prize}",
            description=f"**Winner(s):** {winner_mentions}\n**Hosted by:** <@{host_id}>",
            color=Config.COLOR_OK
        )
        await channel.send(embed=e)
        await channel.send(f"🎊 Congratulations {winner_mentions}! You won **{prize}**!")
        gw["winner_ids"] = [w.id for w in winners]
    gw["ended"] = True
    data[str(guild_id)][str(message_id)] = gw
    save(GW_FILE, data)
    try:
        ended_e = discord.Embed(
            title=f"🎉 {prize} — ENDED",
            description=f"**Winners:** {winner_mentions}\n**Entries:** {len(users)}",
            color=Config.COLOR_ERR
        )
        await msg.edit(embed=ended_e)
    except Exception:
        pass


class Giveaway(commands.Cog):
    """🎉 Giveaway system."""

    slash = app_commands.Group(name="giveaway", description="Giveaway management commands")

    def __init__(self, bot):
        self.bot = bot
        self._running = {}
        bot.loop.create_task(self._resume_giveaways())

    async def _resume_giveaways(self):
        await self.bot.wait_until_ready()
        data = load(GW_FILE)
        now = datetime.now(timezone.utc)
        for guild_id_str, giveaways in data.items():
            for msg_id_str, gw in giveaways.items():
                if gw.get("ended"):
                    continue
                ends_at = datetime.fromisoformat(gw["ends_at"])
                delay = (ends_at - now).total_seconds()
                if delay <= 0:
                    await _end_giveaway(self.bot, int(guild_id_str), gw["channel_id"], int(msg_id_str))
                else:
                    task = self.bot.loop.create_task(self._timer(int(guild_id_str), gw["channel_id"], int(msg_id_str), delay))
                    self._running[int(msg_id_str)] = task

    async def _timer(self, guild_id, channel_id, message_id, delay):
        await asyncio.sleep(delay)
        await _end_giveaway(self.bot, guild_id, channel_id, message_id)

    # ── GSTART ────────────────────────────────────────

    @commands.command(name="gstart")
    @commands.has_permissions(manage_guild=True)
    async def gstart(self, ctx, duration: str, winners: int = 1, *, prize: str):
        await self._do_gstart(ctx, duration, winners, prize)

    @slash.command(name="start", description="Start a giveaway.")
    @app_commands.describe(duration="Duration e.g. 30m, 2h, 1d", prize="Prize to give away", winners="Number of winners")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def gstart_slash(self, interaction: discord.Interaction, duration: str, prize: str, winners: int = 1):
        await interaction.response.defer(ephemeral=True)
        ctx = await commands.Context.from_interaction(interaction)
        await self._do_gstart(ctx, duration, winners, prize)

    async def _do_gstart(self, ctx, duration, winners, prize):
        seconds = _parse_time(duration)
        if not seconds:
            return await ctx.reply("❌ Invalid duration. Use `30m`, `2h`, `1d` etc.")
        if winners < 1 or winners > 20:
            return await ctx.reply("❌ Winners must be between 1 and 20.")
        ends_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        e = gw_embed(prize, ends_at, winners, ctx.author)
        msg = await ctx.channel.send(embed=e)
        await msg.add_reaction(Config.GIVEAWAY_EMOJI)
        data = load(GW_FILE)
        data.setdefault(str(ctx.guild.id), {})[str(msg.id)] = {
            "prize": prize, "winners": winners, "host_id": ctx.author.id,
            "channel_id": ctx.channel.id, "ends_at": ends_at.isoformat(),
            "ended": False, "winner_ids": [],
        }
        save(GW_FILE, data)
        task = self.bot.loop.create_task(self._timer(ctx.guild.id, ctx.channel.id, msg.id, seconds))
        self._running[msg.id] = task
        await ctx.reply("🎉 Giveaway started!", delete_after=5)

    # ── GEND ──────────────────────────────────────────

    @commands.command(name="gend")
    @commands.has_permissions(manage_guild=True)
    async def gend(self, ctx, message_id: str):
        await self._do_gend(ctx, message_id)

    @slash.command(name="end", description="End a giveaway early by message ID.")
    @app_commands.describe(message_id="The message ID of the giveaway")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def gend_slash(self, interaction: discord.Interaction, message_id: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self._do_gend(ctx, message_id)

    async def _do_gend(self, ctx, message_id):
        mid = int(message_id)
        task = self._running.pop(mid, None)
        if task:
            task.cancel()
        data = load(GW_FILE)
        gw = data.get(str(ctx.guild.id), {}).get(str(mid))
        if not gw:
            return await ctx.reply("❌ Giveaway not found.")
        await _end_giveaway(self.bot, ctx.guild.id, gw["channel_id"], mid)
        await ctx.reply("✅ Giveaway ended.")

    # ── GREROLL ───────────────────────────────────────

    @commands.command(name="greroll")
    @commands.has_permissions(manage_guild=True)
    async def greroll(self, ctx, message_id: str, winners: int = 1):
        await self._do_greroll(ctx, message_id, winners)

    @slash.command(name="reroll", description="Reroll a giveaway winner.")
    @app_commands.describe(message_id="The message ID of the ended giveaway", winners="Number of new winners")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def greroll_slash(self, interaction: discord.Interaction, message_id: str, winners: int = 1):
        ctx = await commands.Context.from_interaction(interaction)
        await self._do_greroll(ctx, message_id, winners)

    async def _do_greroll(self, ctx, message_id, winners):
        mid = int(message_id)
        data = load(GW_FILE)
        gw = data.get(str(ctx.guild.id), {}).get(str(mid))
        if not gw:
            return await ctx.reply("❌ Giveaway not found.")
        if not gw.get("ended"):
            return await ctx.reply("❌ Giveaway hasn't ended yet.")
        ch = ctx.guild.get_channel(gw["channel_id"])
        if not ch:
            return await ctx.reply("❌ Channel not found.")
        try:
            msg = await ch.fetch_message(mid)
        except Exception:
            return await ctx.reply("❌ Message not found.")
        reaction = discord.utils.get(msg.reactions, emoji=Config.GIVEAWAY_EMOJI)
        if not reaction:
            return await ctx.reply("❌ No reactions found.")
        users = [u async for u in reaction.users() if not u.bot]
        if not users:
            return await ctx.reply("❌ No valid entries.")
        new_winners = random.sample(users, min(winners, len(users)))
        winner_mentions = ", ".join(w.mention for w in new_winners)
        await ctx.reply(f"🎊 New winner(s) for **{gw['prize']}**: {winner_mentions}!")

    # ── GLIST ─────────────────────────────────────────

    @commands.command(name="glist")
    @commands.has_permissions(manage_guild=True)
    async def glist(self, ctx):
        await self._do_glist(ctx)

    @slash.command(name="list", description="List all active giveaways.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def glist_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self._do_glist(ctx)

    async def _do_glist(self, ctx):
        data = load(GW_FILE).get(str(ctx.guild.id), {})
        active = [(mid, gw) for mid, gw in data.items() if not gw.get("ended")]
        if not active:
            return await ctx.reply("No active giveaways.")
        lines = []
        for mid, gw in active:
            ch   = ctx.guild.get_channel(gw["channel_id"])
            ends = datetime.fromisoformat(gw["ends_at"])
            lines.append(f"• **{gw['prize']}** in {ch.mention if ch else 'unknown'} — ends {discord.utils.format_dt(ends, 'R')}")
        e = discord.Embed(title="🎉 Active Giveaways", description="\n".join(lines), color=Config.COLOR_GOLD)
        await ctx.reply(embed=e)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if str(payload.emoji) != Config.GIVEAWAY_EMOJI or payload.user_id == self.bot.user.id:
            return
        data = load(GW_FILE)
        gw = data.get(str(payload.guild_id), {}).get(str(payload.message_id))
        if not gw or gw.get("ended"):
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        ch = guild.get_channel(payload.channel_id)
        if not ch:
            return
        try:
            msg      = await ch.fetch_message(payload.message_id)
            reaction = discord.utils.get(msg.reactions, emoji=Config.GIVEAWAY_EMOJI)
            count    = (reaction.count - 1) if reaction else 0
            host     = guild.get_member(gw["host_id"])
            ends_at  = datetime.fromisoformat(gw["ends_at"])
            e = gw_embed(gw["prize"], ends_at, gw["winners"], host or guild.me, count)
            await msg.edit(embed=e)
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(Giveaway(bot))
