"""
cogs/tickets.py
Full ticket system with category dropdown, per-type modals, claim, close with reason, transcript.
Per-category staff roles, type-specific overwrites, staff role check on all buttons.
All commands are grouped under /ticket <subcommand>.
Support timings embed shown on every new ticket — set via /ticket supporttimes.
"""

import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import io
import re
import aiohttp
from datetime import datetime, timezone, timedelta
from config import Config
from utils.data import load, save

TICKETS_FILE = "tickets.json"
AI_TICKETS_PER_DAY_LIMIT = 70     # Daily ticket creation limit

# Ticket Categories
TICKET_CATEGORIES = {
    "bug":        {"label": "Bug Report",          "description": "Report a bug or issue"},
    "cape":       {"label": "Cape Submit",         "description": "Submit or manage a cape"},
    "general":    {"label": "General Support",     "description": "Get help with general issues"},
    "partnership":{"label": "Partnership Request",  "description": "Apply for a partnership"},
    "ign":        {"label": "Claimed IGN Recovery", "description": "Recover a claimed IGN"},
}

# DM on response tracker
_dm_on_response: dict[int, bool] = {}

# Staff role check helper
def _is_staff(interaction: discord.Interaction, channel_id: int = None) -> bool:
    if interaction.user.guild_permissions.manage_channels:
        return True
    settings     = load("guild_settings.json").get(str(interaction.guild.id), {})
    global_roles = settings.get("ticket_staff_roles", [])
    type_roles   = []
    if channel_id:
        td   = _ticket_data(interaction.guild.id)
        info = td.get("open", {}).get(str(channel_id), {})
        cat  = info.get("category", "general")
        type_roles = settings.get("ticket_type_roles", {}).get(cat, [])
    all_roles = list(set(global_roles + type_roles))
    return any(r.id in all_roles for r in interaction.user.roles)

# Support timings helpers
def _parse_time(time_str: str) -> tuple[int, int] | None:
    time_str = time_str.strip()
    m = re.match(r'^(\d{1,2}):(\d{2})\s*(AM|PM)$', time_str, re.IGNORECASE)
    if m:
        h, mi, ampm = int(m.group(1)), int(m.group(2)), m.group(3).upper()
        if ampm == "PM" and h != 12:
            h += 12
        if ampm == "AM" and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return h, mi
    m = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return h, mi
    return None

def _is_within_support_hours(start_str: str, end_str: str) -> bool:
    start = _parse_time(start_str)
    end   = _parse_time(end_str)
    if not start or not end:
        return False
    now         = datetime.now(timezone.utc)
    now_mins    = now.hour * 60 + now.minute
    start_mins  = start[0] * 60 + start[1]
    end_mins    = end[0] * 60 + end[1]
    if start_mins <= end_mins:
        return start_mins <= now_mins < end_mins
    else:
        return now_mins >= start_mins or now_mins < end_mins

def _get_tickets_created_today(td) -> int:
    today = datetime.now(timezone.utc).date()
    count = 0
    for info in td.get("open", {}).values():
        opened_at_str = info.get("opened_at", "")
        if opened_at_str:
            try:
                opened_at = datetime.fromisoformat(opened_at_str).date()
                if opened_at == today:
                    count += 1
            except Exception:
                pass
    return count

# Data helpers
def _ticket_data(guild_id):
    data = load(TICKETS_FILE)
    return data.get(str(guild_id), {"counter": 0, "open": {}})

def _save_ticket(guild_id, td):
    data = load(TICKETS_FILE)
    data[str(guild_id)] = td
    save(TICKETS_FILE, data)

def _real_open_count(guild, td) -> int:
    return sum(
        1 for ch_id in td.get("open", {})
        if guild.get_channel(int(ch_id))
    )

# Transcript
async def _generate_transcript_url(channel):
    api_key = getattr(Config, "COOKIE_API_KEY", None)
    if not api_key or api_key == "YOUR_COOKIE_API_KEY_HERE":
        return None
    try:
        url     = f"https://api.cookie-api.com/api/transcript?channel_id={channel.id}"
        headers = {"Authorization": api_key, "Content-Type": "application/json"}
        payload = {"bot_token": Config.TOKEN}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("success"):
                        return data.get("url")
    except Exception as e:
        print(f"[Tickets] Transcript API error: {e}")
    return None

