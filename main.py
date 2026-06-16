"""
OmniBot — main.py
Slash command groups (app_commands.Group) — 19 top-level groups, well under Discord's 100 limit.
Prefix commands still work with ~
"""

import discord
from discord.ext import commands
import logging
import json
import os
import sys
import traceback
from config import Config

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s | %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("OmniBot")

intents = discord.Intents.all()


def save_guild_names(guilds):
    """Save guild ID -> name mapping for the dashboard."""
    os.makedirs(Config.DATA_DIR, exist_ok=True)
    path = os.path.join(Config.DATA_DIR, "guild_names.json")
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        data = {}
    for g in guilds:
        data[str(g.id)] = {
            "name": g.name,
            "icon": str(g.icon.url) if g.icon else None,
            "member_count": g.member_count,
        }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class OmniBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or(Config.PREFIX),
            intents=intents,
            help_command=None,
            case_insensitive=True,
            strip_after_prefix=True,
            owner_ids=set(Config.OWNER_IDS),
        )

    async def setup_hook(self):
        cogs = [
            "cogs.moderation",
            "cogs.utility",
            "cogs.fun",
            # "cogs.music",
            "cogs.economy",
            "cogs.leveling",
            "cogs.automod",
            "cogs.logging_cog",
            "cogs.tickets",
            "cogs.welcome",
            "cogs.giveaway",
            "cogs.reaction_roles",
            "cogs.ai",
            "cogs.invite_tracking",
            "cogs.reports",
            "cogs.jtc",
            "cogs.admin",
            "cogs.embed",
            "cogs.mc",
            "cogs.application",
            "cogs.youtube",
            "cogs.antinuke"
        ]

        failed = []
        for cog in cogs:
            try:
                await self.load_extension(cog)
                log.info(f"Loaded cog: {cog}")
            except Exception as e:
                failed.append(cog)
                log.error(f"Failed to load {cog}: {e}\n{traceback.format_exc()}")

        if failed:
            log.warning(f"Cogs that failed to load: {failed}")

        # ----------------------------------------------------------------
        # Slash command sync strategy:
        #
        # DEVELOPMENT — instant sync to one guild (shows up in seconds):
        #   Set DEV_GUILD_ID in config.py to your test server's ID (int).
        #   Commands appear instantly but only in that server.
        #
        # PRODUCTION — global sync (shows up in all servers within ~1 hour):
        #   Set DEV_GUILD_ID = None in config.py.
        # ----------------------------------------------------------------
        dev_guild_id = getattr(Config, "DEV_GUILD_ID", None)

        if dev_guild_id:
            # Instant guild-specific sync for development
            guild_obj = discord.Object(id=dev_guild_id)
            # Copy all global commands to the guild tree so they sync instantly
            self.tree.copy_global_to(guild=guild_obj)
            try:
                synced = await self.tree.sync(guild=guild_obj)
                log.info(f"DEV: Synced {len(synced)} slash commands to guild {dev_guild_id} (instant).")
            except Exception as e:
                log.error(f"Guild slash command sync failed: {e}")
        else:
            # Global sync — propagates to all guilds within ~1 hour
            try:
                synced = await self.tree.sync()
                log.info(f"PROD: Synced {len(synced)} slash commands globally (~1 hour to propagate).")
            except Exception as e:
                log.error(f"Slash command sync failed: {e}")

    async def on_ready(self):
        log.info(f"Logged in as {self.user} (ID: {self.user.id})")
        log.info(f"Connected to {len(self.guilds)} guild(s).")
        save_guild_names(self.guilds)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{Config.PREFIX}help | {len(self.guilds)} servers",
            ),
            status=discord.Status.online,
        )

    async def on_guild_join(self, guild):
        save_guild_names(self.guilds)

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("You don't have permission to use this command.", mention_author=False)
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.reply(f"I'm missing permissions: `{', '.join(error.missing_permissions)}`", mention_author=False)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply(f"Missing argument: `{error.param.name}`.", mention_author=False)
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("Invalid argument provided.", mention_author=False)
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"Cooldown! Try again in `{error.retry_after:.1f}s`.", mention_author=False)
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.reply("This command can only be used in a server.", mention_author=False)
        elif isinstance(error, commands.CheckFailure):
            await ctx.reply("You don't have access to this command.", mention_author=False)
        else:
            log.error(f"Unhandled error in {ctx.command}: {error}", exc_info=error)
            await ctx.reply("An unexpected error occurred.", mention_author=False)

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        msg = "An error occurred."
        if isinstance(error, discord.app_commands.MissingPermissions):
            msg = f"You need: `{'`, `'.join(error.missing_permissions)}`"
        elif isinstance(error, discord.app_commands.BotMissingPermissions):
            msg = f"I need: `{'`, `'.join(error.missing_permissions)}`"
        elif isinstance(error, discord.app_commands.CommandOnCooldown):
            msg = f"Cooldown! Try again in `{error.retry_after:.1f}s`."
        else:
            log.error(f"Slash command error: {error}\n{traceback.format_exc()}")
            msg = f"Error: `{error}`"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


if __name__ == "__main__":
    if not Config.TOKEN or Config.TOKEN == "YOUR_TOKEN_HERE":
        log.error("No bot token set! Edit TOKEN in config.py before running.")
        sys.exit(1)
    bot = OmniBot()
    bot.run(Config.TOKEN, log_handler=None)