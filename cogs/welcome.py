"""
cogs/welcome.py
Slash group: /welcome
Welcome/goodbye messages with variable substitution,
embed or plain text, DM greet option, and auto-role on join.
Prefix commands still work with ~
"""

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
from config import Config
from utils.data import load, save


def _settings(guild_id: int) -> dict:
    data = load("guild_settings.json")
    return data.get(str(guild_id), {})


def _format(template: str, member: discord.Member) -> str:
    return (
        template
        .replace("{user}",        member.mention)
        .replace("{username}",    str(member))
        .replace("{displayname}", member.display_name)
        .replace("{server}",      member.guild.name)
        .replace("{membercount}", str(member.guild.member_count))
        .replace("{id}",          str(member.id))
    )


class Welcome(commands.Cog):
    """👋 Welcome, goodbye & auto-role system."""

    slash = app_commands.Group(name="welcome", description="Welcome and auto-role configuration")

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        s = _settings(member.guild.id)

        for role_id in s.get("autoroles", []):
            role = member.guild.get_role(int(role_id))
            if role:
                try:
                    await member.add_roles(role, reason="Auto-role on join")
                except Exception:
                    pass

        ch_id = s.get("welcome_channel")
        if not ch_id:
            return
        ch = member.guild.get_channel(int(ch_id))
        if not ch:
            return

        template = s.get("welcome_message", "👋 Welcome {user} to **{server}**! You are member **#{membercount}**.")
        msg      = _format(template, member)

        if s.get("welcome_embed", True):
            e = discord.Embed(description=msg, color=Config.COLOR_OK, timestamp=datetime.now(timezone.utc))
            e.set_author(name=f"Welcome to {member.guild.name}!", icon_url=member.guild.icon.url if member.guild.icon else None)
            e.set_thumbnail(url=member.display_avatar.url)
            e.set_footer(text=f"ID: {member.id}")
            await ch.send(embed=e)
        else:
            await ch.send(msg)

        dm_template = s.get("welcome_dm")
        if dm_template:
            try:
                await member.send(_format(dm_template, member))
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        s = _settings(member.guild.id)
        ch_id = s.get("goodbye_channel")
        if not ch_id:
            return
        ch = member.guild.get_channel(int(ch_id))
        if not ch:
            return
        template = s.get("goodbye_message", "👋 **{username}** has left the server. We now have **{membercount}** members.")
        msg = _format(template, member)
        if s.get("goodbye_embed", True):
            e = discord.Embed(description=msg, color=Config.COLOR_ERR, timestamp=datetime.now(timezone.utc))
            e.set_thumbnail(url=member.display_avatar.url)
            await ch.send(embed=e)
        else:
            await ch.send(msg)

    # ── SETWELCOME ────────────────────────────────────

    @commands.command(name="setwelcome")
    @commands.has_permissions(manage_guild=True)
    async def setwelcome(self, ctx, channel: discord.TextChannel):
        data = load("guild_settings.json")
        data.setdefault(str(ctx.guild.id), {})["welcome_channel"] = channel.id
        save("guild_settings.json", data)
        await ctx.reply(f"✅ Welcome channel set to {channel.mention}.")

    @slash.command(name="setchannel", description="Set the welcome message channel.")
    @app_commands.describe(channel="Channel to send welcome messages to")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setwelcome_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        ctx = await commands.Context.from_interaction(interaction)
        await self.setwelcome.callback(self, ctx, channel)

    # ── SETGOODBYE ────────────────────────────────────

    @commands.command(name="setgoodbye")
    @commands.has_permissions(manage_guild=True)
    async def setgoodbye(self, ctx, channel: discord.TextChannel):
        data = load("guild_settings.json")
        data.setdefault(str(ctx.guild.id), {})["goodbye_channel"] = channel.id
        save("guild_settings.json", data)
        await ctx.reply(f"✅ Goodbye channel set to {channel.mention}.")

    @slash.command(name="setgoodbye", description="Set the goodbye message channel.")
    @app_commands.describe(channel="Channel to send goodbye messages to")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setgoodbye_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        ctx = await commands.Context.from_interaction(interaction)
        await self.setgoodbye.callback(self, ctx, channel)

    # ── WELCOMEMSG ────────────────────────────────────

    @commands.command(name="welcomemsg")
    @commands.has_permissions(manage_guild=True)
    async def welcomemsg(self, ctx, *, message: str):
        """Variables: {user} {username} {displayname} {server} {membercount} {id}"""
        data = load("guild_settings.json")
        data.setdefault(str(ctx.guild.id), {})["welcome_message"] = message
        save("guild_settings.json", data)
        await ctx.reply(f"✅ Welcome message updated:\n> {message}")

    @slash.command(name="setwelcomemsg", description="Set the welcome message text.")
    @app_commands.describe(message="Message text. Use {user} {server} {membercount} etc.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcomemsg_slash(self, interaction: discord.Interaction, message: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.welcomemsg.callback(self, ctx, message=message)

    # ── GOODBYEMSG ────────────────────────────────────

    @commands.command(name="goodbyemsg")
    @commands.has_permissions(manage_guild=True)
    async def goodbyemsg(self, ctx, *, message: str):
        """Variables: {user} {username} {displayname} {server} {membercount} {id}"""
        data = load("guild_settings.json")
        data.setdefault(str(ctx.guild.id), {})["goodbye_message"] = message
        save("guild_settings.json", data)
        await ctx.reply(f"✅ Goodbye message updated:\n> {message}")

    @slash.command(name="setgoodbyemsg", description="Set the goodbye message text.")
    @app_commands.describe(message="Message text. Use {username} {server} {membercount} etc.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbyemsg_slash(self, interaction: discord.Interaction, message: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.goodbyemsg.callback(self, ctx, message=message)

    # ── WELCOMEDM ─────────────────────────────────────

    @commands.command(name="welcomedm")
    @commands.has_permissions(manage_guild=True)
    async def welcomedm(self, ctx, *, message: str = None):
        """Set the DM sent to new members. Leave empty to disable."""
        data = load("guild_settings.json")
        data.setdefault(str(ctx.guild.id), {})["welcome_dm"] = message
        save("guild_settings.json", data)
        if message:
            await ctx.reply(f"✅ Welcome DM set:\n> {message}")
        else:
            await ctx.reply("✅ Welcome DM disabled.")

    @slash.command(name="setdm", description="Set the DM sent to new members (leave empty to disable).")
    @app_commands.describe(message="DM message text, or leave empty to disable")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcomedm_slash(self, interaction: discord.Interaction, message: str = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.welcomedm.callback(self, ctx, message=message)

    # ── AUTOROLE ──────────────────────────────────────

    @commands.command(name="autorole")
    @commands.has_permissions(manage_roles=True)
    async def autorole(self, ctx, role: discord.Role):
        """Add or remove an auto-role given to new members."""
        data = load("guild_settings.json")
        gd   = data.setdefault(str(ctx.guild.id), {})
        roles = gd.setdefault("autoroles", [])
        if role.id in roles:
            roles.remove(role.id)
            msg = f"➖ Removed {role.mention} from auto-roles."
        else:
            roles.append(role.id)
            msg = f"➕ Added {role.mention} to auto-roles."
        gd["autoroles"] = roles
        save("guild_settings.json", data)
        await ctx.reply(msg)

    @slash.command(name="autorole", description="Add or remove an auto-role assigned on join.")
    @app_commands.describe(role="Role to add/remove from auto-roles")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def autorole_slash(self, interaction: discord.Interaction, role: discord.Role):
        ctx = await commands.Context.from_interaction(interaction)
        await self.autorole.callback(self, ctx, role)

    # ── AUTOROLES LIST ────────────────────────────────

    @commands.command(name="autoroles")
    @commands.has_permissions(manage_roles=True)
    async def autoroles(self, ctx):
        """List all current auto-roles."""
        s = _settings(ctx.guild.id)
        role_ids = s.get("autoroles", [])
        if not role_ids:
            return await ctx.reply("No auto-roles configured.")
        roles = [ctx.guild.get_role(rid) for rid in role_ids]
        await ctx.reply("**Auto-roles:** " + ", ".join(r.mention for r in roles if r))

    @slash.command(name="listautoroles", description="List all auto-roles assigned on join.")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def autoroles_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.autoroles.callback(self, ctx)

    # ── WELCOMEEMBED ──────────────────────────────────

    @commands.command(name="welcomeembed")
    @commands.has_permissions(manage_guild=True)
    async def welcomeembed(self, ctx):
        """Toggle embed style for welcome messages on/off."""
        data = load("guild_settings.json")
        gd = data.setdefault(str(ctx.guild.id), {})
        gd["welcome_embed"] = not gd.get("welcome_embed", True)
        save("guild_settings.json", data)
        await ctx.reply(f"✅ Welcome embed: **{'on' if gd['welcome_embed'] else 'off'}**.")

    @slash.command(name="toggleembed", description="Toggle embed style for welcome/goodbye messages.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcomeembed_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.welcomeembed.callback(self, ctx)

    # ── PREVIEW ───────────────────────────────────────

    @commands.command(name="previewwelcome")
    @commands.has_permissions(manage_guild=True)
    async def previewwelcome(self, ctx):
        """Preview the welcome message."""
        s = _settings(ctx.guild.id)
        template = s.get("welcome_message", "👋 Welcome {user} to **{server}**! You are member **#{membercount}**.")
        msg = _format(template, ctx.author)
        if s.get("welcome_embed", True):
            e = discord.Embed(description=msg, color=Config.COLOR_OK, timestamp=datetime.now(timezone.utc))
            e.set_author(name=f"Welcome to {ctx.guild.name}!", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
            e.set_thumbnail(url=ctx.author.display_avatar.url)
            e.set_footer(text="Preview — Welcome Message")
            await ctx.reply(embed=e)
        else:
            await ctx.reply(f"**Preview:**\n{msg}")

    @slash.command(name="preview", description="Preview the welcome or goodbye message.")
    @app_commands.describe(message_type="Which message to preview")
    @app_commands.choices(message_type=[
        app_commands.Choice(name="Welcome", value="welcome"),
        app_commands.Choice(name="Goodbye", value="goodbye"),
    ])
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def preview_slash(self, interaction: discord.Interaction, message_type: str = "welcome"):
        s = _settings(interaction.guild.id)
        if message_type == "goodbye":
            template = s.get("goodbye_message", "👋 **{username}** has left the server. We now have **{membercount}** members.")
            color = Config.COLOR_ERR
        else:
            template = s.get("welcome_message", "👋 Welcome {user} to **{server}**! You are member **#{membercount}**.")
            color = Config.COLOR_OK
        msg = _format(template, interaction.user)
        if s.get("welcome_embed", True):
            e = discord.Embed(description=msg, color=color, timestamp=datetime.now(timezone.utc))
            e.set_thumbnail(url=interaction.user.display_avatar.url)
            e.set_footer(text=f"Preview — {message_type.title()} Message")
            await interaction.response.send_message(embed=e, ephemeral=True)
        else:
            await interaction.response.send_message(f"**Preview:**\n{msg}", ephemeral=True)

    @commands.command(name="leavepreview")
    @commands.has_permissions(manage_guild=True)
    async def leavepreview(self, ctx):
        """Preview the goodbye/leave message."""
        s = _settings(ctx.guild.id)
        template = s.get("goodbye_message", "👋 **{username}** has left the server. We now have **{membercount}** members.")
        msg = _format(template, ctx.author)
        if s.get("goodbye_embed", True):
            e = discord.Embed(description=msg, color=Config.COLOR_ERR, timestamp=datetime.now(timezone.utc))
            e.set_thumbnail(url=ctx.author.display_avatar.url)
            e.set_footer(text="Preview — Goodbye Message")
            await ctx.reply(embed=e)
        else:
            await ctx.reply(f"**Preview:**\n{msg}")


async def setup(bot):
    await bot.add_cog(Welcome(bot))