async def _generate_transcript_fallback(channel):
    lines = []
    async for msg in channel.history(limit=500, oldest_first=True):
        ts   = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
        text = msg.content or ""
        for a in msg.attachments:
            text += f" [Attachment: {a.url}]"
        lines.append(f"[{ts}] {msg.author.display_name}: {text}")
    content = "\n".join(lines)
    return discord.File(io.BytesIO(content.encode()), filename=f"transcript-{channel.name}.txt")

# Close logic
async def _do_close(guild, channel, closer, reason: str = None):
    td   = _ticket_data(guild.id)
    info = td.get("open", {}).get(str(channel.id))
    if not info:
        return

    settings  = load("guild_settings.json").get(str(guild.id), {})
    log_ch_id = settings.get("ticket_log_channel")
    log_ch    = guild.get_channel(int(log_ch_id)) if log_ch_id else None

    opener = guild.get_member(info["opener"])
    cat    = TICKET_CATEGORIES.get(info.get("category", "general"), {}).get("label", "Unknown")
    number = info.get("number", "?")

    transcript_url  = await _generate_transcript_url(channel)
    transcript_file = None
    if not transcript_url:
        transcript_file = await _generate_transcript_fallback(channel)

    if log_ch:
        e = discord.Embed(
            title=f"Ticket #{number:04d} Closed",
            color=Config.COLOR_ERR,
            timestamp=datetime.now(timezone.utc),
        )
        e.add_field(name="Opener",    value=opener.mention if opener else str(info["opener"]), inline=True)
        e.add_field(name="Category",  value=cat,            inline=True)
        e.add_field(name="Closed by", value=closer.mention, inline=True)
        if reason:
            e.add_field(name="Reason", value=reason, inline=False)
        if transcript_url:
            e.add_field(name="Transcript", value=f"[View Transcript]({transcript_url})", inline=False)

        if transcript_file:
            await log_ch.send(embed=e, file=transcript_file)
        else:
            await log_ch.send(embed=e)

    td["open"].pop(str(channel.id), None)
    _save_ticket(guild.id, td)
    await asyncio.sleep(3)
    try:
        await channel.delete(reason=f"Ticket closed by {closer}")
    except Exception:
        pass

# Views
class CloseReasonModal(discord.ui.Modal, title="Close Ticket with Reason"):
    reason = discord.ui.TextInput(
        label="Reason for closing", style=discord.TextStyle.paragraph,
        required=True, max_length=500,
    )

    def __init__(self, channel, closer):
        super().__init__()
        self.channel = channel
        self.closer  = closer

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await _do_close(interaction.guild, self.channel, self.closer, self.reason.value)


class CloseRequestOpenerView(discord.ui.View):
    def __init__(self, channel, opener_id):
        super().__init__(timeout=300)
        self.channel   = channel
        self.opener_id = opener_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.opener_id:
            await interaction.response.send_message("Only the ticket opener can respond.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Yes, close it", style=discord.ButtonStyle.danger)
    async def yes(self, interaction, button):
        await interaction.response.defer()
        await _do_close(interaction.guild, self.channel, interaction.user)
        self.stop()

    @discord.ui.button(label="No, keep it open", style=discord.ButtonStyle.secondary)
    async def no(self, interaction, button):
        await interaction.response.send_message("Ticket kept open.", ephemeral=True)
        self.stop()


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        td = _ticket_data(interaction.guild.id)
        info = td.get("open", {}).get(str(interaction.channel.id))
        if not info:
            await interaction.response.send_message("This channel is not an active ticket.", ephemeral=True)
            return False
        
        button_id = interaction.data.get("custom_id")
        
        if button_id == "ticket_dm_btn":
            if interaction.user.id != info["opener"]:
                await interaction.response.send_message("Only the ticket opener can toggle this.", ephemeral=True)
                return False
            return True
        
        if button_id in ["ticket_close_btn", "ticket_close_reason_btn", "ticket_claim_btn", "ticket_delete_btn"]:
            if not _is_staff(interaction, interaction.channel.id):
                await interaction.response.send_message("Only staff can use this button.", ephemeral=True)
                return False
            return True
        
        return True

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="ticket_close_btn")
    async def close_btn(self, interaction, button):
        await interaction.response.defer()
        await _do_close(interaction.guild, interaction.channel, interaction.user)

    @discord.ui.button(label="Close with Reason", style=discord.ButtonStyle.danger, custom_id="ticket_close_reason_btn")
    async def close_reason_btn(self, interaction, button):
        await interaction.response.send_modal(CloseReasonModal(interaction.channel, interaction.user))

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.primary, custom_id="ticket_claim_btn")
    async def claim_btn(self, interaction, button):
        await interaction.response.defer()
        td   = _ticket_data(interaction.guild.id)
        info = td.get("open", {}).get(str(interaction.channel.id), {})
        if info.get("claimed_by"):
            claimer = interaction.guild.get_member(info["claimed_by"])
            return await interaction.followup.send(
                f"Already claimed by {claimer.mention if claimer else 'someone'}.", ephemeral=True
            )
        info["claimed_by"] = interaction.user.id
        td["open"][str(interaction.channel.id)] = info
        _save_ticket(interaction.guild.id, td)
        await interaction.channel.edit(topic=f"Claimed by {interaction.user.display_name}")
        await interaction.followup.send(f"{interaction.user.mention} has claimed this ticket.")

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.secondary, custom_id="ticket_delete_btn")
    async def delete_btn(self, interaction, button):
        await interaction.response.defer()
        td = _ticket_data(interaction.guild.id)
        td["open"].pop(str(interaction.channel.id), None)
        _save_ticket(interaction.guild.id, td)
        await asyncio.sleep(2)
        try:
            await interaction.channel.delete()
        except Exception:
            await interaction.followup.send("Failed to delete channel.", ephemeral=True)

    @discord.ui.button(label="DM on response", style=discord.ButtonStyle.secondary, custom_id="ticket_dm_btn")
    async def dm_btn(self, interaction, button):
        current = _dm_on_response.get(interaction.user.id, False)
        _dm_on_response[interaction.user.id] = not current
        state = "enabled" if not current else "disabled"
        await interaction.response.send_message(f"DM on response {state}.", ephemeral=True)


