"""
cogs/automod.py
Slash group: /automod
Slash subgroup: /automod whitelist-*

Per-module whitelist system:
  Every filter (anti_links, anti_invite, anti_spam, caps_filter,
  bad_words, mention_limit) has its own independent whitelist of
  users, roles, channels, and categories.

  Being whitelisted for ONE module does NOT exempt from the others.
  The global ignore (ignorechannel / ignorerole) still bypasses ALL modules.

Prefix commands still work with ~
"""

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import re
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from config import Config
from utils.data import load, save

INVITE_RE = re.compile(r"discord(?:\.gg|app\.com/invite|\.com/invite)/[a-zA-Z0-9\-]+", re.IGNORECASE)
URL_RE    = re.compile(r"https?://[^\s]+", re.IGNORECASE)

# All filterable modules
ALL_MODULES = ["anti_spam", "anti_invite", "anti_links", "caps_filter", "bad_words", "mention_limit"]

MODULE_CHOICES = [
    app_commands.Choice(name="Anti-Links",    value="anti_links"),
    app_commands.Choice(name="Anti-Invite",   value="anti_invite"),
    app_commands.Choice(name="Anti-Spam",     value="anti_spam"),
    app_commands.Choice(name="Caps Filter",   value="caps_filter"),
    app_commands.Choice(name="Bad Words",     value="bad_words"),
    app_commands.Choice(name="Mention Limit", value="mention_limit"),
]

MODULE_LABELS = {
    "anti_links":    "Anti-Links",
    "anti_invite":   "Anti-Invite",
    "anti_spam":     "Anti-Spam",
    "caps_filter":   "Caps Filter",
    "bad_words":     "Bad Words",
    "mention_limit": "Mention Limit",
}


def _empty_module_wl() -> dict:
    return {"users": [], "roles": [], "channels": [], "categories": []}


