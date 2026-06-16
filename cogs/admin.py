"""
cogs/admin.py
Slash group: /admin
Server administration and bot configuration overview.
Prefix commands still work with ~
"""

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
from config import Config
from utils.data import load, save

# ── Reset confirmation view ────────────────────────────

class ConfirmResetView(discord.ui.View):
    def __init__(self, guild_id: int, module: str, author_id: int):
        super().__init__(timeout=30)
        self.guild_id  = guild_id
        self.module    = module
        self.author_id = author_id
        self.result    = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Only the command caller can confirm this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Yes, Reset", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = False
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()


# ── Module reset keys ─────────────────────────────────

RESET_KEYS = {
    "welcome":    ["welcome_channel", "goodbye_channel", "welcome_message", "goodbye_message",
                   "welcome_dm", "autoroles", "welcome_embed", "goodbye_embed"],
    "logging":    ["logging"],
    "automod":    ["automod"],
    "moderation": ["mod_log_channel", "mute_role"],
    "tickets":    ["ticket_category", "ticket_log_channel", "ticket_staff_role"],
    "leveling":   ["level_channel", "level_roles", "xp_blacklist"],
    "reports":    ["report_channel", "suggestion_channel", "bug_report_channel"],
    "invites":    ["invite_log_channel"],
    "jtc":        None,   # stored in jtc.json, handled separately
}

RESET_CHOICES = [
    app_commands.Choice(name="Welcome / Goodbye",    value="welcome"),
    app_commands.Choice(name="Logging",              value="logging"),
    app_commands.Choice(name="AutoMod",              value="automod"),
    app_commands.Choice(name="Moderation",           value="moderation"),
    app_commands.Choice(name="Tickets",              value="tickets"),
    app_commands.Choice(name="Leveling",             value="leveling"),
    app_commands.Choice(name="Reports / Suggestions", value="reports"),
    app_commands.Choice(name="Invite Tracking",      value="invites"),
    app_commands.Choice(name="JTC (voice)",          value="jtc"),
    app_commands.Choice(name="Everything",           value="all"),
]


