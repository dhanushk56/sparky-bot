"""
cogs/mc.py
Slash group: /mc
Minecraft server integration via RCON — supports multiple named servers.

Setup:
    Run /mc setup for each of your servers, giving each one a name.
    Example:
        /mc setup name:survival  host:node1.laternodes.com port:25575 password:pass1
        /mc setup name:creative  host:node1.laternodes.com port:25576 password:pass2
        /mc setup name:skyblock  host:node1.laternodes.com port:25577 password:pass3

    Every command then has an optional server: argument to pick which one.
    If you only have one server registered, it is used automatically.

Optional config.py value:
    MC_LINKED_ROLE = None   # role ID to grant when a member links their account

Requirements: none (uses built-in socket/struct only)
"""

import asyncio
import re
import socket
import struct
import discord
from discord.ext import commands
from discord import app_commands
from config import Config
from utils.data import load, save

# ---------------------------------------------------------------------------
# File keys
# ---------------------------------------------------------------------------

MC_DATA_FILE   = "mc_links.json"
MC_CONFIG_FILE = "mc_config.json"

IGN_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")

# ---------------------------------------------------------------------------
# Raw-socket RCON  (no third-party library needed)
# ---------------------------------------------------------------------------

def _pack_packet(req_id: int, pkt_type: int, payload: str) -> bytes:
    body = payload.encode("utf-8") + b"\x00"
    length = 4 + 4 + len(body) + 1          # id + type + body + trailing null
    return struct.pack("<iii", length, req_id, pkt_type) + body + b"\x00"


def _unpack_packet(data: bytes):
    req_id, pkt_type = struct.unpack_from("<ii", data, 0)
    payload = data[8:-2].decode("utf-8", errors="replace")
    return req_id, pkt_type, payload


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("RCON socket closed unexpectedly")
        buf += chunk
    return buf


def _do_rcon(host: str, port: int, password: str, command: str) -> str:
    with socket.create_connection((host, port), timeout=10) as sock:
        # Authenticate
        sock.sendall(_pack_packet(1, 3, password))
        length = struct.unpack_from("<i", _recv_exact(sock, 4))[0]
        auth_data = _recv_exact(sock, length)
        auth_id, _, _ = _unpack_packet(auth_data)
        if auth_id == -1:
            raise PermissionError("RCON authentication failed — wrong password?")
        # Send command
        sock.sendall(_pack_packet(2, 2, command))
        length = struct.unpack_from("<i", _recv_exact(sock, 4))[0]
        resp_data = _recv_exact(sock, length)
        _, _, response = _unpack_packet(resp_data)
        return response


async def rcon(host: str, port: int, password: str, command: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_rcon, host, port, password, command)


# ---------------------------------------------------------------------------
# Multi-server config helpers
# ---------------------------------------------------------------------------

def _guild_servers(guild_id: int) -> dict:
    return load(MC_CONFIG_FILE).get(str(guild_id), {})


def _save_server(guild_id: int, name: str, host: str, port: int, password: str):
    data = load(MC_CONFIG_FILE)
    data.setdefault(str(guild_id), {})[name.lower()] = {
        "host": host, "port": port, "password": password
    }
    save(MC_CONFIG_FILE, data)


def _remove_server(guild_id: int, name: str) -> bool:
    data = load(MC_CONFIG_FILE)
    gk = str(guild_id)
    if name.lower() in data.get(gk, {}):
        del data[gk][name.lower()]
        save(MC_CONFIG_FILE, data)
        return True
    return False


def _resolve_server(guild_id: int, name):
    servers = _guild_servers(guild_id)
    if not servers:
        return None, None
    if name:
        cfg = servers.get(name.lower())
        return (name.lower(), cfg) if cfg else (None, None)
    if len(servers) == 1:
        k = next(iter(servers))
        return k, servers[k]
    return None, None


def _footer(srv_name: str, guild_id: int) -> str:
    cfg = _guild_servers(guild_id).get(srv_name, {})
    return "Server: {}  |  {}:{}".format(srv_name, cfg.get("host", ""), cfg.get("port", ""))