class AutoMod(commands.Cog):
    """🛡️ Automatic moderation system."""

    slash = app_commands.Group(name="automod", description="AutoMod configuration commands")

    def __init__(self, bot):
        self.bot = bot
        self._spam_tracker: dict[int, dict[int, deque]] = defaultdict(lambda: defaultdict(deque))

    # ── Data helpers ──────────────────────────────────

    def _settings(self, guild_id: int) -> dict:
        data = load("guild_settings.json")
        return data.get(str(guild_id), {}).get("automod", {
            "enabled":          True,
            "anti_spam":        True,
            "anti_invite":      True,
            "anti_links":       False,
            "caps_filter":      True,
            "mention_limit":    Config.MAX_MENTIONS,
            "bad_words":        Config.BAD_WORDS,
            "log_channel":      None,
            "ignored_roles":    [],
            "ignored_channels": [],
            "module_whitelist": {},
        })

    def _save_am(self, guild_id: int, am: dict):
        data = load("guild_settings.json")
        data.setdefault(str(guild_id), {})["automod"] = am
        save("guild_settings.json", data)

    def _toggle(self, guild_id: int, key: str) -> bool:
        data = load("guild_settings.json")
        am   = data.setdefault(str(guild_id), {}).setdefault("automod", {})
        am[key] = not am.get(key, True)
        save("guild_settings.json", data)
        return am[key]

    # ── Module whitelist helpers ──────────────────────

    def _module_wl(self, am: dict, module: str) -> dict:
        """Return the whitelist dict for a given module (never None)."""
        return am.setdefault("module_whitelist", {}).setdefault(module, _empty_module_wl())

    def _is_module_whitelisted(self, message: discord.Message, module: str, am: dict) -> bool:
        """Return True if this message's author/channel/category is whitelisted for this module."""
        wl       = am.get("module_whitelist", {}).get(module, {})
        user_id  = message.author.id
        role_ids = {r.id for r in getattr(message.author, "roles", [])}
        ch_id    = message.channel.id
        cat_id   = getattr(message.channel, "category_id", None)

        if user_id  in wl.get("users",      []):
            return True
        if role_ids & set(wl.get("roles",   [])):
            return True
        if ch_id    in wl.get("channels",   []):
            return True
        if cat_id and cat_id in wl.get("categories", []):
            return True
        return False

    def _toggle_wl_entry(self, guild_id: int, module: str, key: str, entry_id: int) -> bool:
        """
        Toggle an ID in the whitelist for a module/key combo.
        Returns True if the entry was added, False if removed.
        """
        data   = load("guild_settings.json")
        am     = data.setdefault(str(guild_id), {}).setdefault("automod", {})
        wl     = am.setdefault("module_whitelist", {}).setdefault(module, _empty_module_wl())
        bucket = wl.setdefault(key, [])
        if entry_id in bucket:
            bucket.remove(entry_id)
            added = False
        else:
            bucket.append(entry_id)
            added = True
        save("guild_settings.json", data)
        return added

    # ── Punishment ───────────────────────────────────

    async def _punish(self, message: discord.Message, reason: str, mute_seconds: int = 0):
        try:
            await message.delete()
        except Exception:
            pass
        if mute_seconds and message.guild.me.guild_permissions.moderate_members:
            try:
                until = discord.utils.utcnow() + timedelta(seconds=mute_seconds)
                await message.author.timeout(until, reason=f"AutoMod: {reason}")
            except Exception:
                pass
        am     = self._settings(message.guild.id)
        log_id = am.get("log_channel")
        if log_id:
            ch = message.guild.get_channel(int(log_id))
            if ch:
                e = discord.Embed(
                    title="🛡️ AutoMod Action",
                    description=(
                        f"**User:** {message.author.mention}\n"
                        f"**Channel:** {message.channel.mention}\n"
                        f"**Reason:** {reason}\n"
                        f"**Content:** {message.content[:200]}"
                    ),
                    color=Config.COLOR_ERR,
                    timestamp=datetime.now(timezone.utc)
                )
                await ch.send(embed=e)

    def _is_globally_ignored(self, message: discord.Message, am: dict) -> bool:
        """Global ignore — bypasses ALL modules."""
        if message.channel.id in am.get("ignored_channels", []):
            return True
        if any(r.id in am.get("ignored_roles", []) for r in getattr(message.author, "roles", [])):
            return True
        if message.author.guild_permissions.manage_messages:
            return True
        return False

    # ── Core listener ─────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        am = self._settings(message.guild.id)
        if not am.get("enabled", True):
            return
        if self._is_globally_ignored(message, am):
            return

        content = message.content

        # ── Anti-Spam ─────────────────────────────────
        if am.get("anti_spam", True) and not self._is_module_whitelisted(message, "anti_spam", am):
            tracker = self._spam_tracker[message.guild.id][message.author.id]
            now     = asyncio.get_event_loop().time()
            tracker.append(now)
            cutoff  = now - Config.SPAM_INTERVAL
            while tracker and tracker[0] < cutoff:
                tracker.popleft()
            if len(tracker) >= Config.SPAM_MESSAGE_COUNT:
                tracker.clear()
                await self._punish(message, "Spam detected", Config.SPAM_MUTE_DURATION)
                return

        # ── Anti-Invite ───────────────────────────────
        if am.get("anti_invite", True) and not self._is_module_whitelisted(message, "anti_invite", am):
            if INVITE_RE.search(content):
                await self._punish(message, "Discord invite link")
                return

        # ── Anti-Links ────────────────────────────────
        if am.get("anti_links", False) and not self._is_module_whitelisted(message, "anti_links", am):
            if URL_RE.search(content):
                await self._punish(message, "External link")
                return

        # ── Caps Filter ───────────────────────────────
        if am.get("caps_filter", True) and not self._is_module_whitelisted(message, "caps_filter", am):
            if len(content) > 10:
                upper = sum(1 for c in content if c.isupper())
                if upper / len(content) * 100 >= Config.MAX_CAPS_PERCENT:
                    await self._punish(message, "Excessive caps")
                    return

        # ── Mention Spam ──────────────────────────────
        if not self._is_module_whitelisted(message, "mention_limit", am):
            limit = am.get("mention_limit", Config.MAX_MENTIONS)
            if len(message.mentions) + len(message.role_mentions) > limit:
                await self._punish(message, f"Mention spam ({len(message.mentions)} pings)", 60)
                return

        # ── Bad Words ─────────────────────────────────
        if not self._is_module_whitelisted(message, "bad_words", am):
            bad_words     = am.get("bad_words", Config.BAD_WORDS)
            lower_content = content.lower()
            if any(word in lower_content for word in bad_words):
                await self._punish(message, "Prohibited word")
                return

    # ── STATUS (prefix + slash) ───────────────────────

    @commands.group(name="automod", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def automod_prefix(self, ctx):
        am = self._settings(ctx.guild.id)
        e  = discord.Embed(title="🛡️ AutoMod Config", color=Config.COLOR_MOD)
        e.add_field(name="Enabled",      value="✅" if am.get("enabled") else "❌")
        e.add_field(name="Anti-Spam",    value="✅" if am.get("anti_spam") else "❌")
        e.add_field(name="Anti-Invite",  value="✅" if am.get("anti_invite") else "❌")
        e.add_field(name="Anti-Links",   value="✅" if am.get("anti_links") else "❌")
        e.add_field(name="Caps Filter",  value="✅" if am.get("caps_filter") else "❌")
        e.add_field(name="Max Mentions", value=am.get("mention_limit", Config.MAX_MENTIONS))
        e.set_footer(text=f"Use {Config.PREFIX}automod <subcommand> to configure")
        await ctx.reply(embed=e)

    @slash.command(name="status", description="Show current AutoMod configuration.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def automod_status_slash(self, interaction: discord.Interaction):
        am = self._settings(interaction.guild.id)
        e  = discord.Embed(title="🛡️ AutoMod Config", color=Config.COLOR_MOD)
        e.add_field(name="Enabled",      value="✅" if am.get("enabled") else "❌")
        e.add_field(name="Anti-Spam",    value="✅" if am.get("anti_spam") else "❌")
        e.add_field(name="Anti-Invite",  value="✅" if am.get("anti_invite") else "❌")
        e.add_field(name="Anti-Links",   value="✅" if am.get("anti_links") else "❌")
        e.add_field(name="Caps Filter",  value="✅" if am.get("caps_filter") else "❌")
        e.add_field(name="Max Mentions", value=am.get("mention_limit", Config.MAX_MENTIONS))
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── PREFIX TOGGLE SUBCOMMANDS ─────────────────────

    @automod_prefix.command(name="toggle")
    @commands.has_permissions(administrator=True)
    async def automod_toggle(self, ctx):
        state = self._toggle(ctx.guild.id, "enabled")
        await ctx.reply(f"🛡️ AutoMod is now **{'enabled' if state else 'disabled'}**.")

    @automod_prefix.command(name="antispam")
    @commands.has_permissions(administrator=True)
    async def automod_antispam(self, ctx):
        state = self._toggle(ctx.guild.id, "anti_spam")
        await ctx.reply(f"🛡️ Anti-spam: **{'on' if state else 'off'}**.")

    @automod_prefix.command(name="antiinvite")
    @commands.has_permissions(administrator=True)
    async def automod_antiinvite(self, ctx):
        state = self._toggle(ctx.guild.id, "anti_invite")
        await ctx.reply(f"🛡️ Anti-invite: **{'on' if state else 'off'}**.")

    @automod_prefix.command(name="antilinks")
    @commands.has_permissions(administrator=True)
    async def automod_antilinks(self, ctx):
        state = self._toggle(ctx.guild.id, "anti_links")
        await ctx.reply(f"🛡️ Anti-links: **{'on' if state else 'off'}**.")

    @automod_prefix.command(name="capsfilter")
    @commands.has_permissions(administrator=True)
    async def automod_caps(self, ctx):
        state = self._toggle(ctx.guild.id, "caps_filter")
        await ctx.reply(f"🛡️ Caps filter: **{'on' if state else 'off'}**.")

    @automod_prefix.command(name="mentions")
    @commands.has_permissions(administrator=True)
    async def automod_mentions(self, ctx, limit: int):
        data = load("guild_settings.json")
        data.setdefault(str(ctx.guild.id), {}).setdefault("automod", {})["mention_limit"] = limit
        save("guild_settings.json", data)
        await ctx.reply(f"🛡️ Max mentions per message set to **{limit}**.")

    @automod_prefix.command(name="addword")
    @commands.has_permissions(administrator=True)
    async def automod_addword(self, ctx, *, word: str):
        data  = load("guild_settings.json")
        am    = data.setdefault(str(ctx.guild.id), {}).setdefault("automod", {})
        words = am.setdefault("bad_words", list(Config.BAD_WORDS))
        word  = word.lower()
        if word not in words:
            words.append(word)
        am["bad_words"] = words
        save("guild_settings.json", data)
        await ctx.reply(f"✅ Added `{word}` to bad words list.")

    @automod_prefix.command(name="removeword")
    @commands.has_permissions(administrator=True)
    async def automod_removeword(self, ctx, *, word: str):
        data  = load("guild_settings.json")
        am    = data.setdefault(str(ctx.guild.id), {}).setdefault("automod", {})
        words = am.get("bad_words", [])
        word  = word.lower()
        if word in words:
            words.remove(word)
            am["bad_words"] = words
            save("guild_settings.json", data)
            await ctx.reply(f"✅ Removed `{word}` from bad words.")
        else:
            await ctx.reply(f"❌ `{word}` not in bad words list.")

    @automod_prefix.command(name="logchannel")
    @commands.has_permissions(administrator=True)
    async def automod_log(self, ctx, channel: discord.TextChannel):
        data = load("guild_settings.json")
        data.setdefault(str(ctx.guild.id), {}).setdefault("automod", {})["log_channel"] = channel.id
        save("guild_settings.json", data)
        await ctx.reply(f"✅ AutoMod logs will be sent to {channel.mention}.")

    @automod_prefix.command(name="ignorechannel")
    @commands.has_permissions(administrator=True)
    async def automod_ignorechannel(self, ctx, channel: discord.TextChannel = None):
        """Global ignore — bypasses ALL automod modules."""
        ch   = channel or ctx.channel
        data = load("guild_settings.json")
        am   = data.setdefault(str(ctx.guild.id), {}).setdefault("automod", {})
        ignored = am.setdefault("ignored_channels", [])
        if ch.id in ignored:
            ignored.remove(ch.id)
            msg = f"✅ AutoMod **enabled** in {ch.mention} (all modules)."
        else:
            ignored.append(ch.id)
            msg = f"🚫 AutoMod **globally disabled** in {ch.mention}."
        save("guild_settings.json", data)
        await ctx.reply(msg)

    @automod_prefix.command(name="ignorerole")
    @commands.has_permissions(administrator=True)
    async def automod_ignorerole(self, ctx, role: discord.Role):
        """Global ignore — bypasses ALL automod modules."""
        data = load("guild_settings.json")
        am   = data.setdefault(str(ctx.guild.id), {}).setdefault("automod", {})
        ignored = am.setdefault("ignored_roles", [])
        if role.id in ignored:
            ignored.remove(role.id)
            msg = f"✅ AutoMod **applies** to {role.mention} again (all modules)."
        else:
            ignored.append(role.id)
            msg = f"🚫 AutoMod **globally ignores** {role.mention}."
        save("guild_settings.json", data)
        await ctx.reply(msg)

    # ── PREFIX WHITELIST SUBCOMMANDS ──────────────────
    # ~automod wl user <module> <user>
    # ~automod wl role <module> <role>
    # ~automod wl channel <module> <channel>
    # ~automod wl category <module> <category_id>
    # ~automod wl list [module]

    @automod_prefix.group(name="wl", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def automod_wl(self, ctx):
        await ctx.reply(
            f"**Per-module whitelist subcommands:**\n"
            f"`{Config.PREFIX}automod wl user <module> <@user>` — toggle user exemption\n"
            f"`{Config.PREFIX}automod wl role <module> <@role>` — toggle role exemption\n"
            f"`{Config.PREFIX}automod wl channel <module> [#channel]` — toggle channel exemption\n"
            f"`{Config.PREFIX}automod wl category <module> <category_id>` — toggle category exemption\n"
            f"`{Config.PREFIX}automod wl list [module]` — view whitelists\n\n"
            f"**Modules:** `anti_links` `anti_invite` `anti_spam` `caps_filter` `bad_words` `mention_limit`"
        )

    @automod_wl.command(name="user")
    @commands.has_permissions(administrator=True)
    async def wl_user_prefix(self, ctx, module: str, member: discord.Member):
        if module not in ALL_MODULES:
            return await ctx.reply(f"❌ Invalid module. Choose from: `{'`, `'.join(ALL_MODULES)}`")
        added = self._toggle_wl_entry(ctx.guild.id, module, "users", member.id)
        label = MODULE_LABELS[module]
        if added:
            await ctx.reply(f"✅ {member.mention} is now **whitelisted** from **{label}** (other modules still apply).")
        else:
            await ctx.reply(f"➖ {member.mention} removed from **{label}** whitelist.")

    @automod_wl.command(name="role")
    @commands.has_permissions(administrator=True)
    async def wl_role_prefix(self, ctx, module: str, role: discord.Role):
        if module not in ALL_MODULES:
            return await ctx.reply(f"❌ Invalid module. Choose from: `{'`, `'.join(ALL_MODULES)}`")
        added = self._toggle_wl_entry(ctx.guild.id, module, "roles", role.id)
        label = MODULE_LABELS[module]
        if added:
            await ctx.reply(f"✅ {role.mention} is now **whitelisted** from **{label}** (other modules still apply).")
        else:
            await ctx.reply(f"➖ {role.mention} removed from **{label}** whitelist.")

    @automod_wl.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def wl_channel_prefix(self, ctx, module: str, channel: discord.TextChannel = None):
        if module not in ALL_MODULES:
            return await ctx.reply(f"❌ Invalid module. Choose from: `{'`, `'.join(ALL_MODULES)}`")
        ch    = channel or ctx.channel
        added = self._toggle_wl_entry(ctx.guild.id, module, "channels", ch.id)
        label = MODULE_LABELS[module]
        if added:
            await ctx.reply(f"✅ {ch.mention} is now **whitelisted** from **{label}** (other modules still apply).")
        else:
            await ctx.reply(f"➖ {ch.mention} removed from **{label}** whitelist.")

    @automod_wl.command(name="category")
    @commands.has_permissions(administrator=True)
    async def wl_category_prefix(self, ctx, module: str, category_id: int):
        if module not in ALL_MODULES:
            return await ctx.reply(f"❌ Invalid module. Choose from: `{'`, `'.join(ALL_MODULES)}`")
        cat = ctx.guild.get_channel(category_id)
        if not isinstance(cat, discord.CategoryChannel):
            return await ctx.reply("❌ That is not a valid category ID.")
        added = self._toggle_wl_entry(ctx.guild.id, module, "categories", cat.id)
        label = MODULE_LABELS[module]
        if added:
            await ctx.reply(f"✅ Category **{cat.name}** is now **whitelisted** from **{label}** (other modules still apply).")
        else:
            await ctx.reply(f"➖ Category **{cat.name}** removed from **{label}** whitelist.")

    @automod_wl.command(name="list")
    @commands.has_permissions(administrator=True)
    async def wl_list_prefix(self, ctx, module: str = None):
        am = self._settings(ctx.guild.id)
        modules = [module] if module and module in ALL_MODULES else ALL_MODULES
        e = discord.Embed(title="🛡️ AutoMod Per-Module Whitelists", color=Config.COLOR_MOD)
        for mod in modules:
            wl    = am.get("module_whitelist", {}).get(mod, {})
            lines = []
            for uid in wl.get("users",      []):
                lines.append(f"👤 <@{uid}>")
            for rid in wl.get("roles",      []):
                lines.append(f"🎭 <@&{rid}>")
            for cid in wl.get("channels",   []):
                lines.append(f"📢 <#{cid}>")
            for cat_id in wl.get("categories", []):
                cat = ctx.guild.get_channel(cat_id)
                lines.append(f"📁 {cat.name if cat else f'Category {cat_id}'}")
            e.add_field(
                name=f"{MODULE_LABELS[mod]}",
                value="\n".join(lines) if lines else "*None*",
                inline=True
            )
        await ctx.reply(embed=e)

    # ── SLASH TOGGLE SUBCOMMANDS ──────────────────────

    @slash.command(name="toggle", description="Enable or disable AutoMod entirely.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def toggle_slash(self, interaction: discord.Interaction):
        state = self._toggle(interaction.guild.id, "enabled")
        await interaction.response.send_message(f"🛡️ AutoMod is now **{'enabled' if state else 'disabled'}**.", ephemeral=True)

    @slash.command(name="antispam", description="Toggle anti-spam filter.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def antispam_slash(self, interaction: discord.Interaction):
        state = self._toggle(interaction.guild.id, "anti_spam")
        await interaction.response.send_message(f"🛡️ Anti-spam: **{'on' if state else 'off'}**.", ephemeral=True)

    @slash.command(name="antiinvite", description="Toggle anti-invite link filter.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def antiinvite_slash(self, interaction: discord.Interaction):
        state = self._toggle(interaction.guild.id, "anti_invite")
        await interaction.response.send_message(f"🛡️ Anti-invite: **{'on' if state else 'off'}**.", ephemeral=True)

    @slash.command(name="antilinks", description="Toggle anti-external-links filter.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def antilinks_slash(self, interaction: discord.Interaction):
        state = self._toggle(interaction.guild.id, "anti_links")
        await interaction.response.send_message(f"🛡️ Anti-links: **{'on' if state else 'off'}**.", ephemeral=True)

    @slash.command(name="capsfilter", description="Toggle excessive-caps filter.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def capsfilter_slash(self, interaction: discord.Interaction):
        state = self._toggle(interaction.guild.id, "caps_filter")
        await interaction.response.send_message(f"🛡️ Caps filter: **{'on' if state else 'off'}**.", ephemeral=True)

    @slash.command(name="mentions", description="Set max mentions allowed per message.")
    @app_commands.describe(limit="Maximum number of mentions before action is taken")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mentions_slash(self, interaction: discord.Interaction, limit: int):
        data = load("guild_settings.json")
        data.setdefault(str(interaction.guild.id), {}).setdefault("automod", {})["mention_limit"] = limit
        save("guild_settings.json", data)
        await interaction.response.send_message(f"🛡️ Max mentions per message set to **{limit}**.", ephemeral=True)

    @slash.command(name="addword", description="Add a word to the bad words filter.")
    @app_commands.describe(word="Word to block")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def addword_slash(self, interaction: discord.Interaction, word: str):
        data  = load("guild_settings.json")
        am    = data.setdefault(str(interaction.guild.id), {}).setdefault("automod", {})
        words = am.setdefault("bad_words", list(Config.BAD_WORDS))
        word  = word.lower()
        if word not in words:
            words.append(word)
        am["bad_words"] = words
        save("guild_settings.json", data)
        await interaction.response.send_message(f"✅ Added `{word}` to bad words list.", ephemeral=True)

    @slash.command(name="removeword", description="Remove a word from the bad words filter.")
    @app_commands.describe(word="Word to unblock")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def removeword_slash(self, interaction: discord.Interaction, word: str):
        data  = load("guild_settings.json")
        am    = data.setdefault(str(interaction.guild.id), {}).setdefault("automod", {})
        words = am.get("bad_words", [])
        word  = word.lower()
        if word in words:
            words.remove(word)
            am["bad_words"] = words
            save("guild_settings.json", data)
            await interaction.response.send_message(f"✅ Removed `{word}` from bad words.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ `{word}` not in bad words list.", ephemeral=True)

    @slash.command(name="logchannel", description="Set the AutoMod log channel.")
    @app_commands.describe(channel="Channel to log AutoMod actions to")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def logchannel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        data = load("guild_settings.json")
        data.setdefault(str(interaction.guild.id), {}).setdefault("automod", {})["log_channel"] = channel.id
        save("guild_settings.json", data)
        await interaction.response.send_message(f"✅ AutoMod logs → {channel.mention}.", ephemeral=True)

    @slash.command(name="ignorechannel", description="Globally disable ALL AutoMod in a channel (all modules).")
    @app_commands.describe(channel="Channel to toggle global ignore (defaults to current)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def ignorechannel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        ch   = channel or interaction.channel
        data = load("guild_settings.json")
        am   = data.setdefault(str(interaction.guild.id), {}).setdefault("automod", {})
        ignored = am.setdefault("ignored_channels", [])
        if ch.id in ignored:
            ignored.remove(ch.id)
            msg = f"✅ AutoMod **enabled** in {ch.mention} (all modules)."
        else:
            ignored.append(ch.id)
            msg = f"🚫 AutoMod **globally disabled** in {ch.mention}."
        save("guild_settings.json", data)
        await interaction.response.send_message(msg, ephemeral=True)

    @slash.command(name="ignorerole", description="Globally exempt a role from ALL AutoMod modules.")
    @app_commands.describe(role="Role to globally ignore")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def ignorerole_slash(self, interaction: discord.Interaction, role: discord.Role):
        data = load("guild_settings.json")
        am   = data.setdefault(str(interaction.guild.id), {}).setdefault("automod", {})
        ignored = am.setdefault("ignored_roles", [])
        if role.id in ignored:
            ignored.remove(role.id)
            msg = f"✅ AutoMod **applies** to {role.mention} again (all modules)."
        else:
            ignored.append(role.id)
            msg = f"🚫 AutoMod **globally ignores** {role.mention}."
        save("guild_settings.json", data)
        await interaction.response.send_message(msg, ephemeral=True)

    # ══════════════════════════════════════════════════
    # ── SLASH WHITELIST SUBCOMMANDS ───────────────────
    # /automod whitelist-user   <module> <user>
    # /automod whitelist-role   <module> <role>
    # /automod whitelist-channel <module> [channel]
    # /automod whitelist-category <module> <category>
    # /automod whitelist-list   [module]
    # /automod whitelist-clear  <module>
    #
    # Each command is a FLAT subcommand of /automod because
    # Discord.py nested-group support requires careful ordering.
    # The names follow the pattern "whitelist-<target>" for clarity.
    # ══════════════════════════════════════════════════

    @slash.command(name="whitelist-user", description="Toggle a user's exemption for ONE automod module only.")
    @app_commands.describe(module="The specific module to whitelist for", user="User to whitelist/unwhitelist")
    @app_commands.choices(module=MODULE_CHOICES)
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def wl_user_slash(self, interaction: discord.Interaction, module: str, user: discord.Member):
        added = self._toggle_wl_entry(interaction.guild.id, module, "users", user.id)
        label = MODULE_LABELS[module]
        if added:
            await interaction.response.send_message(
                f"✅ {user.mention} is now **whitelisted** from **{label}** only.\n"
                f"*All other AutoMod modules still apply to them.*",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"➖ {user.mention} removed from the **{label}** whitelist.",
                ephemeral=True
            )

    @slash.command(name="whitelist-role", description="Toggle a role's exemption for ONE automod module only.")
    @app_commands.describe(module="The specific module to whitelist for", role="Role to whitelist/unwhitelist")
    @app_commands.choices(module=MODULE_CHOICES)
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def wl_role_slash(self, interaction: discord.Interaction, module: str, role: discord.Role):
        added = self._toggle_wl_entry(interaction.guild.id, module, "roles", role.id)
        label = MODULE_LABELS[module]
        if added:
            await interaction.response.send_message(
                f"✅ {role.mention} is now **whitelisted** from **{label}** only.\n"
                f"*All other AutoMod modules still apply to members with this role.*",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"➖ {role.mention} removed from the **{label}** whitelist.",
                ephemeral=True
            )

    @slash.command(name="whitelist-channel", description="Toggle a channel's exemption for ONE automod module only.")
    @app_commands.describe(module="The specific module to whitelist for", channel="Channel to whitelist (defaults to current)")
    @app_commands.choices(module=MODULE_CHOICES)
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def wl_channel_slash(self, interaction: discord.Interaction, module: str, channel: discord.TextChannel = None):
        ch    = channel or interaction.channel
        added = self._toggle_wl_entry(interaction.guild.id, module, "channels", ch.id)
        label = MODULE_LABELS[module]
        if added:
            await interaction.response.send_message(
                f"✅ {ch.mention} is now **whitelisted** from **{label}** only.\n"
                f"*All other AutoMod modules still apply in this channel.*",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"➖ {ch.mention} removed from the **{label}** whitelist.",
                ephemeral=True
            )

    @slash.command(name="whitelist-category", description="Toggle a category's exemption for ONE automod module only.")
    @app_commands.describe(module="The specific module to whitelist for", category="Category to whitelist")
    @app_commands.choices(module=MODULE_CHOICES)
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def wl_category_slash(self, interaction: discord.Interaction, module: str, category: discord.CategoryChannel):
        added = self._toggle_wl_entry(interaction.guild.id, module, "categories", category.id)
        label = MODULE_LABELS[module]
        if added:
            await interaction.response.send_message(
                f"✅ Category **{category.name}** is now **whitelisted** from **{label}** only.\n"
                f"*All channels under this category are exempt from {label}.*\n"
                f"*All other AutoMod modules still apply.*",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"➖ Category **{category.name}** removed from the **{label}** whitelist.",
                ephemeral=True
            )

    @slash.command(name="whitelist-list", description="Show per-module whitelists. Optionally filter to one module.")
    @app_commands.describe(module="Filter to a specific module (leave empty to show all)")
    @app_commands.choices(module=MODULE_CHOICES)
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def wl_list_slash(self, interaction: discord.Interaction, module: str = None):
        am      = self._settings(interaction.guild.id)
        modules = [module] if module else ALL_MODULES
        e = discord.Embed(
            title="🛡️ AutoMod Per-Module Whitelists",
            description=(
                "Each entry below is exempt from that specific module **only**.\n"
                "Global ignores (ignorechannel / ignorerole) bypass ALL modules."
            ),
            color=Config.COLOR_MOD
        )
        any_set = False
        for mod in modules:
            wl    = am.get("module_whitelist", {}).get(mod, {})
            lines = []
            for uid   in wl.get("users",      []):
                lines.append(f"👤 <@{uid}>")
            for rid   in wl.get("roles",      []):
                lines.append(f"🎭 <@&{rid}>")
            for cid   in wl.get("channels",   []):
                lines.append(f"📢 <#{cid}>")
            for cat_id in wl.get("categories", []):
                cat = interaction.guild.get_channel(cat_id)
                lines.append(f"📁 {cat.name if cat else f'Category {cat_id}'}")
            if lines:
                any_set = True
            e.add_field(
                name=f"{MODULE_LABELS[mod]}",
                value="\n".join(lines) if lines else "*None*",
                inline=True
            )
        if not any_set:
            e.set_footer(text="No per-module whitelists configured.")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @slash.command(name="whitelist-clear", description="Clear ALL whitelist entries for a specific module.")
    @app_commands.describe(module="Module to clear whitelists for")
    @app_commands.choices(module=MODULE_CHOICES)
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def wl_clear_slash(self, interaction: discord.Interaction, module: str):
        data = load("guild_settings.json")
        am   = data.setdefault(str(interaction.guild.id), {}).setdefault("automod", {})
        am.setdefault("module_whitelist", {})[module] = _empty_module_wl()
        save("guild_settings.json", data)
        label = MODULE_LABELS[module]
        await interaction.response.send_message(
            f"🗑️ Cleared all whitelist entries for **{label}**.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