# Support timings embed
async def _send_support_timing_embed(channel: discord.TextChannel):
    settings = load("guild_settings.json").get(str(channel.guild.id), {})
    start    = settings.get("support_start")
    end      = settings.get("support_end")
    if not start or not end:
        return

    if _is_within_support_hours(start, end):
        e = discord.Embed(
            title="We are currently working and will get to you soon",
            description="Please refrain from pinging staff multiple times.",
            color=Config.COLOR_OK,
        )
    else:
        e = discord.Embed(
            title="Sorry, we aren't working right now",
            description=f"Staff support timings are from **{start}** to **{end}** (UTC).",
            color=Config.COLOR_ERR,
        )
    await channel.send(embed=e)

# Shared embed sender
async def _send_ticket_embed(channel, opener, number, category_label, fields: dict):
    td         = _ticket_data(channel.guild.id)
    open_count = _real_open_count(channel.guild, td)
    e = discord.Embed(
        title=f"Ticket #{number:04d} — {category_label}",
        description=f"Welcome {opener.mention}! Staff will assist you shortly.\n**{open_count}** ticket(s) currently open.",
        color=Config.COLOR_INFO,
        timestamp=datetime.now(timezone.utc),
    )
    for name, value in fields.items():
        e.add_field(name=name, value=value or "—", inline=False)

    control_view = TicketControlView()
    await channel.send(embed=e, view=control_view)

    settings = load("guild_settings.json").get(str(channel.guild.id), {})
    td  = _ticket_data(channel.guild.id)
    cat = td.get("open", {}).get(str(channel.id), {}).get("category", "general")

    global_roles = settings.get("ticket_staff_roles", [])
    type_roles   = settings.get("ticket_type_roles", {}).get(cat, [])
    ping_ids       = type_roles if type_roles else global_roles
    valid_ping_ids = [rid for rid in ping_ids if channel.guild.get_role(int(rid))]
    if valid_ping_ids:
        mentions = " ".join(f"<@&{rid}>" for rid in valid_ping_ids)
        await channel.send(f"{mentions} — New {category_label} ticket!", allowed_mentions=discord.AllowedMentions(roles=True))

    await _send_support_timing_embed(channel)