# ---------------------------------------------------------------------------
# Account-link helpers
# ---------------------------------------------------------------------------

def _get_ign(discord_id: int):
    return load(MC_DATA_FILE).get(str(discord_id))


def _set_ign(discord_id: int, ign: str):
    data = load(MC_DATA_FILE)
    data[str(discord_id)] = ign
    save(MC_DATA_FILE, data)


def _unlink_ign(discord_id: int):
    data = load(MC_DATA_FILE)
    data.pop(str(discord_id), None)
    save(MC_DATA_FILE, data)


def _discord_from_ign(ign: str):
    ign_lower = ign.lower()
    for uid, stored in load(MC_DATA_FILE).items():
        if stored.lower() == ign_lower:
            return int(uid)
    return None


# ---------------------------------------------------------------------------
# Embed helpers
# ---------------------------------------------------------------------------

def _ok(title: str, desc: str) -> discord.Embed:
    return discord.Embed(title=title, description=desc, color=Config.COLOR_OK)


def _err(desc: str) -> discord.Embed:
    return discord.Embed(description="ERROR: " + desc, color=Config.COLOR_ERR)


# ---------------------------------------------------------------------------
# Core exec helper
# ---------------------------------------------------------------------------

async def _exec(interaction: discord.Interaction, command: str, server=None):
    servers = _guild_servers(interaction.guild_id)

    if not servers:
        await interaction.followup.send(
            embed=_err("No servers configured. An admin must run /mc setup first."),
            ephemeral=True,
        )
        return None, None

    srv_name, cfg = _resolve_server(interaction.guild_id, server)

    if cfg is None and len(servers) > 1:
        names = ", ".join("`{}`".format(n) for n in servers)
        await interaction.followup.send(
            embed=_err("You have multiple servers. Specify one with the server option: " + names),
            ephemeral=True,
        )
        return None, None

    if cfg is None:
        await interaction.followup.send(
            embed=_err("Server `{}` not found. Use /mc servers to see registered servers.".format(server)),
            ephemeral=True,
        )
        return None, None

    try:
        resp = await rcon(cfg["host"], cfg["port"], cfg["password"], command)
        return resp, srv_name
    except Exception as exc:
        await interaction.followup.send(
            embed=_err("RCON error on {}: `{}`\nMake sure the server is online and RCON is enabled.".format(srv_name, exc)),
            ephemeral=True,
        )
        return None, None


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Minecraft(commands.Cog, name="Minecraft"):
    """Minecraft server integration via RCON (multi-server)."""

    slash = app_commands.Group(name="mc", description="Minecraft server commands")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @slash.command(name="setup", description="Register a Minecraft server. Run once per server.")
    @app_commands.describe(
        name="Short nickname for this server e.g. survival, creative, skyblock",
        host="Server IP or hostname from your Laternode panel",
        port="RCON port set in server.properties (default 25575)",
        password="rcon.password from server.properties",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mc_setup(self, interaction: discord.Interaction, name: str, host: str, password: str, port: int = 25575):
        await interaction.response.defer(ephemeral=True)
        name = name.lower().strip()
        try:
            resp = await rcon(host, port, password, "list")
        except Exception as exc:
            await interaction.followup.send(
                embed=_err("Could not connect to {} ({}:{}): {}\nCheck enable-rcon=true and rcon.password in server.properties.".format(name, host, port, exc)),
                ephemeral=True,
            )
            return
        _save_server(interaction.guild_id, name, host, port, password)
        e = _ok("Server Registered", "**Name:** `{}`\n**Host:** `{}:{}`\n**Test response:** {}".format(name, host, port, resp or "OK"))
        e.set_footer(text="Run /mc setup again with a different name to add another server.")
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="servers", description="List all registered Minecraft servers.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mc_servers(self, interaction: discord.Interaction):
        servers = _guild_servers(interaction.guild_id)
        if not servers:
            await interaction.response.send_message(embed=_err("No servers registered yet. Use /mc setup to add one."), ephemeral=True)
            return
        e = discord.Embed(title="Registered Minecraft Servers", color=Config.COLOR_INFO)
        for sname, cfg in servers.items():
            e.add_field(name="- " + sname, value="`{}:{}`".format(cfg["host"], cfg["port"]), inline=False)
        e.set_footer(text="Use /mc remove to delete a server.")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @slash.command(name="remove", description="Remove a registered Minecraft server.")
    @app_commands.describe(name="Name of the server to remove")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mc_remove(self, interaction: discord.Interaction, name: str):
        if _remove_server(interaction.guild_id, name):
            await interaction.response.send_message(embed=_ok("Server Removed", "`{}` has been unregistered.".format(name)), ephemeral=True)
        else:
            await interaction.response.send_message(embed=_err("No server named `{}` found.".format(name)), ephemeral=True)

    @slash.command(name="status", description="Check who is online on a server.")
    @app_commands.describe(server="Which server to check (leave blank if you only have one)")
    async def mc_status(self, interaction: discord.Interaction, server: str = None):
        await interaction.response.defer()
        resp, srv = await _exec(interaction, "list", server)
        if resp is None:
            return
        e = discord.Embed(title="{} - Online".format(srv), description=resp or "No response", color=Config.COLOR_OK)
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e)

    @slash.command(name="linkaccount", description="Link your Discord account to your Minecraft username.")
    @app_commands.describe(minecraft_username="Your exact Minecraft in-game name")
    async def mc_linkaccount(self, interaction: discord.Interaction, minecraft_username: str):
        await interaction.response.defer(ephemeral=True)
        if not IGN_RE.match(minecraft_username):
            await interaction.followup.send(embed=_err("Invalid username. Only letters, numbers, and underscores (max 16 chars)."), ephemeral=True)
            return
        existing = _discord_from_ign(minecraft_username)
        if existing and existing != interaction.user.id:
            await interaction.followup.send(embed=_err("`{}` is already linked to another Discord account.".format(minecraft_username)), ephemeral=True)
            return
        _set_ign(interaction.user.id, minecraft_username)
        role_note = ""
        linked_role_id = getattr(Config, "MC_LINKED_ROLE", None)
        if linked_role_id:
            role = interaction.guild.get_role(int(linked_role_id))
            if role:
                try:
                    await interaction.user.add_roles(role, reason="Minecraft account linked")
                    role_note = "\nYou have been given the **{}** role.".format(role.name)
                except discord.Forbidden:
                    role_note = "\nCould not assign the linked role (missing permissions)."
        await interaction.followup.send(
            embed=_ok("Account Linked", "Discord: {}\nMinecraft: `{}`{}".format(interaction.user.mention, minecraft_username, role_note)),
            ephemeral=True,
        )

    @slash.command(name="unlinkaccount", description="Unlink your Discord account from Minecraft.")
    async def mc_unlinkaccount(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ign = _get_ign(interaction.user.id)
        if not ign:
            await interaction.followup.send(embed=_err("Your account is not linked."), ephemeral=True)
            return
        _unlink_ign(interaction.user.id)
        await interaction.followup.send(embed=_ok("Unlinked", "Removed link for `{}`.".format(ign)), ephemeral=True)

    @slash.command(name="whois", description="See what Minecraft username a Discord member is linked to.")
    @app_commands.describe(member="Discord member to look up (leave blank for yourself)")
    async def mc_whois(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        ign = _get_ign(target.id)
        if not ign:
            await interaction.response.send_message(embed=_err("{} has not linked a Minecraft account.".format(target.mention)), ephemeral=True)
            return
        e = discord.Embed(title="Linked Account", color=Config.COLOR_INFO)
        e.add_field(name="Discord",   value=target.mention, inline=True)
        e.add_field(name="Minecraft", value="`{}`".format(ign), inline=True)
        e.set_thumbnail(url="https://mc-heads.net/avatar/{}/64".format(ign))
        await interaction.response.send_message(embed=e)

    @slash.command(name="whitelist", description="Add or remove a player from a server whitelist.")
    @app_commands.describe(action="add or remove", username="Minecraft username (leave blank to use your linked account)", server="Which server")
    @app_commands.choices(action=[app_commands.Choice(name="add", value="add"), app_commands.Choice(name="remove", value="remove")])
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def mc_whitelist(self, interaction: discord.Interaction, action: str, username: str = None, server: str = None):
        await interaction.response.defer(ephemeral=True)
        ign = username or _get_ign(interaction.user.id)
        if not ign:
            await interaction.followup.send(embed=_err("No username provided and your account is not linked. Use /mc linkaccount first."), ephemeral=True)
            return
        if not IGN_RE.match(ign):
            await interaction.followup.send(embed=_err("Invalid Minecraft username."), ephemeral=True)
            return
        resp, srv = await _exec(interaction, "whitelist {} {}".format(action, ign), server)
        if resp is None:
            return
        verb = "added to" if action == "add" else "removed from"
        e = _ok("Whitelist Updated", "`{}` has been **{}** the whitelist on **{}**.\n> {}".format(ign, verb, srv, resp or ""))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="whitelist_list", description="Show the whitelist of a server.")
    @app_commands.describe(server="Which server (leave blank if you only have one)")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def mc_whitelist_list(self, interaction: discord.Interaction, server: str = None):
        await interaction.response.defer(ephemeral=True)
        resp, srv = await _exec(interaction, "whitelist list", server)
        if resp is None:
            return
        e = _ok("{} - Whitelist".format(srv), resp or "*(empty)*")
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="say", description="Broadcast a message to everyone on a server.")
    @app_commands.describe(message="Message to broadcast in-game", server="Which server")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def mc_say(self, interaction: discord.Interaction, message: str, server: str = None):
        await interaction.response.defer(ephemeral=True)
        resp, srv = await _exec(interaction, "say [Discord] {}: {}".format(interaction.user.display_name, message), server)
        if resp is None:
            return
        e = _ok("Message Sent", "**{}** to **{}**: {}".format(interaction.user.display_name, srv, message))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="tell", description="Send a private message to a specific in-game player.")
    @app_commands.describe(username="Minecraft username to message", message="Your private message", server="Which server")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def mc_tell(self, interaction: discord.Interaction, username: str, message: str, server: str = None):
        await interaction.response.defer(ephemeral=True)
        if not IGN_RE.match(username):
            await interaction.followup.send(embed=_err("Invalid username."), ephemeral=True)
            return
        resp, srv = await _exec(interaction, "tell {} [Discord] {}: {}".format(username, interaction.user.display_name, message), server)
        if resp is None:
            return
        e = _ok("Message Sent", "Sent to `{}` on **{}**: *{}*".format(username, srv, message))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="kick", description="Kick a player from a Minecraft server.")
    @app_commands.describe(username="Minecraft username", reason="Reason (optional)", server="Which server")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.checks.has_permissions(kick_members=True)
    async def mc_kick(self, interaction: discord.Interaction, username: str, reason: str = "Kicked by Discord admin", server: str = None):
        await interaction.response.defer(ephemeral=True)
        if not IGN_RE.match(username):
            await interaction.followup.send(embed=_err("Invalid username."), ephemeral=True)
            return
        resp, srv = await _exec(interaction, "kick {} {}".format(username, reason), server)
        if resp is None:
            return
        e = _ok("Player Kicked", "`{}` was kicked from **{}**.\n**Reason:** {}\n> {}".format(username, srv, reason, resp or ""))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="ban", description="Ban a player from a Minecraft server.")
    @app_commands.describe(username="Minecraft username", reason="Reason (optional)", server="Which server")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    async def mc_ban(self, interaction: discord.Interaction, username: str, reason: str = "Banned by Discord admin", server: str = None):
        await interaction.response.defer(ephemeral=True)
        if not IGN_RE.match(username):
            await interaction.followup.send(embed=_err("Invalid username."), ephemeral=True)
            return
        resp, srv = await _exec(interaction, "ban {} {}".format(username, reason), server)
        if resp is None:
            return
        e = _ok("Player Banned", "`{}` has been banned from **{}**.\n**Reason:** {}\n> {}".format(username, srv, reason, resp or ""))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="unban", description="Pardon a banned player from a Minecraft server.")
    @app_commands.describe(username="Minecraft username to unban", server="Which server")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    async def mc_unban(self, interaction: discord.Interaction, username: str, server: str = None):
        await interaction.response.defer(ephemeral=True)
        if not IGN_RE.match(username):
            await interaction.followup.send(embed=_err("Invalid username."), ephemeral=True)
            return
        resp, srv = await _exec(interaction, "pardon {}".format(username), server)
        if resp is None:
            return
        e = _ok("Player Unbanned", "`{}` has been pardoned on **{}**.\n> {}".format(username, srv, resp or ""))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="op", description="Grant operator status to a player.")
    @app_commands.describe(username="Minecraft username", server="Which server")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mc_op(self, interaction: discord.Interaction, username: str, server: str = None):
        await interaction.response.defer(ephemeral=True)
        if not IGN_RE.match(username):
            await interaction.followup.send(embed=_err("Invalid username."), ephemeral=True)
            return
        resp, srv = await _exec(interaction, "op {}".format(username), server)
        if resp is None:
            return
        e = _ok("OP Granted", "`{}` is now an operator on **{}**.\n> {}".format(username, srv, resp or ""))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="deop", description="Revoke operator status from a player.")
    @app_commands.describe(username="Minecraft username", server="Which server")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mc_deop(self, interaction: discord.Interaction, username: str, server: str = None):
        await interaction.response.defer(ephemeral=True)
        if not IGN_RE.match(username):
            await interaction.followup.send(embed=_err("Invalid username."), ephemeral=True)
            return
        resp, srv = await _exec(interaction, "deop {}".format(username), server)
        if resp is None:
            return
        e = _ok("OP Revoked", "`{}` is no longer an operator on **{}**.\n> {}".format(username, srv, resp or ""))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="gamemode", description="Change the gamemode of a player.")
    @app_commands.describe(mode="Game mode to set", username="Minecraft username (leave blank to use your linked account)", server="Which server")
    @app_commands.choices(mode=[
        app_commands.Choice(name="survival",  value="survival"),
        app_commands.Choice(name="creative",  value="creative"),
        app_commands.Choice(name="adventure", value="adventure"),
        app_commands.Choice(name="spectator", value="spectator"),
    ])
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mc_gamemode(self, interaction: discord.Interaction, mode: str, username: str = None, server: str = None):
        await interaction.response.defer(ephemeral=True)
        ign = username or _get_ign(interaction.user.id)
        if not ign:
            await interaction.followup.send(embed=_err("No username provided and your account is not linked."), ephemeral=True)
            return
        resp, srv = await _exec(interaction, "gamemode {} {}".format(mode, ign), server)
        if resp is None:
            return
        e = _ok("Gamemode Changed", "`{}` set to **{}** on **{}**.\n> {}".format(ign, mode, srv, resp or ""))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="give", description="Give a player items.")
    @app_commands.describe(username="Minecraft username", item="Item ID e.g. minecraft:diamond", amount="How many (1-64, default 1)", server="Which server")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mc_give(self, interaction: discord.Interaction, username: str, item: str, amount: int = 1, server: str = None):
        await interaction.response.defer(ephemeral=True)
        if not IGN_RE.match(username):
            await interaction.followup.send(embed=_err("Invalid username."), ephemeral=True)
            return
        if not 1 <= amount <= 64:
            await interaction.followup.send(embed=_err("Amount must be between 1 and 64."), ephemeral=True)
            return
        resp, srv = await _exec(interaction, "give {} {} {}".format(username, item, amount), server)
        if resp is None:
            return
        e = _ok("Items Given", "Gave **{}x {}** to `{}` on **{}**.\n> {}".format(amount, item, username, srv, resp or ""))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="tp", description="Teleport a player to another player or coordinates.")
    @app_commands.describe(player="Player to teleport", target="Target player name OR x y z coordinates", server="Which server")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mc_tp(self, interaction: discord.Interaction, player: str, target: str, server: str = None):
        await interaction.response.defer(ephemeral=True)
        resp, srv = await _exec(interaction, "tp {} {}".format(player, target), server)
        if resp is None:
            return
        e = _ok("Teleported", "`{}` to `{}` on **{}**.\n> {}".format(player, target, srv, resp or ""))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="time", description="Set the time of day on a server.")
    @app_commands.describe(time_of_day="Time preset", server="Which server")
    @app_commands.choices(time_of_day=[
        app_commands.Choice(name="day",      value="day"),
        app_commands.Choice(name="noon",     value="noon"),
        app_commands.Choice(name="night",    value="night"),
        app_commands.Choice(name="midnight", value="midnight"),
    ])
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mc_time(self, interaction: discord.Interaction, time_of_day: str, server: str = None):
        await interaction.response.defer(ephemeral=True)
        resp, srv = await _exec(interaction, "time set {}".format(time_of_day), server)
        if resp is None:
            return
        e = _ok("Time Set", "**{}** time set to **{}**.\n> {}".format(srv, time_of_day, resp or ""))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="weather", description="Change the weather on a server.")
    @app_commands.describe(weather="Weather type", server="Which server")
    @app_commands.choices(weather=[
        app_commands.Choice(name="clear",   value="clear"),
        app_commands.Choice(name="rain",    value="rain"),
        app_commands.Choice(name="thunder", value="thunder"),
    ])
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mc_weather(self, interaction: discord.Interaction, weather: str, server: str = None):
        await interaction.response.defer(ephemeral=True)
        resp, srv = await _exec(interaction, "weather {}".format(weather), server)
        if resp is None:
            return
        e = _ok("Weather Changed", "**{}** weather set to **{}**.\n> {}".format(srv, weather, resp or ""))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="difficulty", description="Change the difficulty of a server.")
    @app_commands.describe(level="Difficulty level", server="Which server")
    @app_commands.choices(level=[
        app_commands.Choice(name="peaceful", value="peaceful"),
        app_commands.Choice(name="easy",     value="easy"),
        app_commands.Choice(name="normal",   value="normal"),
        app_commands.Choice(name="hard",     value="hard"),
    ])
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mc_difficulty(self, interaction: discord.Interaction, level: str, server: str = None):
        await interaction.response.defer(ephemeral=True)
        resp, srv = await _exec(interaction, "difficulty {}".format(level), server)
        if resp is None:
            return
        e = _ok("Difficulty Changed", "**{}** set to **{}**.\n> {}".format(srv, level, resp or ""))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="seed", description="Get the world seed of a server.")
    @app_commands.describe(server="Which server (leave blank if you only have one)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mc_seed(self, interaction: discord.Interaction, server: str = None):
        await interaction.response.defer(ephemeral=True)
        resp, srv = await _exec(interaction, "seed", server)
        if resp is None:
            return
        e = _ok("{} - World Seed".format(srv), "`{}`".format(resp))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="save", description="Force a server to save the world to disk.")
    @app_commands.describe(server="Which server (leave blank if you only have one)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mc_save(self, interaction: discord.Interaction, server: str = None):
        await interaction.response.defer(ephemeral=True)
        resp, srv = await _exec(interaction, "save-all", server)
        if resp is None:
            return
        e = _ok("World Saved", "**{}** saved successfully.\n> {}".format(srv, resp or ""))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)

    @slash.command(name="run", description="Run a raw console command on a server. Admin only.")
    @app_commands.describe(command="The Minecraft console command without the leading /", server="Which server")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def mc_run(self, interaction: discord.Interaction, command: str, server: str = None):
        await interaction.response.defer(ephemeral=True)
        resp, srv = await _exec(interaction, command, server)
        if resp is None:
            return
        e = _ok("Command Executed", "**Server:** {}\n**Command:** `{}`\n**Response:** {}".format(srv, command, resp or "*(no output)*"))
        e.set_footer(text=_footer(srv, interaction.guild_id))
        await interaction.followup.send(embed=e, ephemeral=True)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def setup(bot: commands.Bot):
    await bot.add_cog(Minecraft(bot))
