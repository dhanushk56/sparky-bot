"""
cogs/reports.py
Slash group: /report
Report, suggestion & bug report system with modal forms.
Prefix commands still work with ~
"""

import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from datetime import datetime, timezone
from config import Config
from utils.data import load, save

REPORTS_FILE = "reports.json"


# ══════════════════════════════════════════════════════
# ── REPORT SYSTEM ─────────────────────────────────────
# ══════════════════════════════════════════════════════

class ReportModal(discord.ui.Modal, title="📋 Report a Member"):
    reported_user = discord.ui.TextInput(
        label="Reported Username",
        placeholder="Enter the Discord username of the person you're reporting",
        required=True,
        max_length=100,
    )
    reason = discord.ui.TextInput(
        label="Reason for Report",
        style=discord.TextStyle.paragraph,
        placeholder="Describe what happened in detail...",
        required=True,
        max_length=1000,
    )
    proof = discord.ui.TextInput(
        label="Proof Link",
        placeholder="Paste a screenshot or media link here",
        required=False,
        max_length=500,
    )

    def __init__(self, guild: discord.Guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        settings = load("guild_settings.json").get(str(self.guild.id), {})
        ch_id    = settings.get("report_channel")
        if not ch_id:
            return await interaction.response.send_message("❌ Report channel not configured.", ephemeral=True)
        ch = self.guild.get_channel(int(ch_id))
        if not ch:
            return await interaction.response.send_message("❌ Report channel not found.", ephemeral=True)

        data  = load(REPORTS_FILE)
        gdata = data.setdefault(str(self.guild.id), {"reports": {}, "counter": 0})
        gdata["counter"] = gdata.get("counter", 0) + 1
        report_id = gdata["counter"]

        report = {
            "id":          report_id,
            "reported":    self.reported_user.value,
            "reporter_id": interaction.user.id,
            "reason":      self.reason.value,
            "proof":       self.proof.value or "No proof provided",
            "status":      "pending",
            "time":        datetime.now(timezone.utc).isoformat(),
        }
        gdata.setdefault("reports", {})[str(report_id)] = report
        save(REPORTS_FILE, data)

        e = discord.Embed(
            title=f"🚨 New Report #{report_id:04d}",
            color=Config.COLOR_ERR,
            timestamp=datetime.now(timezone.utc),
        )
        e.add_field(name="Reported User",  value=self.reported_user.value, inline=True)
        e.add_field(name="Reporter",       value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
        e.add_field(name="Reason",         value=self.reason.value,        inline=False)
        e.add_field(name="Proof",          value=self.proof.value or "None provided", inline=False)
        e.set_footer(text=f"Report ID: {report_id:04d}")

        view = ReportActionView(report_id, int(ch_id))
        await ch.send(embed=e, view=view)
        await interaction.response.send_message("✅ Your report has been submitted!", ephemeral=True)


class ReportActionView(discord.ui.View):
    def __init__(self, report_id: int, log_channel_id: int):
        super().__init__(timeout=None)
        self.report_id      = report_id
        self.log_channel_id = log_channel_id

    @discord.ui.button(label="✅ Resolve", style=discord.ButtonStyle.success, custom_id="report_resolve")
    async def resolve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        data  = load(REPORTS_FILE)
        gdata = data.get(str(interaction.guild.id), {})
        report = gdata.get("reports", {}).get(str(self.report_id))
        if report:
            report["status"] = "resolved"
            report["resolved_by"] = interaction.user.id
            save(REPORTS_FILE, data)
        await interaction.response.send_message(f"✅ Report #{self.report_id:04d} marked as **resolved** by {interaction.user.mention}.")
        self.stop()

    @discord.ui.button(label="❌ Dismiss", style=discord.ButtonStyle.danger, custom_id="report_dismiss")
    async def dismiss(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        data  = load(REPORTS_FILE)
        gdata = data.get(str(interaction.guild.id), {})
        report = gdata.get("reports", {}).get(str(self.report_id))
        if report:
            report["status"] = "dismissed"
            save(REPORTS_FILE, data)
        await interaction.response.send_message(f"❌ Report #{self.report_id:04d} **dismissed** by {interaction.user.mention}.")
        self.stop()


class ReportPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📋 Fill Out Report Form", style=discord.ButtonStyle.danger, custom_id="report_open_modal")
    async def open_form(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReportModal(interaction.guild))


# ══════════════════════════════════════════════════════
# ── SUGGESTION SYSTEM ─────────────────────────────────
# ══════════════════════════════════════════════════════

class SuggestionModal(discord.ui.Modal, title="💡 Submit a Suggestion"):
    suggestion_title = discord.ui.TextInput(
        label="Suggestion Title",
        placeholder="Brief title for your suggestion",
        required=True,
        max_length=100,
    )
    description = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        placeholder="Describe your idea in detail...",
        required=True,
        max_length=1000,
    )

    def __init__(self, guild: discord.Guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        settings = load("guild_settings.json").get(str(self.guild.id), {})
        ch_id    = settings.get("suggestion_channel")
        if not ch_id:
            return await interaction.response.send_message("❌ Suggestion channel not configured.", ephemeral=True)
        ch = self.guild.get_channel(int(ch_id))
        if not ch:
            return await interaction.response.send_message("❌ Suggestion channel not found.", ephemeral=True)

        data  = load(REPORTS_FILE)
        gdata = data.setdefault(str(self.guild.id), {"suggestions": {}, "sug_counter": 0})
        gdata["sug_counter"] = gdata.get("sug_counter", 0) + 1
        sug_id = gdata["sug_counter"]

        suggestion = {
            "id":        sug_id,
            "title":     self.suggestion_title.value,
            "desc":      self.description.value,
            "author_id": interaction.user.id,
            "status":    "pending",
            "time":      datetime.now(timezone.utc).isoformat(),
        }
        gdata.setdefault("suggestions", {})[str(sug_id)] = suggestion
        save(REPORTS_FILE, data)

        e = discord.Embed(
            title=f"💡 Suggestion #{sug_id:04d} — {self.suggestion_title.value}",
            description=self.description.value,
            color=Config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc),
        )
        e.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        e.set_footer(text=f"Suggestion #{sug_id:04d}")

        view = SuggestionActionView(sug_id, int(ch_id))
        msg  = await ch.send(embed=e, view=view)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        await interaction.response.send_message("✅ Suggestion submitted!", ephemeral=True)


class SuggestionActionView(discord.ui.View):
    def __init__(self, sug_id: int, log_channel_id: int):
        super().__init__(timeout=None)
        self.sug_id         = sug_id
        self.log_channel_id = log_channel_id

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, custom_id="sug_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        data = load(REPORTS_FILE)
        sug  = data.get(str(interaction.guild.id), {}).get("suggestions", {}).get(str(self.sug_id))
        if sug:
            sug["status"] = "approved"
            save(REPORTS_FILE, data)
        await interaction.response.send_message(f"✅ Suggestion #{self.sug_id:04d} **approved** by {interaction.user.mention}.")
        self.stop()

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, custom_id="sug_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        data = load(REPORTS_FILE)
        sug  = data.get(str(interaction.guild.id), {}).get("suggestions", {}).get(str(self.sug_id))
        if sug:
            sug["status"] = "denied"
            save(REPORTS_FILE, data)
        await interaction.response.send_message(f"❌ Suggestion #{self.sug_id:04d} **denied** by {interaction.user.mention}.")
        self.stop()


class SuggestionPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💡 Submit a Suggestion", style=discord.ButtonStyle.primary, custom_id="sug_open_modal")
    async def open_form(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SuggestionModal(interaction.guild))


# ══════════════════════════════════════════════════════
# ── BUG REPORT SYSTEM ─────────────────────────────────
# ══════════════════════════════════════════════════════

class BugReportModal(discord.ui.Modal, title="🐛 Bug Report"):
    bug_title = discord.ui.TextInput(
        label="Bug Title",
        placeholder="Brief description of the bug",
        required=True,
        max_length=100,
    )
    steps = discord.ui.TextInput(
        label="Steps to Reproduce",
        style=discord.TextStyle.paragraph,
        placeholder="1. Do this\n2. Then this\n3. Bug appears",
        required=True,
        max_length=800,
    )
    expected = discord.ui.TextInput(
        label="Expected vs Actual Behavior",
        style=discord.TextStyle.paragraph,
        placeholder="Expected: ...\nActual: ...",
        required=True,
        max_length=500,
    )

    def __init__(self, guild: discord.Guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        settings = load("guild_settings.json").get(str(self.guild.id), {})
        ch_id    = settings.get("bug_report_channel")
        if not ch_id:
            return await interaction.response.send_message("❌ Bug report channel not configured.", ephemeral=True)
        ch = self.guild.get_channel(int(ch_id))
        if not ch:
            return await interaction.response.send_message("❌ Bug report channel not found.", ephemeral=True)

        data  = load(REPORTS_FILE)
        gdata = data.setdefault(str(self.guild.id), {"bugs": {}, "bug_counter": 0})
        gdata["bug_counter"] = gdata.get("bug_counter", 0) + 1
        bug_id = gdata["bug_counter"]

        e = discord.Embed(
            title=f"🐛 Bug Report #{bug_id:04d} — {self.bug_title.value}",
            color=Config.COLOR_WARN,
            timestamp=datetime.now(timezone.utc),
        )
        e.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        e.add_field(name="Steps to Reproduce", value=self.steps.value,    inline=False)
        e.add_field(name="Expected vs Actual",  value=self.expected.value, inline=False)
        e.set_footer(text=f"Bug #{bug_id:04d}")

        view = BugReportActionView(bug_id, int(ch_id))
        await ch.send(embed=e, view=view)
        await interaction.response.send_message("✅ Bug report submitted!", ephemeral=True)


class BugReportActionView(discord.ui.View):
    def __init__(self, bug_id: int, log_channel_id: int):
        super().__init__(timeout=None)
        self.bug_id         = bug_id
        self.log_channel_id = log_channel_id

    @discord.ui.button(label="🔧 Fixed", style=discord.ButtonStyle.success, custom_id="bug_fixed")
    async def fixed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await interaction.response.send_message(f"🔧 Bug #{self.bug_id:04d} marked as **fixed** by {interaction.user.mention}.")
        self.stop()

    @discord.ui.button(label="❌ Invalid", style=discord.ButtonStyle.danger, custom_id="bug_invalid")
    async def invalid(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await interaction.response.send_message(f"❌ Bug #{self.bug_id:04d} marked as **invalid** by {interaction.user.mention}.")
        self.stop()


class BugReportPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🐛 Report a Bug", style=discord.ButtonStyle.secondary, custom_id="bug_open_modal")
    async def open_form(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BugReportModal(interaction.guild))


# ══════════════════════════════════════════════════════
# ── COG ───────────────────────────────────────────────
# ══════════════════════════════════════════════════════

class Reports(commands.Cog):
    """🚨 Report, Suggestion & Bug Report system."""

    slash = app_commands.Group(name="report", description="Report, suggestion, and bug report system")

    def __init__(self, bot):
        self.bot = bot
        bot.add_view(ReportPanelView())
        bot.add_view(SuggestionPanelView())
        bot.add_view(BugReportPanelView())
        bot.add_view(ReportActionView(0, 0))
        bot.add_view(SuggestionActionView(0, 0))
        bot.add_view(BugReportActionView(0, 0))

    # ── REPORT ────────────────────────────────────────

    @commands.command(name="report")
    async def report(self, ctx):
        """Open the member report form."""
        settings = load("guild_settings.json").get(str(ctx.guild.id), {})
        if not settings.get("report_channel"):
            return await ctx.reply("❌ No report channel set. Ask an admin to use `~setreportchannel`.")
        e = discord.Embed(
            title="🚨 Report a Member",
            description=(
                "**Before submitting a report, you need proof.**\n\n"
                "**How to get proof:**\n"
                "1. Take a screenshot of the evidence\n"
                "2. Upload it to any Discord channel\n"
                "3. Right-click the image → **Copy Link**\n"
                "4. Click the button below and paste the link in the Proof field\n\n"
                "⚠️ **Reports without valid proof will be dismissed.**"
            ),
            color=Config.COLOR_ERR,
        )
        await ctx.reply(embed=e, view=ReportPanelView())

    @slash.command(name="member", description="Report a member to staff.")
    async def report_slash(self, interaction: discord.Interaction):
        settings = load("guild_settings.json").get(str(interaction.guild.id), {})
        if not settings.get("report_channel"):
            return await interaction.response.send_message("❌ No report channel set. Ask an admin to use `/report setchannel`.", ephemeral=True)
        await interaction.response.send_modal(ReportModal(interaction.guild))

    @commands.command(name="setreportchannel")
    @commands.has_permissions(administrator=True)
    async def setreportchannel(self, ctx, channel: discord.TextChannel):
        data = load("guild_settings.json")
        data.setdefault(str(ctx.guild.id), {})["report_channel"] = channel.id
        save("guild_settings.json", data)
        await ctx.reply(f"✅ Reports will be sent to {channel.mention}.")

    @slash.command(name="setchannel", description="Set the channel for member reports.")
    @app_commands.describe(channel="Channel for reports")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def setreportchannel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        ctx = await commands.Context.from_interaction(interaction)
        await self.setreportchannel.callback(self, ctx, channel)

    @commands.command(name="reports")
    @commands.has_permissions(manage_messages=True)
    async def reports(self, ctx):
        """View pending reports."""
        data    = load(REPORTS_FILE).get(str(ctx.guild.id), {})
        reps    = data.get("reports", {})
        pending = [r for r in reps.values() if r.get("status") == "pending"]
        if not pending:
            return await ctx.reply("✅ No pending reports!")
        lines = [
            f"`#{r['id']:04d}` — **{r['reported']}** reported by <@{r['reporter_id']}>"
            for r in pending[:10]
        ]
        e = discord.Embed(
            title=f"🚨 Pending Reports ({len(pending)})",
            description="\n".join(lines),
            color=Config.COLOR_ERR,
        )
        await ctx.reply(embed=e)

    @slash.command(name="list", description="View pending reports.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def reports_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.reports.callback(self, ctx)

    # ── SUGGESTION ────────────────────────────────────

    @commands.command(name="suggestion")
    async def suggestion(self, ctx):
        """Open the suggestion form."""
        settings = load("guild_settings.json").get(str(ctx.guild.id), {})
        if not settings.get("suggestion_channel"):
            return await ctx.reply("❌ No suggestion channel set. Ask an admin to use `~setsuggestions`.")
        e = discord.Embed(
            title="💡 Submit a Suggestion",
            description=(
                "Have an idea to improve the server? We'd love to hear it!\n\n"
                "Click the button below to fill out the suggestion form.\n"
                "Once submitted, the community can vote on your idea with 👍 and 👎."
            ),
            color=Config.COLOR_INFO,
        )
        await ctx.reply(embed=e, view=SuggestionPanelView())

    @slash.command(name="suggest", description="Submit a suggestion for the server.")
    async def suggestion_slash(self, interaction: discord.Interaction):
        settings = load("guild_settings.json").get(str(interaction.guild.id), {})
        if not settings.get("suggestion_channel"):
            return await interaction.response.send_message("❌ No suggestion channel set. Ask an admin to use `/report setsuggestions`.", ephemeral=True)
        await interaction.response.send_modal(SuggestionModal(interaction.guild))

    @commands.command(name="setsuggestions")
    @commands.has_permissions(administrator=True)
    async def setsuggestions(self, ctx, channel: discord.TextChannel):
        data = load("guild_settings.json")
        data.setdefault(str(ctx.guild.id), {})["suggestion_channel"] = channel.id
        save("guild_settings.json", data)
        await ctx.reply(f"✅ Suggestions will be sent to {channel.mention}.")

    @slash.command(name="setsuggestions", description="Set the suggestions channel.")
    @app_commands.describe(channel="Channel for suggestions")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def setsuggestions_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        ctx = await commands.Context.from_interaction(interaction)
        await self.setsuggestions.callback(self, ctx, channel)

    @commands.command(name="suggestions")
    @commands.has_permissions(manage_guild=True)
    async def suggestions(self, ctx):
        """View pending suggestions."""
        data    = load(REPORTS_FILE).get(str(ctx.guild.id), {})
        sugs    = data.get("suggestions", {})
        pending = [s for s in sugs.values() if s.get("status") == "pending"]
        if not pending:
            return await ctx.reply("✅ No pending suggestions!")
        lines = [
            f"`#{s['id']:04d}` — **{s['title']}** by <@{s['author_id']}>"
            for s in pending[:10]
        ]
        e = discord.Embed(
            title=f"💡 Pending Suggestions ({len(pending)})",
            description="\n".join(lines),
            color=Config.COLOR_INFO,
        )
        await ctx.reply(embed=e)

    # ── BUG REPORT ────────────────────────────────────

    @commands.command(name="bugreport")
    async def bugreport(self, ctx):
        """Open the bug report form."""
        settings = load("guild_settings.json").get(str(ctx.guild.id), {})
        if not settings.get("bug_report_channel"):
            return await ctx.reply("❌ No bug report channel set. Ask an admin to use `~setbugchannel`.")
        e = discord.Embed(
            title="🐛 Report a Bug",
            description=(
                "Found a bug in the bot? Let us know!\n\n"
                "Click the button below to fill out the bug report form.\n"
                "Please be as detailed as possible so we can reproduce and fix it."
            ),
            color=Config.COLOR_WARN,
        )
        await ctx.reply(embed=e, view=BugReportPanelView())

    @slash.command(name="bug", description="Report a bug in the bot.")
    async def bugreport_slash(self, interaction: discord.Interaction):
        settings = load("guild_settings.json").get(str(interaction.guild.id), {})
        if not settings.get("bug_report_channel"):
            return await interaction.response.send_message("❌ No bug report channel set. Ask an admin to use `/report setbugchannel`.", ephemeral=True)
        await interaction.response.send_modal(BugReportModal(interaction.guild))

    @commands.command(name="setbugchannel")
    @commands.has_permissions(administrator=True)
    async def setbugchannel(self, ctx, channel: discord.TextChannel):
        data = load("guild_settings.json")
        data.setdefault(str(ctx.guild.id), {})["bug_report_channel"] = channel.id
        save("guild_settings.json", data)
        await ctx.reply(f"✅ Bug reports will be sent to {channel.mention}.")

    @slash.command(name="setbugchannel", description="Set the bug report channel.")
    @app_commands.describe(channel="Channel for bug reports")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def setbugchannel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        ctx = await commands.Context.from_interaction(interaction)
        await self.setbugchannel.callback(self, ctx, channel)


async def setup(bot):
    await bot.add_cog(Reports(bot))