# Create ticket channel
async def _create_ticket_channel(guild, author, category_key):
    td       = _ticket_data(guild.id)
    settings = load("guild_settings.json").get(str(guild.id), {})

    for ch_id, info in td.get("open", {}).items():
        if info.get("opener") == author.id:
            ch = guild.get_channel(int(ch_id))
            if ch:
                return None, ch

    tickets_today = _get_tickets_created_today(td)
    if tickets_today >= AI_TICKETS_PER_DAY_LIMIT:
        return "DAILY_LIMIT", None

    cat_name = settings.get("ticket_category", Config.TICKET_CATEGORY_NAME)
    category = discord.utils.get(guild.categories, name=cat_name)
    if not category:
        category = await guild.create_category(cat_name)

    td["counter"] = td.get("counter", 0) + 1
    number = td["counter"]
    slug   = category_key[:6]

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        author:             discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
    }
    for role_id in settings.get("ticket_staff_roles", []):
        role = guild.get_role(int(role_id))
        if role:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True)
    for role_id in settings.get("ticket_type_roles", {}).get(category_key, []):
        role = guild.get_role(int(role_id))
        if role:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True)

    channel = await category.create_text_channel(f"{slug}-{number:04d}", overwrites=overwrites)
    td.setdefault("open", {})[str(channel.id)] = {
        "opener":     author.id,
        "number":     number,
        "category":   category_key,
        "opened_at":  datetime.now(timezone.utc).isoformat(),
        "claimed_by": None,
    }
    _save_ticket(guild.id, td)
    return number, channel

# Category Dropdown
class TicketCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=info["label"], value=key, description=info["description"])
            for key, info in TICKET_CATEGORIES.items()
        ]
        super().__init__(
            placeholder="Select a ticket category...",
            min_values=1, max_values=1,
            options=options,
            custom_id="ticket_category_select",
        )

    async def callback(self, interaction: discord.Interaction):
        category_key = self.values[0]
        td = _ticket_data(interaction.guild.id)
        
        for ch_id, info in td.get("open", {}).items():
            if info.get("opener") == interaction.user.id:
                ch = interaction.guild.get_channel(int(ch_id))
                if ch:
                    return await interaction.response.send_message(
                        f"You already have an open ticket: {ch.mention}", ephemeral=True
                    )
        
        tickets_today = _get_tickets_created_today(td)
        if tickets_today >= AI_TICKETS_PER_DAY_LIMIT:
            return await interaction.response.send_message(
                f"Daily ticket limit reached ({AI_TICKETS_PER_DAY_LIMIT}). Please try again tomorrow.", ephemeral=True
            )
        
        modal_cls = CATEGORY_MODALS[category_key]
        await interaction.response.send_modal(modal_cls(interaction.guild, interaction.user, category_key))

# Per-Category Modals
class BugReportModal(discord.ui.Modal, title="Bug Report"):
    bug_description = discord.ui.TextInput(label="Describe the bug", style=discord.TextStyle.paragraph, required=True, max_length=500)
    reproduction = discord.ui.TextInput(label="How to reproduce", style=discord.TextStyle.paragraph, required=False, max_length=300)
    expected = discord.ui.TextInput(label="Expected behavior", style=discord.TextStyle.paragraph, required=False, max_length=300)

    def __init__(self, guild, author, category_key):
        super().__init__()
        self.guild = guild
        self.author = author
        self.category_key = category_key

    async def on_submit(self, interaction):
        try:
            result = await _create_ticket_channel(self.guild, self.author, self.category_key)
            if result[0] == "DAILY_LIMIT":
                return await interaction.response.send_message(f"Daily ticket limit reached.", ephemeral=True)
            number, channel = result
            if number is None:
                return await interaction.response.send_message(f"You already have an open ticket: {channel.mention}", ephemeral=True)
            await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)
            await _send_ticket_embed(channel, self.author, number, "Bug Report",
                {"Bug Description": self.bug_description.value, "Reproduction": self.reproduction.value or "Not specified", "Expected Behavior": self.expected.value or "Not specified"})
        except Exception as e:
            print(f"[Tickets] Error: {e}")
            await interaction.response.send_message("An error occurred.", ephemeral=True)

