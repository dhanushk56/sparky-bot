"""
cogs/reaction_roles.py
Slash group: /rr
Prefix commands still work with ~
"""

import discord
from discord.ext import commands
from discord import app_commands
from config import Config
from utils.data import load, save

RR_FILE = "reaction_roles.json"


def _get_rr(guild_id):
    return load(RR_FILE).get(str(guild_id), {})


def _save_rr(guild_id, rr):
    data = load(RR_FILE)
    data[str(guild_id)] = rr
    save(RR_FILE, data)


class ReactionRoles(commands.Cog):
    """🎭 Reaction role system."""

    slash = app_commands.Group(name="rr", description="Reaction role management")

    def __init__(self, bot):
        self.bot = bot

    # ── RRADD ─────────────────────────────────────────

    @commands.command(name="rradd")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def rradd(self, ctx, message_id: str, emoji: str, role: discord.Role, exclusive: bool = False):
        try:
            mid = int(message_id)
            msg = await ctx.channel.fetch_message(mid)
        except Exception:
            return await ctx.reply("❌ Message not found in this channel.")
        try:
            await msg.add_reaction(emoji)
        except discord.HTTPException:
            return await ctx.reply("❌ Invalid emoji or I can't use it.")
        rr  = _get_rr(ctx.guild.id)
        key = str(mid)
        rr.setdefault(key, {"channel_id": ctx.channel.id, "exclusive": exclusive, "roles": {}})
        rr[key]["roles"][emoji] = role.id
        if exclusive:
            rr[key]["exclusive"] = True
        _save_rr(ctx.guild.id, rr)
        await ctx.reply(f"✅ Reaction role added: {emoji} → {role.mention}")

    @slash.command(name="add", description="Add a reaction role to a message.")
    @app_commands.describe(
        message_id="Message ID to add reaction role to",
        emoji="Emoji to react with",
        role="Role to assign",
        exclusive="If True, having this role removes other reaction roles on the same message"
    )
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def rradd_slash(self, interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role, exclusive: bool = False):
        ctx = await commands.Context.from_interaction(interaction)
        await self.rradd.callback(self, ctx, message_id, emoji, role, exclusive)

    # ── RRREMOVE ──────────────────────────────────────

    @commands.command(name="rrremove")
    @commands.has_permissions(manage_roles=True)
    async def rrremove(self, ctx, message_id: str, emoji: str):
        rr  = _get_rr(ctx.guild.id)
        key = str(message_id)
        if key not in rr or emoji not in rr[key].get("roles", {}):
            return await ctx.reply("❌ No reaction role found.")
        del rr[key]["roles"][emoji]
        if not rr[key]["roles"]:
            del rr[key]
        _save_rr(ctx.guild.id, rr)
        await ctx.reply(f"✅ Removed reaction role for {emoji}.")

    @slash.command(name="remove", description="Remove a reaction role from a message.")
    @app_commands.describe(message_id="Message ID", emoji="Emoji to remove")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def rrremove_slash(self, interaction: discord.Interaction, message_id: str, emoji: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.rrremove.callback(self, ctx, message_id, emoji)

    # ── RRLIST ────────────────────────────────────────

    @commands.command(name="rrlist")
    @commands.has_permissions(manage_roles=True)
    async def rrlist(self, ctx):
        rr = _get_rr(ctx.guild.id)
        if not rr:
            return await ctx.reply("No reaction roles configured.")
        e = discord.Embed(title="🎭 Reaction Roles", color=Config.COLOR_INFO)
        for msg_id, data in rr.items():
            ch    = ctx.guild.get_channel(data.get("channel_id", 0))
            lines = []
            for emoji, role_id in data.get("roles", {}).items():
                role = ctx.guild.get_role(int(role_id))
                lines.append(f"{emoji} → {role.mention if role else 'deleted role'}")
            e.add_field(
                name=f"Message {msg_id} in #{ch.name if ch else 'unknown'}",
                value="\n".join(lines) or "None",
                inline=False
            )
        await ctx.reply(embed=e)

    @slash.command(name="list", description="List all reaction roles in this server.")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def rrlist_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.rrlist.callback(self, ctx)

    # ── RRCLEAR ───────────────────────────────────────

    @commands.command(name="rrclear")
    @commands.has_permissions(manage_roles=True)
    async def rrclear(self, ctx, message_id: str):
        rr = _get_rr(ctx.guild.id)
        if str(message_id) not in rr:
            return await ctx.reply("❌ No reaction roles on that message.")
        del rr[str(message_id)]
        _save_rr(ctx.guild.id, rr)
        await ctx.reply("✅ Cleared all reaction roles from that message.")

    @slash.command(name="clear", description="Remove all reaction roles from a message.")
    @app_commands.describe(message_id="Message ID to clear")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def rrclear_slash(self, interaction: discord.Interaction, message_id: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.rrclear.callback(self, ctx, message_id)

    # ── RRPANEL ───────────────────────────────────────

    @commands.command(name="rrpanel")
    @commands.has_permissions(manage_roles=True)
    async def rrpanel(self, ctx, title: str = "React to get roles!", *, description: str = "React to the emojis below to get a role."):
        e = discord.Embed(title=title, description=description, color=Config.COLOR_INFO)
        e.set_footer(text="React below to get/remove roles")
        msg = await ctx.channel.send(embed=e)
        await ctx.reply(f"✅ Panel created! Use `~rradd {msg.id} <emoji> <role>` to add roles.")

    @slash.command(name="panel", description="Send a reaction role panel embed.")
    @app_commands.describe(title="Panel title", description="Panel description")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def rrpanel_slash(self, interaction: discord.Interaction, title: str = "React to get roles!", description: str = "React to the emojis below to get a role."):
        ctx = await commands.Context.from_interaction(interaction)
        await self.rrpanel.callback(self, ctx, title, description=description)

    # ── LISTENERS ─────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        await self._handle(payload, True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        await self._handle(payload, False)

    async def _handle(self, payload, adding: bool):
        if not payload.guild_id:
            return
        rr  = _get_rr(payload.guild_id)
        key = str(payload.message_id)
        if key not in rr:
            return
        emoji   = str(payload.emoji)
        role_id = rr[key].get("roles", {}).get(emoji)
        if not role_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return
        role = guild.get_role(int(role_id))
        if not role:
            return
        try:
            if adding:
                if rr[key].get("exclusive"):
                    for other_emoji, other_role_id in rr[key]["roles"].items():
                        if other_emoji != emoji:
                            other_role = guild.get_role(int(other_role_id))
                            if other_role and other_role in member.roles:
                                await member.remove_roles(other_role)
                await member.add_roles(role, reason="Reaction role")
            else:
                await member.remove_roles(role, reason="Reaction role removed")
        except discord.Forbidden:
            pass


async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
