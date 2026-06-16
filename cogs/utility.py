"""
cogs/utility.py
Slash group: /utility
General-purpose utility commands.
Prefix commands still work with ~
"""

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime, timezone
from config import Config
from utils.data import load, save

AFK_FILE = "afk.json"


def _get_afk(guild_id: int) -> dict:
    return load(AFK_FILE).get(str(guild_id), {})


def _save_afk(guild_id: int, afk: dict):
    data = load(AFK_FILE)
    data[str(guild_id)] = afk
    save(AFK_FILE, data)


# ---------------------------------------------------------------------------
# Help UI
# ---------------------------------------------------------------------------

class HelpSelect(discord.ui.Select):
    def __init__(self, cog_pages: dict):
        self.cog_pages = cog_pages
        options = [
            discord.SelectOption(
                label=name,
                description=cog_pages[name]["desc"][:100],
                emoji=cog_pages[name].get("emoji", "🔹"),
            )
            for name in cog_pages
        ]
        super().__init__(placeholder="Select a category...", options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        page = self.cog_pages[self.values[0]]
        await interaction.response.edit_message(embed=page["embed"])


class HelpView(discord.ui.View):
    def __init__(self, main_embed: discord.Embed, cog_pages: dict, author_id: int):
        super().__init__(timeout=120)
        self.author_id  = author_id
        self.main_embed = main_embed
        self.add_item(HelpSelect(cog_pages))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the command caller can use this menu.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Home", style=discord.ButtonStyle.secondary, row=1, emoji="🏠")
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.main_embed)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Utility(commands.Cog):
    """General utility commands."""

    slash = app_commands.Group(name="utility", description="General utility commands")

    def __init__(self, bot):
        self.bot = bot

    # ── HELP ──────────────────────────────────────────────────────────────────

    @commands.command(name="help")
    async def help(self, ctx, *, command_name: str = None):
        prefix = Config.PREFIX

        if command_name:
            cmd = self.bot.get_command(command_name)
            if not cmd:
                return await ctx.reply("Command `{}{}` not found.".format(prefix, command_name))
            e = discord.Embed(
                title="Help: `{}{}`".format(prefix, cmd.name),
                description=cmd.help or "No description.",
                color=Config.COLOR_INFO,
            )
            if cmd.aliases:
                e.add_field(name="Aliases", value=", ".join("`{}`".format(a) for a in cmd.aliases), inline=False)
            return await ctx.reply(embed=e)

        cog_data = {
            "Moderation": {
                "emoji": "⚔️",
                "desc": "Kick, ban, warn, mute and more",
                "cmds": ["kick","ban","unban","mute","unmute","warn","warnings","clearwarns","purge","lock","unlock","lockdown","unlockdown","nick","role","deafen","move","roleall","setmodlog","slowmode"],
            },
            "Music": {
                "emoji": "🎵",
                "desc": "Full music player with queue",
                "cmds": ["play","pause","resume","skip","stop","queue","nowplaying","volume","loop","shuffle","remove","disconnect"],
            },
            "Tickets": {
                "emoji": "🎟️",
                "desc": "Advanced ticket system",
                "cmds": ["ticketsetup","ticketlogchannel","ticketstaffrole","close","closerequest","add","removeuser","opentickets"],
            },
            "Utility": {
                "emoji": "🔧",
                "desc": "General utility tools",
                "cmds": ["ping","userinfo","serverinfo","avatar","banner","roleinfo","channelinfo","invite","poll","remind","afk","timestamp","emojis","membercount"],
            },
            "Fun": {
                "emoji": "🎲",
                "desc": "Fun and entertainment",
                "cmds": ["8ball","coinflip","dice","rps","choose","reverse","mock","emojify","rate","fact","roast","compliment","ship","trivia"],
            },
            "Economy": {
                "emoji": "💰",
                "desc": "Full economy system",
                "cmds": ["balance","daily","work","pay","deposit","withdraw","rob","gamble","slots","shop","buy","inventory","richest"],
            },
            "Leveling": {
                "emoji": "⭐",
                "desc": "XP and level system",
                "cmds": ["rank","levels","setlevelchannel","setxp","levelrole","removelevelrole","levelroles","xpblacklist"],
            },
            "Giveaway": {
                "emoji": "🎉",
                "desc": "Giveaway management",
                "cmds": ["gstart","gend","greroll","glist"],
            },
            "AutoMod": {
                "emoji": "🛡️",
                "desc": "Auto-moderation system",
                "cmds": ["automod"],
            },
            "AI": {
                "emoji": "🤖",
                "desc": "Free AI via Groq",
                "cmds": ["ask","chat","clearchat","translate","summarize","story","airoast"],
            },
            "Logging": {
                "emoji": "📝",
                "desc": "Server event logging",
                "cmds": ["setlogchannel","logconfig","logtoggle"],
            },
            "Welcome": {
                "emoji": "👋",
                "desc": "Welcome and auto-role system",
                "cmds": ["setwelcome","setgoodbye","welcomemsg","goodbyemsg","welcomedm","autorole","autoroles","welcomeembed","previewwelcome"],
            },
            "React Roles": {
                "emoji": "🎭",
                "desc": "Reaction role system",
                "cmds": ["rradd","rrremove","rrlist","rrclear","rrpanel"],
            },
            "Invites": {
                "emoji": "📨",
                "desc": "Invite tracking and message stats",
                "cmds": ["invites","invitestats","inviteinfo","invitedmembers","resetinvites","setinvitelog","messagestats","msgleaderboard"],
            },
            "JTC": {
                "emoji": "🔊",
                "desc": "Join-to-Create voice system",
                "cmds": ["jtcsetup","jtcname","jtclimit","jtcrename","jtclock","jtcunlock","jtchide","jtcreveal","jtckick","jtcallow","jtcowner","jtcinfo"],
            },
            "Reports": {
                "emoji": "🚨",
                "desc": "Reports, suggestions and bugs",
                "cmds": ["report","setreportchannel","reports","suggestion","setsuggestions","suggestions","bugreport","setbugchannel"],
            },
            "Admin": {
                "emoji": "📋",
                "desc": "Server config, announcements and admin tools",
                "cmds": ["serverconfig","adminreset","botperms","announce","channeldelay","botnick"],
            },
            "Embed": {
                "emoji": "🖼️",
                "desc": "Rich embed builder and scheduled DM-all",
                "cmds": ["/embed send","/embed quick","/embed preview","/embed edit","/embed addfield","/embed clearfields","/embed setauthor","/embed json","/embed dmall","/embed dmall_cancel","/embed dmall_status"],
            },
            "Minecraft": {
                "emoji": "🎮",
                "desc": "Minecraft server integration via RCON",
                "cmds": ["/mc setup","/mc servers","/mc remove","/mc status","/mc linkaccount","/mc unlinkaccount","/mc whois","/mc whitelist","/mc whitelist_list","/mc say","/mc tell","/mc kick","/mc ban","/mc unban","/mc op","/mc deop","/mc gamemode","/mc give","/mc tp","/mc time","/mc weather","/mc difficulty","/mc seed","/mc save","/mc run"],
            },
            "Applications": {
                "emoji": "📄",
                "desc": "Advanced application forms — no DMs required",
                "cmds": ["/application create","/application addquestion","/application removequestion","/application editquestion","/application reorderquestion","/application preview","/application list","/application open","/application close","/application delete","/application setlogchannel","/application setrole","/application post","/application apply"],
            },
        }

        main_embed = discord.Embed(
            title="{} Help".format(self.bot.user.name),
            description="Use `{}help <command>` for details on a specific command.\nSelect a category below to browse.".format(prefix),
            color=Config.COLOR_INFO,
        )
        if self.bot.user.avatar:
            main_embed.set_thumbnail(url=self.bot.user.avatar.url)
        main_embed.set_footer(text="Prefix: {} | {} commands loaded | Slash commands start with /".format(prefix, len(self.bot.commands)))

        cog_pages = {}
        for cog_name, info in cog_data.items():
            lines = []
            for c in info["cmds"]:
                if c.startswith("/"):
                    lines.append("`{}`".format(c))
                else:
                    lines.append("`{}{}`".format(prefix, c))
            e = discord.Embed(
                title="{} {} Commands".format(info["emoji"], cog_name),
                description="\n".join(lines),
                color=Config.COLOR_INFO,
            )
            e.set_footer(text="Use {}help <command> for prefix commands | Slash commands start with /".format(prefix))
            cog_pages[cog_name] = {"emoji": info["emoji"], "desc": info["desc"], "embed": e}

        for name, info in cog_data.items():
            main_embed.add_field(
                name="{} {}".format(info["emoji"], name),
                value=info["desc"],
                inline=True,
            )

        view = HelpView(main_embed, cog_pages, ctx.author.id)
        await ctx.reply(embed=main_embed, view=view)

    @slash.command(name="help", description="Show the help menu.")
    async def help_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.help.callback(self, ctx)

    # ── PING ──────────────────────────────────────────────────────────────────

    @commands.command(name="ping")
    async def ping(self, ctx):
        start = discord.utils.utcnow()
        msg   = await ctx.reply("Pinging...")
        end   = discord.utils.utcnow()
        rtt   = (end - start).total_seconds() * 1000
        ws    = round(ctx.bot.latency * 1000)
        e = discord.Embed(title="Pong!", color=Config.COLOR_INFO)
        e.add_field(name="WebSocket",  value="`{}ms`".format(ws))
        e.add_field(name="Round-Trip", value="`{:.0f}ms`".format(rtt))
        await msg.edit(content=None, embed=e)

    @slash.command(name="ping", description="Check the bot latency.")
    async def ping_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.ping.callback(self, ctx)

    # ── USERINFO ──────────────────────────────────────────────────────────────

    @commands.command(name="userinfo", aliases=["ui", "whois"])
    async def userinfo(self, ctx, member: discord.Member = None):
        m     = member or ctx.author
        roles = [r.mention for r in m.roles if r != ctx.guild.default_role]
        joined = discord.utils.format_dt(m.joined_at, "R") if m.joined_at else "Unknown"
        e = discord.Embed(title=str(m), color=m.color or Config.COLOR_INFO)
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name="ID",         value=str(m.id))
        e.add_field(name="Bot",        value="Yes" if m.bot else "No")
        e.add_field(name="Joined",     value=joined)
        e.add_field(name="Registered", value=discord.utils.format_dt(m.created_at, "R"))
        e.add_field(name="Status",     value=str(m.status).title())
        e.add_field(name="Top Role",   value=m.top_role.mention)
        if roles:
            e.add_field(
                name="Roles ({})".format(len(roles)),
                value=" ".join(roles[:15]) + ("..." if len(roles) > 15 else ""),
                inline=False,
            )
        await ctx.reply(embed=e)

    @slash.command(name="userinfo", description="View detailed info about a member.")
    @app_commands.describe(member="Member to look up (leave empty for yourself)")
    async def userinfo_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.userinfo.callback(self, ctx, member)

    # ── SERVERINFO ────────────────────────────────────────────────────────────

    @commands.command(name="serverinfo", aliases=["si", "guildinfo"])
    async def serverinfo(self, ctx):
        g      = ctx.guild
        bots   = sum(m.bot for m in g.members)
        online = sum(m.status != discord.Status.offline and not m.bot for m in g.members)
        e = discord.Embed(title=g.name, color=Config.COLOR_INFO)
        if g.icon:
            e.set_thumbnail(url=g.icon.url)
        e.add_field(name="Owner",    value=g.owner.mention if g.owner else "Unknown")
        e.add_field(name="ID",       value=str(g.id))
        e.add_field(name="Created",  value=discord.utils.format_dt(g.created_at, "R"))
        e.add_field(name="Members",  value="{:,} ({} bots)".format(g.member_count, bots))
        e.add_field(name="Online",   value="{:,}".format(online))
        e.add_field(name="Channels", value="{} text | {} voice".format(len(g.text_channels), len(g.voice_channels)))
        e.add_field(name="Roles",    value=str(len(g.roles)))
        e.add_field(name="Emojis",   value=str(len(g.emojis)))
        e.add_field(name="Boosts",   value="Level {} ({} boosts)".format(g.premium_tier, g.premium_subscription_count))
        await ctx.reply(embed=e)

    @slash.command(name="serverinfo", description="View information about this server.")
    async def serverinfo_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.serverinfo.callback(self, ctx)

    # ── AVATAR ────────────────────────────────────────────────────────────────

    @commands.command(name="avatar", aliases=["av", "pfp"])
    async def avatar(self, ctx, member: discord.Member = None):
        m = member or ctx.author
        e = discord.Embed(title="{}'s Avatar".format(m.display_name), color=Config.COLOR_INFO)
        e.set_image(url=m.display_avatar.url)
        e.description = "[PNG]({}) | [JPG]({}) | [WEBP]({})".format(
            m.display_avatar.with_format("png").url,
            m.display_avatar.with_format("jpg").url,
            m.display_avatar.with_format("webp").url,
        )
        await ctx.reply(embed=e)

    @slash.command(name="avatar", description="Show a member's avatar.")
    @app_commands.describe(member="Member to show avatar for")
    async def avatar_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.avatar.callback(self, ctx, member)

    # ── BANNER ────────────────────────────────────────────────────────────────

    @commands.command(name="banner")
    async def banner(self, ctx, member: discord.Member = None):
        m    = member or ctx.author
        user = await self.bot.fetch_user(m.id)
        if not user.banner:
            return await ctx.reply("**{}** has no banner.".format(m))
        e = discord.Embed(title="{}'s Banner".format(m.display_name), color=Config.COLOR_INFO)
        e.set_image(url=user.banner.url)
        await ctx.reply(embed=e)

    @slash.command(name="banner", description="Show a member's banner.")
    @app_commands.describe(member="Member to show banner for")
    async def banner_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.banner.callback(self, ctx, member)

    # ── ROLEINFO ──────────────────────────────────────────────────────────────

    @commands.command(name="roleinfo")
    async def roleinfo(self, ctx, role: discord.Role):
        perms = [p.replace("_", " ").title() for p, v in role.permissions if v]
        e = discord.Embed(title="Role: {}".format(role.name), color=role.color or Config.COLOR_INFO)
        e.add_field(name="ID",          value=str(role.id))
        e.add_field(name="Color",       value=str(role.color))
        e.add_field(name="Mentionable", value="Yes" if role.mentionable else "No")
        e.add_field(name="Hoisted",     value="Yes" if role.hoist else "No")
        e.add_field(name="Members",     value=str(len(role.members)))
        e.add_field(name="Created",     value=discord.utils.format_dt(role.created_at, "R"))
        if perms:
            e.add_field(name="Key Permissions", value=", ".join(perms[:10]), inline=False)
        await ctx.reply(embed=e)

    @slash.command(name="roleinfo", description="Show info about a role.")
    @app_commands.describe(role="Role to look up")
    async def roleinfo_slash(self, interaction: discord.Interaction, role: discord.Role):
        ctx = await commands.Context.from_interaction(interaction)
        await self.roleinfo.callback(self, ctx, role)

    # ── CHANNELINFO ───────────────────────────────────────────────────────────

    @commands.command(name="channelinfo", aliases=["ci"])
    async def channelinfo(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        e = discord.Embed(title="#{}`".format(ch.name), color=Config.COLOR_INFO)
        e.add_field(name="ID",       value=str(ch.id))
        e.add_field(name="Type",     value=str(ch.type).replace("_", " ").title())
        e.add_field(name="Category", value=ch.category.name if ch.category else "None")
        e.add_field(name="NSFW",     value="Yes" if ch.is_nsfw() else "No")
        e.add_field(name="Created",  value=discord.utils.format_dt(ch.created_at, "R"))
        if isinstance(ch, discord.TextChannel):
            e.add_field(name="Slowmode", value="{}s".format(ch.slowmode_delay) if ch.slowmode_delay else "Off")
            e.add_field(name="Topic",    value=ch.topic or "None", inline=False)
        await ctx.reply(embed=e)

    @slash.command(name="channelinfo", description="Show info about a channel.")
    @app_commands.describe(channel="Channel to look up (defaults to current)")
    async def channelinfo_slash(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.channelinfo.callback(self, ctx, channel)

    # ── INVITE ────────────────────────────────────────────────────────────────

    @commands.command(name="invite")
    async def invite(self, ctx):
        perms = discord.Permissions(
            kick_members=True, ban_members=True, manage_channels=True,
            manage_guild=True, add_reactions=True, view_channel=True,
            send_messages=True, manage_messages=True, embed_links=True,
            attach_files=True, read_message_history=True, mention_everyone=False,
            connect=True, speak=True, move_members=True, manage_roles=True,
            moderate_members=True,
        )
        url = discord.utils.oauth_url(self.bot.user.id, permissions=perms)
        e = discord.Embed(
            title="Invite Me!",
            description="[Click here to invite {}]({})".format(self.bot.user.name, url),
            color=Config.COLOR_INFO,
        )
        await ctx.reply(embed=e)

    @slash.command(name="invite", description="Get the bot invite link.")
    async def invite_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.invite.callback(self, ctx)

    # ── POLL ──────────────────────────────────────────────────────────────────

    @commands.command(name="poll")
    async def poll(self, ctx, question: str, *options: str):
        if len(options) < 2:
            return await ctx.reply("Provide at least 2 options.")
        if len(options) > 10:
            return await ctx.reply("Maximum 10 options.")
        emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        desc   = "\n".join("{} {}".format(emojis[i], opt) for i, opt in enumerate(options))
        e = discord.Embed(title=question, description=desc, color=Config.COLOR_INFO)
        e.set_footer(text="Poll by {}".format(ctx.author.display_name))
        msg = await ctx.reply(embed=e)
        for i in range(len(options)):
            await msg.add_reaction(emojis[i])

    @slash.command(name="poll", description="Create a poll with up to 10 options.")
    @app_commands.describe(question="Poll question", options="Options separated by commas")
    async def poll_slash(self, interaction: discord.Interaction, question: str, options: str):
        ctx  = await commands.Context.from_interaction(interaction)
        opts = [o.strip() for o in options.split(",") if o.strip()]
        await self.poll.callback(self, ctx, question, *opts)

    # ── REMIND ────────────────────────────────────────────────────────────────

    @commands.command(name="remind", aliases=["remindme"])
    async def remind(self, ctx, time: str, *, reminder: str):
        units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        unit  = time[-1].lower()
        if unit not in units or not time[:-1].isdigit():
            return await ctx.reply("Invalid time format. Use `10s`, `5m`, `2h`, `1d`.")
        seconds = int(time[:-1]) * units[unit]
        if seconds > 2592000:
            return await ctx.reply("Maximum reminder time is 30 days.")
        author  = ctx.author
        channel = ctx.channel
        await ctx.reply("I'll remind you in **{}**: *{}*".format(time, reminder))
        await asyncio.sleep(seconds)
        try:
            await channel.send("{} Reminder: **{}**".format(author.mention, reminder))
        except Exception:
            try:
                await author.send("Reminder: **{}**".format(reminder))
            except Exception:
                pass

    @slash.command(name="remind", description="Set a reminder.")
    @app_commands.describe(time="Duration e.g. 10m, 2h, 1d", reminder="What to remind you about")
    async def remind_slash(self, interaction: discord.Interaction, time: str, reminder: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.remind.callback(self, ctx, time, reminder=reminder)

    # ── AFK ───────────────────────────────────────────────────────────────────

    @commands.command(name="afk")
    async def afk(self, ctx, *, reason: str = "AFK"):
        afk = _get_afk(ctx.guild.id)
        afk[str(ctx.author.id)] = {"reason": reason, "time": discord.utils.utcnow().isoformat()}
        _save_afk(ctx.guild.id, afk)
        await ctx.reply("You are now AFK: *{}*".format(reason))

    @slash.command(name="afk", description="Set yourself as AFK with an optional reason.")
    @app_commands.describe(reason="Why you're going AFK")
    async def afk_slash(self, interaction: discord.Interaction, reason: str = "AFK"):
        ctx = await commands.Context.from_interaction(interaction)
        await self.afk.callback(self, ctx, reason=reason)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Skip counting channel to avoid interfering with CountingListener
        from utils.data import load as _load
        counting_data = _load("counting.json").get(str(message.guild.id), {})
        if counting_data.get("channel") and message.channel.id == counting_data["channel"]:
            return

        afk = _get_afk(message.guild.id)

        if str(message.author.id) in afk:
            del afk[str(message.author.id)]
            _save_afk(message.guild.id, afk)
            try:
                await message.reply("Welcome back! Your AFK status has been removed.", delete_after=5)
            except Exception:
                pass

        for m in message.mentions:
            if str(m.id) in afk:
                info = afk[str(m.id)]
                try:
                    afk_time = discord.utils.format_dt(
                        datetime.fromisoformat(info["time"]), "R"
                    )
                    await message.reply(
                        "**{}** is AFK {}: *{}*".format(m.display_name, afk_time, info["reason"]),
                        delete_after=10,
                    )
                except Exception:
                    pass

    # ── TIMESTAMP ─────────────────────────────────────────────────────────────

    @commands.command(name="timestamp")
    async def timestamp(self, ctx, date: str):
        try:
            dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            ts = int(dt.timestamp())
            e  = discord.Embed(title="Timestamp", color=Config.COLOR_INFO)
            e.add_field(name="Input",          value=date)
            e.add_field(name="Unix",           value="`{}`".format(ts))
            e.add_field(name="Short Date",     value=discord.utils.format_dt(dt, "d"))
            e.add_field(name="Long Date+Time", value=discord.utils.format_dt(dt, "f"))
            e.add_field(name="Relative",       value=discord.utils.format_dt(dt, "R"))
            await ctx.reply(embed=e)
        except ValueError:
            await ctx.reply("Invalid date format. Use `YYYY-MM-DD`.")

    @slash.command(name="timestamp", description="Get Unix timestamp for a date.")
    @app_commands.describe(date="Date in YYYY-MM-DD format")
    async def timestamp_slash(self, interaction: discord.Interaction, date: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.timestamp.callback(self, ctx, date)

    # ── EMOJIS ────────────────────────────────────────────────────────────────

    @commands.command(name="emojis")
    async def emojis(self, ctx):
        if not ctx.guild.emojis:
            return await ctx.reply("This server has no custom emojis.")
        pages = [ctx.guild.emojis[i:i+40] for i in range(0, len(ctx.guild.emojis), 40)]
        for page in pages[:2]:
            await ctx.reply(" ".join(str(e) for e in page))

    @slash.command(name="emojis", description="List all custom server emojis.")
    async def emojis_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.emojis.callback(self, ctx)

    # ── MEMBERCOUNT ───────────────────────────────────────────────────────────

    @commands.command(name="membercount")
    async def membercount(self, ctx):
        g      = ctx.guild
        bots   = sum(m.bot for m in g.members)
        humans = g.member_count - bots
        online = sum(m.status != discord.Status.offline and not m.bot for m in g.members)
        e = discord.Embed(title="{} Member Count".format(g.name), color=Config.COLOR_INFO)
        e.add_field(name="Humans", value="**{:,}**".format(humans))
        e.add_field(name="Bots",   value="**{:,}**".format(bots))
        e.add_field(name="Online", value="**{:,}**".format(online))
        e.add_field(name="Total",  value="**{:,}**".format(g.member_count), inline=False)
        if g.icon:
            e.set_thumbnail(url=g.icon.url)
        await ctx.reply(embed=e)

    @slash.command(name="membercount", description="Show the server member count breakdown.")
    async def membercount_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.membercount.callback(self, ctx)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def setup(bot):
    await bot.add_cog(Utility(bot))