class CapeSubmitModal(discord.ui.Modal, title="Cape Submit"):
    cape_name = discord.ui.TextInput(label="Cape name", required=True, max_length=100)
    cape_link = discord.ui.TextInput(label="Cape image/design link", required=True, max_length=300)
    description = discord.ui.TextInput(label="Cape description", style=discord.TextStyle.paragraph, required=False, max_length=300)

    def __init__(self, guild, author, category_key):
        super().__init__()
        self.guild = guild
        self.author = author
        self.category_key = category_key

    async def on_submit(self, interaction):
        try:
            result = await _create_ticket_channel(self.guild, self.author, self.category_key)
            if result[0] == "DAILY_LIMIT":
                return await interaction.response.send_message(f"Daily ticket limit reached.", ephemeral=True)
            number, channel = result
            if number is None:
                return await interaction.response.send_message(f"You already have an open ticket: {channel.mention}", ephemeral=True)
            await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)
            await _send_ticket_embed(channel, self.author, number, "Cape Submit",
                {"Cape Name": self.cape_name.value, "Link": self.cape_link.value, "Description": self.description.value or "None provided"})
        except Exception as e:
            print(f"[Tickets] Error: {e}")
            await interaction.response.send_message("An error occurred.", ephemeral=True)

class GeneralSupportModal(discord.ui.Modal, title="General Support"):
    issue = discord.ui.TextInput(label="What do you need help with?", style=discord.TextStyle.paragraph, required=True, max_length=500)
    tried = discord.ui.TextInput(label="What have you already tried?", style=discord.TextStyle.paragraph, required=False, max_length=300)

    def __init__(self, guild, author, category_key):
        super().__init__()
        self.guild = guild
        self.author = author
        self.category_key = category_key

    async def on_submit(self, interaction):
        try:
            result = await _create_ticket_channel(self.guild, self.author, self.category_key)
            if result[0] == "DAILY_LIMIT":
                return await interaction.response.send_message(f"Daily ticket limit reached.", ephemeral=True)
            number, channel = result
            if number is None:
                return await interaction.response.send_message(f"You already have an open ticket: {channel.mention}", ephemeral=True)
            await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)
            await _send_ticket_embed(channel, self.author, number, "General Support",
                {"Issue": self.issue.value, "Already Tried": self.tried.value or "Not specified"})
        except Exception as e:
            print(f"[Tickets] Error: {e}")
            await interaction.response.send_message("An error occurred.", ephemeral=True)

class PartnershipModal(discord.ui.Modal, title="Partnership Request"):
    server_name  = discord.ui.TextInput(label="Your server name", required=True, max_length=100)
    invite       = discord.ui.TextInput(label="Invite link", required=True, max_length=200)
    member_count = discord.ui.TextInput(label="Member count", required=True, max_length=20)
    description  = discord.ui.TextInput(label="Brief description", style=discord.TextStyle.paragraph, required=True, max_length=400)

    def __init__(self, guild, author, category_key):
        super().__init__()
        self.guild = guild
        self.author = author
        self.category_key = category_key

    async def on_submit(self, interaction):
        try:
            result = await _create_ticket_channel(self.guild, self.author, self.category_key)
            if result[0] == "DAILY_LIMIT":
                return await interaction.response.send_message(f"Daily ticket limit reached.", ephemeral=True)
            number, channel = result
            if number is None:
                return await interaction.response.send_message(f"You already have an open ticket: {channel.mention}", ephemeral=True)
            await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)
            await _send_ticket_embed(channel, self.author, number, "Partnership Request",
                {"Server": self.server_name.value, "Invite": self.invite.value, "Members": self.member_count.value, "Description": self.description.value})
        except Exception as e:
            print(f"[Tickets] Error: {e}")
            await interaction.response.send_message("An error occurred.", ephemeral=True)

class IGNRecoveryModal(discord.ui.Modal, title="Claimed IGN Recovery"):
    ign_name = discord.ui.TextInput(label="Claimed IGN to recover", required=True, max_length=100)
    proof = discord.ui.TextInput(label="Proof of ownership", style=discord.TextStyle.paragraph, required=True, max_length=500)
    account_email = discord.ui.TextInput(label="Associated email", required=False, max_length=200)

    def __init__(self, guild, author, category_key):
        super().__init__()
        self.guild = guild
        self.author = author
        self.category_key = category_key

    async def on_submit(self, interaction):
        try:
            result = await _create_ticket_channel(self.guild, self.author, self.category_key)
            if result[0] == "DAILY_LIMIT":
                return await interaction.response.send_message(f"Daily ticket limit reached.", ephemeral=True)
            number, channel = result
            if number is None:
                return await interaction.response.send_message(f"You already have an open ticket: {channel.mention}", ephemeral=True)
            await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)
            await _send_ticket_embed(channel, self.author, number, "Claimed IGN Recovery",
                {"IGN": self.ign_name.value, "Proof": self.proof.value, "Email": self.account_email.value or "Not provided"})
        except Exception as e:
            print(f"[Tickets] Error: {e}")
            await interaction.response.send_message("An error occurred.", ephemeral=True)

