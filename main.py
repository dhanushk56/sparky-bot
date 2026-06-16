"""
OmniBot — main.py
Slash command groups (app_commands.Group) — 19 top-level groups, well under Discord's 100 limit.
Prefix commands still work with ~
"""

import discord
from discord.ext import commands
import discord.app_commands as app_commands
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

# Your user ID for error DMs and fallback owner check
OWNER_ID = 1077905352244338688


# Custom owner check that also includes the hardcoded OWNER_ID
def is_owner():
    async def predicate(ctx):
        return ctx.author.id in set(Config.OWNER_IDS) or ctx.author.id == OWNER_ID
    return commands.check(predicate)


async def send_dm_to_owner(bot, content: str):
    """Send a DM to the bot owner."""
    try:
        owner = await bot.fetch_user(OWNER_ID)
        # Split content if too long (Discord DM limit 2000 chars)
        for chunk in [content[i:i+1990] for i in range(0, len(content), 1990)]:
            await owner.send(chunk)
    except Exception as e:
        log.error(f"Failed to DM owner: {e}")


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

        loaded_cogs = []
        failed_cogs = []
        
        for cog in cogs:
            try:
                await self.load_extension(cog)
                log.info(f"Loaded cog: {cog}")
                loaded_cogs.append(cog)
            except Exception as e:
                error_msg = f"Failed to load {cog}: {e}\n{traceback.format_exc()}"
                log.error(error_msg)
                failed_cogs.append((cog, error_msg))
                # DM owner about the failure
                await send_dm_to_owner(self, f"❌ Cog load failed: `{cog}`\n```py\n{error_msg[:1900]}\n```")

        # Send success summary to owner
        if loaded_cogs:
            await send_dm_to_owner(self, f"✅ Loaded cogs: {', '.join(loaded_cogs)}")
        
        if failed_cogs:
            await send_dm_to_owner(self, f"⚠️ Failed cogs: {', '.join([c[0] for c in failed_cogs])}")

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
                await send_dm_to_owner(self, f"📡 Synced {len(synced)} commands to guild `{dev_guild_id}` (instant)")
            except Exception as e:
                error_msg = f"Guild slash command sync failed: {e}\n{traceback.format_exc()}"
                log.error(error_msg)
                await send_dm_to_owner(self, f"❌ Command sync failed:\n```py\n{error_msg[:1900]}\n```")
        else:
            # Global sync — propagates to all guilds within ~1 hour
            try:
                synced = await self.tree.sync()
                log.info(f"PROD: Synced {len(synced)} slash commands globally (~1 hour to propagate).")
                await send_dm_to_owner(self, f"📡 Synced {len(synced)} global commands (may take up to 1h to appear)")
            except Exception as e:
                error_msg = f"Slash command sync failed: {e}\n{traceback.format_exc()}"
                log.error(error_msg)
                await send_dm_to_owner(self, f"❌ Global command sync failed:\n```py\n{error_msg[:1900]}\n```")

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
        
        # DM owner with owner IDs loaded from config
        owner_ids_str = ", ".join(str(oid) for oid in self.owner_ids) if self.owner_ids else "EMPTY"
        await send_dm_to_owner(self, f"✅ Bot online.\nOwner IDs from config: `{owner_ids_str}`\nHardcoded OWNER_ID: `{OWNER_ID}`")

        # Setup owner commands after bot is ready
        await self.setup_owner_commands()

    async def on_guild_join(self, guild):
        save_guild_names(self.guilds)
        await send_dm_to_owner(self, f"➕ Bot joined new guild: `{guild.name}` (ID: {guild.id})")

    async def setup_owner_commands(self):
        """Setup owner-only prefix commands for debugging."""
        
        @self.command(name="reload")
        @is_owner()   # custom check
        async def reload_cmd(ctx, cog_name: str = None):
            """Reload a cog (or all if none specified)."""
            if cog_name is None:
                # Reload all cogs
                success = []
                failed = []
                for cog in [
                    "cogs.moderation",
                    "cogs.utility",
                    "cogs.fun",
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
                    "cogs.antinuke",
                    # "cogs.music"
                ]:
                    try:
                        await self.reload_extension(cog)
                        success.append(cog)
                    except Exception as e:
                        failed.append(f"{cog}: {e}")
                
                await ctx.send(f"✅ Reloaded: {', '.join(success) if success else 'none'}\n❌ Failed: {', '.join(failed) if failed else 'none'}")
                
                # Resync commands
                dev_guild_id = getattr(Config, "DEV_GUILD_ID", None)
                if dev_guild_id:
                    await self.tree.sync(guild=discord.Object(id=dev_guild_id))
                    await ctx.send(f"🔄 Commands re-synced to guild {dev_guild_id}")
                else:
                    await self.tree.sync()
                    await ctx.send("🔄 Global commands re-synced (may take up to 1h)")
            else:
                # Reload a single cog
                cog_path = f"cogs.{cog_name}" if not cog_name.startswith("cogs.") else cog_name
                try:
                    await self.reload_extension(cog_path)
                    await ctx.send(f"✅ Reloaded `{cog_path}`")
                    
                    # Resync commands
                    dev_guild_id = getattr(Config, "DEV_GUILD_ID", None)
                    if dev_guild_id:
                        await self.tree.sync(guild=discord.Object(id=dev_guild_id))
                        await ctx.send(f"🔄 Commands re-synced to guild {dev_guild_id}")
                    else:
                        await self.tree.sync()
                        await ctx.send("🔄 Global commands re-synced (may take up to 1h)")
                except Exception as e:
                    await ctx.send(f"❌ Error: {e}")

        @self.command(name="sync")
        @is_owner()
        async def sync_cmd(ctx):
            """Manually sync slash commands."""
            try:
                dev_guild_id = getattr(Config, "DEV_GUILD_ID", None)
                if dev_guild_id:
                    guild = discord.Object(id=dev_guild_id)
                    synced = await self.tree.sync(guild=guild)
                    await ctx.send(f"✅ Synced {len(synced)} guild commands to `{dev_guild_id}`")
                else:
                    synced = await self.tree.sync()
                    await ctx.send(f"✅ Synced {len(synced)} global commands (may take up to 1h to appear)")
            except Exception as e:
                await ctx.send(f"❌ Sync failed: {e}")

        @self.command(name="cogs")
        @is_owner()
        async def list_cogs_cmd(ctx):
            """List all loaded cogs."""
            loaded = list(self.cogs.keys())
            await ctx.send(f"📦 Loaded cogs ({len(loaded)}):\n{', '.join(loaded)}")

        @self.command(name="ownerinfo")
        @is_owner()
        async def ownerinfo_cmd(ctx):
            """Debug: show owner IDs and your ID."""
            config_owners = ", ".join(str(oid) for oid in self.owner_ids) if self.owner_ids else "None"
            await ctx.send(
                f"**Config OWNER_IDS:** {config_owners}\n"
                f"**Hardcoded OWNER_ID:** {OWNER_ID}\n"
                f"**Your ID:** {ctx.author.id}\n"
                f"**Is owner?** {ctx.author.id in self.owner_ids or ctx.author.id == OWNER_ID}"
            )

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
            error_msg = f"Unhandled error in {ctx.command}: {error}\n{traceback.format_exc()}"
            log.error(error_msg)
            await send_dm_to_owner(self, f"⚠️ Command error:\n```py\n{error_msg[:1900]}\n```")
            await ctx.reply("An unexpected error occurred. The owner has been notified.", mention_author=False)

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        msg = "An error occurred."
        if isinstance(error, discord.app_commands.MissingPermissions):
            msg = f"You need: `{'`, `'.join(error.missing_permissions)}`"
        elif isinstance(error, discord.app_commands.BotMissingPermissions):
            msg = f"I need: `{'`, `'.join(error.missing_permissions)}`"
        elif isinstance(error, discord.app_commands.CommandOnCooldown):
            msg = f"Cooldown! Try again in `{error.retry_after:.1f}s`."
        else:
            error_msg = f"Slash command error: {error}\n{traceback.format_exc()}"
            log.error(error_msg)
            await send_dm_to_owner(self, f"⚠️ Slash command error:\n```py\n{error_msg[:1900]}\n```")
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