class Admin(commands.Cog):
    """⚙️ Server administration and bot configuration."""

    slash = app_commands.Group(name="admin", description="Server administration commands")

    def __init__(self, bot):
        self.bot = bot

    # ── CONFIG ────────────────────────────────────────

    @commands.command(name="serverconfig")
    @commands.has_permissions(administrator=True)
    async def serverconfig(self, ctx):
        """Show all configured bot settings for this server."""
        await self._send_config(ctx.guild, ctx.reply)

    @slash.command(name="config", description="Show all configured bot settings for this server.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def config_slash(self, interaction: discord.Interaction):
        await self._send_config(interaction.guild, interaction.response.send_message, ephemeral=True)

    async def _send_config(self, guild: discord.Guild, send_fn, **kwargs):
        gs  = load("guild_settings.json").get(str(guild.id), {})
        am  = gs.get("automod", {})
        lg  = gs.get("logging", {})

        def ch(ch_id):
            if not ch_id:
                return "*Not set*"
            c = guild.get_channel(int(ch_id))
            return c.mention if c else f"*Deleted ({ch_id})*"

        def role(role_id):
            if not role_id:
                return "*Not set*"
            r = guild.get_role(int(role_id))
            return r.mention if r else f"*Deleted ({role_id})*"

        e = discord.Embed(
            title=f"⚙️ {guild.name} — Bot Configuration",
            color=Config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        if guild.icon:
            e.set_thumbnail(url=guild.icon.url)

        # Welcome / goodbye
        e.add_field(
            name="👋 Welcome",
            value=(
                f"Channel: {ch(gs.get('welcome_channel'))}\n"
                f"Goodbye: {ch(gs.get('goodbye_channel'))}\n"
                f"DM: {'✅' if gs.get('welcome_dm') else '❌'}\n"
                f"Embed: {'✅' if gs.get('welcome_embed', True) else '❌'}\n"
                f"Auto-roles: {len(gs.get('autoroles', []))}"
            ),
            inline=True
        )

        # Moderation
        e.add_field(
            name="⚔️ Moderation",
            value=(
                f"Mod log: {ch(gs.get('mod_log_channel'))}\n"
                f"Mute role: {role(gs.get('mute_role'))}"
            ),
            inline=True
        )

        # Logging
        log_ch  = ch(lg.get("channel"))
        log_on  = "✅" if lg.get("enabled") else "❌"
        e.add_field(
            name="📝 Logging",
            value=f"Channel: {log_ch}\nEnabled: {log_on}",
            inline=True
        )

        # AutoMod
        e.add_field(
            name="🛡️ AutoMod",
            value=(
                f"Enabled: {'✅' if am.get('enabled', True) else '❌'}\n"
                f"Anti-Spam: {'✅' if am.get('anti_spam', True) else '❌'}\n"
                f"Anti-Invite: {'✅' if am.get('anti_invite', True) else '❌'}\n"
                f"Anti-Links: {'✅' if am.get('anti_links') else '❌'}\n"
                f"Caps Filter: {'✅' if am.get('caps_filter', True) else '❌'}\n"
                f"Log: {ch(am.get('log_channel'))}"
            ),
            inline=True
        )

        # Tickets
        e.add_field(
            name="🎟️ Tickets",
            value=(
                f"Category: {ch(gs.get('ticket_category'))}\n"
                f"Log: {ch(gs.get('ticket_log_channel'))}\n"
                f"Staff role: {role(gs.get('ticket_staff_role'))}"
            ),
            inline=True
        )

        # Leveling
        e.add_field(
            name="⭐ Leveling",
            value=(
                f"Level-up channel: {ch(gs.get('level_channel'))}\n"
                f"Level roles: {len(gs.get('level_roles', {}))}\n"
                f"XP blacklisted ch: {len(gs.get('xp_blacklist', []))}"
            ),
            inline=True
        )

        # Reports
        e.add_field(
            name="🚨 Reports",
            value=(
                f"Reports: {ch(gs.get('report_channel'))}\n"
                f"Suggestions: {ch(gs.get('suggestion_channel'))}\n"
                f"Bug reports: {ch(gs.get('bug_report_channel'))}"
            ),
            inline=True
        )

        # Invite log
        e.add_field(
            name="📨 Invites",
            value=f"Log channel: {ch(gs.get('invite_log_channel'))}",
            inline=True
        )

        # JTC
        jtc_data = load("jtc.json").get(str(guild.id), {})
        e.add_field(
            name="🔊 JTC",
            value=(
                f"Trigger: {ch(jtc_data.get('jtc_channel'))}\n"
                f"Panel: {ch(jtc_data.get('control_panel_channel'))}\n"
                f"Active channels: {len(jtc_data.get('channels', {}))}"
            ),
            inline=True
        )

        e.set_footer(text=f"Use /admin reset to clear any module's settings")
        await send_fn(embed=e, **kwargs)

    # ── RESET ─────────────────────────────────────────

    @commands.command(name="adminreset")
    @commands.has_permissions(administrator=True)
    async def adminreset(self, ctx, module: str = None):
        """Reset a module's settings. Usage: ~adminreset <module> or ~adminreset all"""
        valid = list(RESET_KEYS.keys()) + ["all"]
        if not module or module not in valid:
            return await ctx.reply(
                f"❌ Specify a module. Valid options: `{'`, `'.join(valid)}`\n"
                f"Example: `{Config.PREFIX}adminreset automod`"
            )

        e = discord.Embed(
            title="⚠️ Confirm Reset",
            description=(
                f"This will reset **{module}** settings for **{ctx.guild.name}**.\n"
                f"This **cannot be undone**. Are you sure?"
            ),
            color=Config.COLOR_WARN
        )
        view = ConfirmResetView(ctx.guild.id, module, ctx.author.id)
        msg  = await ctx.reply(embed=e, view=view)
        await view.wait()

        if view.result:
            self._do_reset(ctx.guild.id, module)
            await msg.edit(
                embed=discord.Embed(title=f"✅ Reset `{module}` settings.", color=Config.COLOR_OK),
                view=None
            )
        else:
            await msg.edit(
                embed=discord.Embed(title="❌ Reset cancelled.", color=Config.COLOR_ERR),
                view=None
            )

    @slash.command(name="reset", description="Reset a module's settings with confirmation.")
    @app_commands.describe(module="Module to reset")
    @app_commands.choices(module=RESET_CHOICES)
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_slash(self, interaction: discord.Interaction, module: str):
        e = discord.Embed(
            title="⚠️ Confirm Reset",
            description=(
                f"This will reset **{module}** settings for **{interaction.guild.name}**.\n"
                f"This **cannot be undone**. Are you sure?"
            ),
            color=Config.COLOR_WARN
        )
        view = ConfirmResetView(interaction.guild.id, module, interaction.user.id)
        await interaction.response.send_message(embed=e, view=view, ephemeral=True)
        await view.wait()

        if view.result:
            self._do_reset(interaction.guild.id, module)
            await interaction.edit_original_response(
                embed=discord.Embed(title=f"✅ Reset `{module}` settings.", color=Config.COLOR_OK),
                view=None
            )
        else:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ Reset cancelled.", color=Config.COLOR_ERR),
                view=None
            )

    def _do_reset(self, guild_id: int, module: str):
        """Perform the actual settings reset."""
        gid = str(guild_id)

        if module == "jtc" or module == "all":
            jtc_data = load("jtc.json")
            jtc_data.pop(gid, None)
            save("jtc.json", jtc_data)

        if module == "all":
            data = load("guild_settings.json")
            data.pop(gid, None)
            save("guild_settings.json", data)
            return

        keys = RESET_KEYS.get(module)
        if not keys:
            return

        data = load("guild_settings.json")
        gd   = data.get(gid, {})

        for key in keys:
            if isinstance(gd.get(key), dict):
                gd[key] = {}
            elif isinstance(gd.get(key), list):
                gd[key] = []
            else:
                gd.pop(key, None)

        data[gid] = gd
        save("guild_settings.json", data)

    # ── PERMISSIONS CHECK ─────────────────────────────

    @commands.command(name="botperms")
    @commands.has_permissions(administrator=True)
    async def botperms(self, ctx):
        """Check which permissions the bot has and is missing."""
        await self._send_perms(ctx.guild, ctx.reply)

    @slash.command(name="permissions", description="Check what permissions the bot has and is missing.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def permissions_slash(self, interaction: discord.Interaction):
        await self._send_perms(interaction.guild, interaction.response.send_message, ephemeral=True)

    async def _send_perms(self, guild: discord.Guild, send_fn, **kwargs):
        me     = guild.me
        perms  = me.guild_permissions

        needed = {
            "Kick Members":           perms.kick_members,
            "Ban Members":            perms.ban_members,
            "Manage Channels":        perms.manage_channels,
            "Manage Guild":           perms.manage_guild,
            "Add Reactions":          perms.add_reactions,
            "View Channel":           perms.view_channel,
            "Send Messages":          perms.send_messages,
            "Manage Messages":        perms.manage_messages,
            "Embed Links":            perms.embed_links,
            "Attach Files":           perms.attach_files,
            "Read Message History":   perms.read_message_history,
            "Connect":                perms.connect,
            "Speak":                  perms.speak,
            "Move Members":           perms.move_members,
            "Manage Roles":           perms.manage_roles,
            "Moderate Members":       perms.moderate_members,
            "View Audit Log":         perms.view_audit_log,
            "Manage Nicknames":       perms.manage_nicknames,
        }

        have    = [f"✅ {p}" for p, v in needed.items() if v]
        missing = [f"❌ {p}" for p, v in needed.items() if not v]

        e = discord.Embed(
            title=f"🔐 {me.display_name} — Permission Check",
            color=Config.COLOR_OK if not missing else Config.COLOR_WARN,
            timestamp=datetime.now(timezone.utc)
        )
        e.set_thumbnail(url=me.display_avatar.url)

        if have:
            # Split into two columns if long
            mid = len(have) // 2 + len(have) % 2
            e.add_field(name="Granted Permissions", value="\n".join(have[:mid]), inline=True)
            if have[mid:]:
                e.add_field(name="\u200b", value="\n".join(have[mid:]), inline=True)

        if missing:
            e.add_field(name="⚠️ Missing Permissions", value="\n".join(missing), inline=False)
            e.set_footer(text="Missing permissions may cause some bot features to fail.")
        else:
            e.set_footer(text="All required permissions are granted.")

        await send_fn(embed=e, **kwargs)

    # ── ANNOUNCE ──────────────────────────────────────

    @commands.command(name="announce")
    @commands.has_permissions(administrator=True)
    async def announce(self, ctx, channel: discord.TextChannel, *, message: str):
        """Send an announcement embed to a channel."""
        e = discord.Embed(
            description=message,
            color=Config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        e.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        e.set_footer(text=f"Announcement by {ctx.author.display_name}")
        await channel.send(embed=e)
        await ctx.reply(f"✅ Announcement sent to {channel.mention}.")

    @slash.command(name="announce", description="Send a formatted announcement to a channel.")
    @app_commands.describe(channel="Channel to post the announcement in", message="Announcement text")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def announce_slash(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        e = discord.Embed(
            description=message,
            color=Config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        e.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        e.set_footer(text=f"Announcement by {interaction.user.display_name}")
        await channel.send(embed=e)
        await interaction.response.send_message(f"✅ Announcement sent to {channel.mention}.", ephemeral=True)

    # ── CHANNEL DELAY (replaces the former slowmode duplicate) ──────────
    # The moderation cog owns the top-level /slowmode and ~slowmode commands.
    # Here we expose the same feature as /admin channeldelay to avoid clashing.

    @commands.command(name="channeldelay")
    @commands.has_permissions(manage_channels=True)
    async def channeldelay(self, ctx, seconds: int, channel: discord.TextChannel = None):
        """Set slowmode delay on a channel (admin shorthand). 0 to disable."""
        ch = channel or ctx.channel
        await ch.edit(slowmode_delay=max(0, min(seconds, 21600)))
        if seconds <= 0:
            await ctx.reply(f"✅ Slowmode **disabled** in {ch.mention}.")
        else:
            await ctx.reply(f"✅ Slowmode set to **{seconds}s** in {ch.mention}.")

    @slash.command(name="channeldelay", description="Set slowmode delay on a channel (0 to disable).")
    @app_commands.describe(seconds="Delay in seconds (0–21600)", channel="Channel to apply delay to (defaults to current)")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def channeldelay_slash(self, interaction: discord.Interaction, seconds: int, channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        await ch.edit(slowmode_delay=max(0, min(seconds, 21600)))
        if seconds <= 0:
            await interaction.response.send_message(f"✅ Slowmode **disabled** in {ch.mention}.", ephemeral=True)
        else:
            await interaction.response.send_message(f"✅ Slowmode set to **{seconds}s** in {ch.mention}.", ephemeral=True)

    # ── SETNICK ───────────────────────────────────────

    @commands.command(name="botnick")
    @commands.has_permissions(manage_nicknames=True)
    async def botnick(self, ctx, *, nickname: str = None):
        """Change the bot's nickname in this server."""
        await ctx.guild.me.edit(nick=nickname)
        if nickname:
            await ctx.reply(f"✅ Bot nickname set to **{nickname}**.")
        else:
            await ctx.reply("✅ Bot nickname **reset**.")

    @slash.command(name="botnick", description="Change the bot's nickname in this server.")
    @app_commands.describe(nickname="New nickname (leave empty to reset)")
    @app_commands.default_permissions(manage_nicknames=True)
    @app_commands.checks.has_permissions(manage_nicknames=True)
    async def botnick_slash(self, interaction: discord.Interaction, nickname: str = None):
        await interaction.guild.me.edit(nick=nickname)
        if nickname:
            await interaction.response.send_message(f"✅ Bot nickname set to **{nickname}**.", ephemeral=True)
        else:
            await interaction.response.send_message("✅ Bot nickname **reset**.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Admin(bot))