CATEGORY_MODALS = {
    "bug":        BugReportModal,
    "cape":       CapeSubmitModal,
    "general":    GeneralSupportModal,
    "partnership": PartnershipModal,
    "ign":        IGNRecoveryModal,
}

class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect())

class Tickets(commands.Cog):
    """Advanced ticket system with category dropdown."""

    def __init__(self, bot):
        self.bot = bot
        bot.add_view(TicketPanelView())
        bot.add_view(TicketControlView())

    ticket = app_commands.Group(name="ticket", description="Ticket system commands")

    @ticket.command(name="setup", description="Send a ticket panel to a channel.")
    @app_commands.describe(channel="Channel to send the panel to", title="Title for the panel embed")
    @app_commands.default_permissions(administrator=True)
    async def ticket_setup(self, interaction: discord.Interaction, channel: discord.TextChannel = None, title: str = "Help Desk"):
        ch = channel or interaction.channel
        e = discord.Embed(
            title=title,
            description="Select a category below to create a ticket.",
            color=Config.COLOR_INFO,
        )
        await ch.send(embed=e, view=TicketPanelView())
        await interaction.response.send_message(f"Ticket panel sent to {ch.mention}.", ephemeral=True)

    @ticket.command(name="setcategory", description="Set the category name for ticket channels.")
    @app_commands.describe(category_name="Category name (e.g. Tickets)")
    @app_commands.default_permissions(administrator=True)
    async def ticket_setcategory(self, interaction: discord.Interaction, category_name: str):
        data = load("guild_settings.json")
        data.setdefault(str(interaction.guild.id), {})["ticket_category"] = category_name
        save("guild_settings.json", data)
        await interaction.response.send_message(f"Ticket category set to **{category_name}**.", ephemeral=True)

    @ticket.command(name="supporttimes", description="Set staff support hours.")
    @app_commands.describe(start="Start time (e.g. 9:00 AM)", end="End time (e.g. 5:00 PM)")
    @app_commands.default_permissions(administrator=True)
    async def ticket_supporttimes(self, interaction: discord.Interaction, start: str, end: str):
        if not _parse_time(start) or not _parse_time(end):
            return await interaction.response.send_message("Invalid time format.", ephemeral=True)
        data = load("guild_settings.json")
        gd = data.setdefault(str(interaction.guild.id), {})
        gd["support_start"] = start
        gd["support_end"] = end
        save("guild_settings.json", data)
        await interaction.response.send_message(f"Support times: **{start}** → **{end}** (UTC).", ephemeral=True)

    @ticket.command(name="removesupporttimes", description="Remove support timings.")
    @app_commands.default_permissions(administrator=True)
    async def ticket_removesupporttimes(self, interaction: discord.Interaction):
        data = load("guild_settings.json")
        gd = data.get(str(interaction.guild.id), {})
        gd.pop("support_start", None)
        gd.pop("support_end", None)
        save("guild_settings.json", data)
        await interaction.response.send_message("Support timings removed.", ephemeral=True)

    @ticket.command(name="logchannel", description="Set the ticket log channel.")
    @app_commands.describe(channel="Channel for ticket logs")
    @app_commands.default_permissions(administrator=True)
    async def ticket_logchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        data = load("guild_settings.json")
        data.setdefault(str(interaction.guild.id), {})["ticket_log_channel"] = channel.id
        save("guild_settings.json", data)
        await interaction.response.send_message(f"Ticket logs → {channel.mention}.", ephemeral=True)

    @ticket.command(name="globalstaffrole", description="Add/remove a global ticket staff role.")
    @app_commands.describe(role="Role to add/remove")
    @app_commands.default_permissions(administrator=True)
    async def ticket_globalstaffrole(self, interaction: discord.Interaction, role: discord.Role):
        data = load("guild_settings.json")
        gd = data.setdefault(str(interaction.guild.id), {})
        roles = gd.setdefault("ticket_staff_roles", [])
        if role.id in roles:
            roles.remove(role.id)
            msg = f"Removed {role.mention} from ticket staff."
        else:
            roles.append(role.id)
            msg = f"Added {role.mention} as ticket staff."
        save("guild_settings.json", data)
        await interaction.response.send_message(msg, ephemeral=True)

    @ticket.command(name="typerole", description="Add/remove a staff role for a specific ticket type.")
    @app_commands.describe(ticket_type="Ticket category", role="Role to add/remove")
    @app_commands.choices(ticket_type=[app_commands.Choice(name=v["label"], value=k) for k, v in TICKET_CATEGORIES.items()])
    @app_commands.default_permissions(administrator=True)
    async def ticket_typerole(self, interaction: discord.Interaction, ticket_type: str, role: discord.Role):
        data = load("guild_settings.json")
        gd = data.setdefault(str(interaction.guild.id), {})
        type_roles = gd.setdefault("ticket_type_roles", {})
        roles = type_roles.setdefault(ticket_type, [])
        if role.id in roles:
            roles.remove(role.id)
            msg = f"Removed {role.mention} from **{ticket_type}** staff."
        else:
            roles.append(role.id)
            msg = f"Added {role.mention} to **{ticket_type}** staff."
        save("guild_settings.json", data)
        await interaction.response.send_message(msg, ephemeral=True)

    @ticket.command(name="typeinfo", description="Show role assignments per ticket type.")
    @app_commands.default_permissions(manage_channels=True)
    async def ticket_typeinfo(self, interaction: discord.Interaction):
        settings = load("guild_settings.json").get(str(interaction.guild.id), {})
        type_roles = settings.get("ticket_type_roles", {})
        global_roles = settings.get("ticket_staff_roles", [])
        guild = interaction.guild
        valid_global = [r for r in global_roles if guild.get_role(int(r))]
        global_mentions = " ".join(f"<@&{r}>" for r in valid_global) or "None"
        e = discord.Embed(title="Ticket Type Role Config", color=Config.COLOR_INFO)
        e.add_field(name="Global Staff", value=global_mentions, inline=False)
        for key, info in TICKET_CATEGORIES.items():
            roles = type_roles.get(key, [])
            valid = [r for r in roles if guild.get_role(int(r))]
            mentions = " ".join(f"<@&{r}>" for r in valid) if valid else "Same as global"
            e.add_field(name=info["label"], value=mentions, inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @ticket.command(name="close", description="Close the current ticket.")
    async def ticket_close(self, interaction: discord.Interaction):
        td = _ticket_data(interaction.guild.id)
        if str(interaction.channel.id) not in td.get("open", {}):
            return await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
        info = td["open"][str(interaction.channel.id)]
        if interaction.user.id != info["opener"] and not _is_staff(interaction, interaction.channel.id):
            return await interaction.response.send_message("Only the opener or staff can close.", ephemeral=True)
        await interaction.response.defer()
        await _do_close(interaction.guild, interaction.channel, interaction.user)

    @ticket.command(name="closerequest", description="Request the opener to confirm closing.")
    async def ticket_closerequest(self, interaction: discord.Interaction):
        td = _ticket_data(interaction.guild.id)
        if str(interaction.channel.id) not in td.get("open", {}):
            return await interaction.response.send_message("Not a ticket channel.", ephemeral=True)
        info = td["open"][str(interaction.channel.id)]
        opener = interaction.guild.get_member(info["opener"])
        await interaction.response.send_message(
            f"{opener.mention if opener else 'Opener'} — {interaction.user.mention} requests closing this ticket.",
            view=CloseRequestOpenerView(interaction.channel, info["opener"]),
        )

    @ticket.command(name="claim", description="Claim the current ticket.")
    @app_commands.default_permissions(manage_channels=True)
    async def ticket_claim(self, interaction: discord.Interaction):
        td = _ticket_data(interaction.guild.id)
        if str(interaction.channel.id) not in td.get("open", {}):
            return await interaction.response.send_message("Not a ticket channel.", ephemeral=True)
        info = td["open"][str(interaction.channel.id)]
        if info.get("claimed_by"):
            claimer = interaction.guild.get_member(info["claimed_by"])
            return await interaction.response.send_message(f"Already claimed by {claimer.mention if claimer else 'someone'}.", ephemeral=True)
        info["claimed_by"] = interaction.user.id
        td["open"][str(interaction.channel.id)] = info
        _save_ticket(interaction.guild.id, td)
        await interaction.channel.edit(topic=f"Claimed by {interaction.user.display_name}")
        await interaction.response.send_message(f"{interaction.user.mention} claimed this ticket.")

    @ticket.command(name="add", description="Add a member to this ticket.")
    @app_commands.describe(member="Member to add")
    @app_commands.default_permissions(manage_channels=True)
    async def ticket_add(self, interaction: discord.Interaction, member: discord.Member):
        td = _ticket_data(interaction.guild.id)
        if str(interaction.channel.id) not in td.get("open", {}):
            return await interaction.response.send_message("Not a ticket channel.", ephemeral=True)
        await interaction.channel.set_permissions(member, read_messages=True, send_messages=True)
        await interaction.response.send_message(f"Added {member.mention} to the ticket.")

    @ticket.command(name="remove", description="Remove a member from this ticket.")
    @app_commands.describe(member="Member to remove")
    @app_commands.default_permissions(manage_channels=True)
    async def ticket_remove(self, interaction: discord.Interaction, member: discord.Member):
        td = _ticket_data(interaction.guild.id)
        if str(interaction.channel.id) not in td.get("open", {}):
            return await interaction.response.send_message("Not a ticket channel.", ephemeral=True)
        await interaction.channel.set_permissions(member, overwrite=None)
        await interaction.response.send_message(f"Removed {member.mention} from the ticket.")

    @ticket.command(name="list", description="List all open tickets.")
    @app_commands.default_permissions(manage_channels=True)
    async def ticket_list(self, interaction: discord.Interaction):
        td = _ticket_data(interaction.guild.id)
        open_tickets = td.get("open", {})
        if not open_tickets:
            return await interaction.response.send_message("No open tickets.", ephemeral=True)
        lines = []
        for ch_id, info in open_tickets.items():
            ch = interaction.guild.get_channel(int(ch_id))
            opener = interaction.guild.get_member(info["opener"])
            cat = TICKET_CATEGORIES.get(info.get("category", "general"), {}).get("label", "Unknown")
            if ch:
                lines.append(f"• {ch.mention} — {opener.mention if opener else 'Unknown'} — {cat}")
        e = discord.Embed(title=f"Open Tickets — {len(lines)}", description="\n".join(lines), color=Config.COLOR_INFO)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @ticket.command(name="cleanup", description="Remove stale ticket records.")
    @app_commands.default_permissions(manage_channels=True)
    async def ticket_cleanup(self, interaction: discord.Interaction):
        td = _ticket_data(interaction.guild.id)
        stale = [ch_id for ch_id in td.get("open", {}) if not interaction.guild.get_channel(int(ch_id))]
        if not stale:
            return await interaction.response.send_message("Memory is clean.", ephemeral=True)
        for ch_id in stale:
            td["open"].pop(ch_id, None)
        _save_ticket(interaction.guild.id, td)
        await interaction.response.send_message(f"Removed **{len(stale)}** stale record(s).", ephemeral=True)

    @ticket.command(name="opentickets", description="Show open ticket count.")
    @app_commands.default_permissions(manage_channels=True)
    async def ticket_opentickets(self, interaction: discord.Interaction):
        td = _ticket_data(interaction.guild.id)
        real_count = _real_open_count(interaction.guild, td)
        await interaction.response.send_message(f"**{real_count}** ticket(s) currently open.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        
        td   = _ticket_data(message.guild.id)
        info = td.get("open", {}).get(str(message.channel.id))
        if not info:
            return
        
        opener_id = info.get("opener")
        if not opener_id or message.author.id == opener_id:
            return
        
        settings     = load("guild_settings.json").get(str(message.guild.id), {})
        global_roles = settings.get("ticket_staff_roles", [])
        type_roles   = settings.get("ticket_type_roles", {}).get(info.get("category", "general"), [])
        all_roles    = list(set(global_roles + type_roles))
        is_staff = (
            message.author.guild_permissions.manage_channels or
            any(r.id in all_roles for r in message.author.roles)
        )
        
        if not is_staff:
            return
        
        # DM on response feature
        opener = message.guild.get_member(opener_id)
        if opener and _dm_on_response.get(opener_id, False):
            try:
                e = discord.Embed(
                    title="Staff responded in your ticket!",
                    description=f"**{message.author.display_name}** replied in **#{message.channel.name}**:\n\n{message.content[:500]}",
                    color=Config.COLOR_INFO,
                )
                e.add_field(name="Jump to ticket", value=f"[Click here]({message.jump_url})")
                await opener.send(embed=e)
            except Exception:
                pass


async def setup(bot):
    await bot.add_cog(Tickets(bot))