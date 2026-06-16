"""
cogs/jtc.py
Slash group: /jtc
Join-to-Create voice channel system.

Panel is posted ONCE in a channel. All JTC owners use the same persistent
panel — buttons check that the clicker owns an active JTC channel.
Buttons are emoji-only; the embed lists the key.
12 buttons across 3 rows of 4.
"""

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from config import Config
from utils.data import load, save

JTC_FILE = "jtc.json"

# ── Data helpers ──────────────────────────────────────

def _settings(guild_id: int) -> dict:
    return load(JTC_FILE).get(str(guild_id), {})

def _save_settings(guild_id: int, s: dict):
    data = load(JTC_FILE)
    data[str(guild_id)] = s
    save(JTC_FILE, data)

def _get_channel(guild_id: int, channel_id: int) -> dict | None:
    return _settings(guild_id).get("channels", {}).get(str(channel_id))

def _save_channel(guild_id: int, channel_id: int, ch_data: dict):
    data = load(JTC_FILE)
    s    = data.setdefault(str(guild_id), {})
    s.setdefault("channels", {})[str(channel_id)] = ch_data
    save(JTC_FILE, data)

def _remove_channel(guild_id: int, channel_id: int):
    data = load(JTC_FILE)
    data.get(str(guild_id), {}).get("channels", {}).pop(str(channel_id), None)
    save(JTC_FILE, data)

# ── Owner check helper ────────────────────────────────

async def _get_owner_vc(interaction: discord.Interaction):
    """
    Returns the VoiceChannel the user owns, or sends an error and returns None.
    The user must be in a voice channel AND own a JTC channel that matches.
    """
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message(
            "❌ You must be inside your JTC voice channel to use this.", ephemeral=True
        )
        return None
    vc      = interaction.user.voice.channel
    ch_data = _get_channel(interaction.guild.id, vc.id)
    if not ch_data:
        await interaction.response.send_message(
            "❌ That channel is not a JTC channel.", ephemeral=True
        )
        return None
    if ch_data.get("owner_id") != interaction.user.id:
        owner = interaction.guild.get_member(ch_data.get("owner_id", 0))
        await interaction.response.send_message(
            f"❌ You are not the owner of this JTC channel."
            + (f" It belongs to {owner.mention}." if owner else ""),
            ephemeral=True,
        )
        return None
    return vc

# ── Modals ────────────────────────────────────────────

class RenameModal(discord.ui.Modal, title="Rename Channel"):
    name = discord.ui.TextInput(label="New channel name", min_length=1, max_length=32)

    async def on_submit(self, interaction: discord.Interaction):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        await vc.edit(name=self.name.value)
        ch_data = _get_channel(interaction.guild.id, vc.id)
        _save_channel(interaction.guild.id, vc.id, {**ch_data, "name": self.name.value})
        await interaction.response.send_message(
            f"✅ Channel renamed to **{self.name.value}**.", ephemeral=True
        )

class LimitModal(discord.ui.Modal, title="Set User Limit"):
    limit = discord.ui.TextInput(
        label="User limit (0 = unlimited)", placeholder="0–99", min_length=1, max_length=2
    )

    async def on_submit(self, interaction: discord.Interaction):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        try:
            lim = int(self.limit.value)
            if not (0 <= lim <= 99):
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                "❌ Enter a number between 0 and 99.", ephemeral=True
            )
        await vc.edit(user_limit=lim)
        await interaction.response.send_message(
            f"✅ User limit set to **{lim or 'Unlimited'}**.", ephemeral=True
        )

class BitrateModal(discord.ui.Modal, title="Set Bitrate"):
    bitrate = discord.ui.TextInput(
        label="Bitrate in kbps (8–96)", placeholder="64", min_length=1, max_length=3
    )

    async def on_submit(self, interaction: discord.Interaction):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        try:
            kbps = int(self.bitrate.value)
            if not (8 <= kbps <= 96):
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                "❌ Enter a bitrate between 8 and 96 kbps.", ephemeral=True
            )
        await vc.edit(bitrate=kbps * 1000)
        await interaction.response.send_message(
            f"✅ Bitrate set to **{kbps} kbps**.", ephemeral=True
        )

class KickUserModal(discord.ui.Modal, title="Kick User from Channel"):
    user_id = discord.ui.TextInput(
        label="User ID or @mention (ID only)", placeholder="123456789012345678", max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        try:
            uid    = int(self.user_id.value.strip().strip("<@!>"))
            member = interaction.guild.get_member(uid)
        except ValueError:
            return await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        if not member:
            return await interaction.response.send_message("❌ Member not found.", ephemeral=True)
        if member.id == interaction.user.id:
            return await interaction.response.send_message("❌ You can't kick yourself.", ephemeral=True)
        if not member.voice or member.voice.channel != vc:
            return await interaction.response.send_message(
                f"❌ {member.mention} is not in your channel.", ephemeral=True
            )
        ow              = vc.overwrites_for(member)
        ow.connect      = False
        ow.view_channel = False
        await vc.set_permissions(member, overwrite=ow)
        await member.move_to(None)
        await interaction.response.send_message(
            f"👢 Kicked and blocked **{member.display_name}** from rejoining.", ephemeral=True
        )

class AllowUserModal(discord.ui.Modal, title="Allow User into Channel"):
    user_id = discord.ui.TextInput(
        label="User ID", placeholder="123456789012345678", max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        try:
            uid    = int(self.user_id.value.strip().strip("<@!>"))
            member = interaction.guild.get_member(uid)
        except ValueError:
            return await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        if not member:
            return await interaction.response.send_message("❌ Member not found.", ephemeral=True)
        ow              = vc.overwrites_for(member)
        ow.connect      = True
        ow.view_channel = True
        await vc.set_permissions(member, overwrite=ow)
        await interaction.response.send_message(
            f"✅ **{member.display_name}** can now join your channel.", ephemeral=True
        )

class AllowRoleModal(discord.ui.Modal, title="Allow Role into Channel"):
    role_id = discord.ui.TextInput(
        label="Role ID", placeholder="123456789012345678", max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        try:
            rid  = int(self.role_id.value.strip().strip("<@&>"))
            role = interaction.guild.get_role(rid)
        except ValueError:
            return await interaction.response.send_message("❌ Invalid role ID.", ephemeral=True)
        if not role:
            return await interaction.response.send_message("❌ Role not found.", ephemeral=True)
        ow              = vc.overwrites_for(role)
        ow.connect      = True
        ow.view_channel = True
        await vc.set_permissions(role, overwrite=ow)
        await interaction.response.send_message(
            f"✅ **{role.name}** can now join your channel.", ephemeral=True
        )

class TransferModal(discord.ui.Modal, title="Transfer Ownership"):
    user_id = discord.ui.TextInput(
        label="New owner's User ID", placeholder="123456789012345678", max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        try:
            uid    = int(self.user_id.value.strip().strip("<@!>"))
            member = interaction.guild.get_member(uid)
        except ValueError:
            return await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        if not member:
            return await interaction.response.send_message("❌ Member not found.", ephemeral=True)
        if member.id == interaction.user.id:
            return await interaction.response.send_message(
                "❌ You already own this channel.", ephemeral=True
            )
        if not member.voice or member.voice.channel != vc:
            return await interaction.response.send_message(
                f"❌ {member.mention} must be in your channel.", ephemeral=True
            )
        new_ow                 = vc.overwrites_for(member)
        new_ow.connect         = True
        new_ow.view_channel    = True
        new_ow.manage_channels = True
        new_ow.move_members    = True
        await vc.set_permissions(member, overwrite=new_ow)

        old_ow                 = vc.overwrites_for(interaction.user)
        old_ow.manage_channels = False
        old_ow.move_members    = False
        await vc.set_permissions(interaction.user, overwrite=old_ow)

        ch_data             = _get_channel(interaction.guild.id, vc.id)
        ch_data["owner_id"] = member.id
        _save_channel(interaction.guild.id, vc.id, ch_data)
        await interaction.response.send_message(
            f"👑 Ownership transferred to **{member.display_name}**.", ephemeral=True
        )

# ── Region Select ─────────────────────────────────────

REGIONS = {
    "automatic":    None,
    "brazil":       "brazil",
    "eu-central":   "eu-central",
    "eu-west":      "eu-west",
    "hong-kong":    "hongkong",
    "india":        "india",
    "japan":        "japan",
    "rotterdam":    "rotterdam",
    "russia":       "russia",
    "singapore":    "singapore",
    "south-africa": "southafrica",
    "sydney":       "sydney",
    "us-central":   "us-central",
    "us-east":      "us-east",
    "us-south":     "us-south",
    "us-west":      "us-west",
}

class RegionSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label.title(), value=label)
            for label in REGIONS
        ]
        super().__init__(
            placeholder="🌐 Select a voice region…",
            options=options,
            custom_id="jtc_region_select",
        )

    async def callback(self, interaction: discord.Interaction):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        region = REGIONS[self.values[0]]
        await vc.edit(rtc_region=region)
        label = self.values[0].title()
        await interaction.response.send_message(
            f"🌐 Voice region set to **{label}**.", ephemeral=True
        )

class RegionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(RegionSelect())

# ── Persistent Control Panel ──────────────────────────
# 12 emoji-only buttons, 4 per row across 3 rows.
# Row 0: 🔒 Lock | 🔓 Unlock | 🙈 Hide | 👁️ Unhide
# Row 1: 🎭 Allow Role | ✅ Allow User | 👢 Kick | 👑 Transfer
# Row 2: 🌐 Region | 👥 Limit | 🎙️ Bitrate | ✏️ Rename
# All buttons are secondary (grey) and never change appearance.
# Each sends an ephemeral confirmation or opens a modal.

class JTCControlPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    # ── Row 0 — Privacy ───────────────────────────────

    @discord.ui.button(emoji="🔒", style=discord.ButtonStyle.secondary,
                       row=0, custom_id="jtc_lock")
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        ow         = vc.overwrites_for(interaction.guild.default_role)
        ow.connect = False
        await vc.set_permissions(interaction.guild.default_role, overwrite=ow)
        await interaction.response.send_message("🔒 Channel **locked**.", ephemeral=True)

    @discord.ui.button(emoji="🔓", style=discord.ButtonStyle.secondary,
                       row=0, custom_id="jtc_unlock")
    async def unlock(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        ow         = vc.overwrites_for(interaction.guild.default_role)
        ow.connect = None
        await vc.set_permissions(interaction.guild.default_role, overwrite=ow)
        await interaction.response.send_message("🔓 Channel **unlocked**.", ephemeral=True)

    @discord.ui.button(emoji="🙈", style=discord.ButtonStyle.secondary,
                       row=0, custom_id="jtc_hide")
    async def hide(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        ow              = vc.overwrites_for(interaction.guild.default_role)
        ow.view_channel = False
        await vc.set_permissions(interaction.guild.default_role, overwrite=ow)
        await interaction.response.send_message("🙈 Channel **hidden**.", ephemeral=True)

    @discord.ui.button(emoji="👁️", style=discord.ButtonStyle.secondary,
                       row=0, custom_id="jtc_unhide")
    async def unhide(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        ow              = vc.overwrites_for(interaction.guild.default_role)
        ow.view_channel = None
        await vc.set_permissions(interaction.guild.default_role, overwrite=ow)
        await interaction.response.send_message("👁️ Channel **visible**.", ephemeral=True)

    # ── Row 1 — Members ───────────────────────────────

    @discord.ui.button(emoji="🎭", style=discord.ButtonStyle.secondary,
                       row=1, custom_id="jtc_allow_role")
    async def allow_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        await interaction.response.send_modal(AllowRoleModal())

    @discord.ui.button(emoji="✅", style=discord.ButtonStyle.secondary,
                       row=1, custom_id="jtc_allow_user")
    async def allow_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        await interaction.response.send_modal(AllowUserModal())

    @discord.ui.button(emoji="👢", style=discord.ButtonStyle.secondary,
                       row=1, custom_id="jtc_kick")
    async def kick_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        await interaction.response.send_modal(KickUserModal())

    @discord.ui.button(emoji="👑", style=discord.ButtonStyle.secondary,
                       row=1, custom_id="jtc_transfer")
    async def transfer(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        await interaction.response.send_modal(TransferModal())

    # ── Row 2 — Settings ──────────────────────────────

    @discord.ui.button(emoji="🌐", style=discord.ButtonStyle.secondary,
                       row=2, custom_id="jtc_region")
    async def region(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        await interaction.response.send_message(
            "🌐 Select a voice region:", view=RegionView(), ephemeral=True
        )

    @discord.ui.button(emoji="👥", style=discord.ButtonStyle.secondary,
                       row=2, custom_id="jtc_limit")
    async def limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        await interaction.response.send_modal(LimitModal())

    @discord.ui.button(emoji="🎙️", style=discord.ButtonStyle.secondary,
                       row=2, custom_id="jtc_bitrate")
    async def bitrate(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        await interaction.response.send_modal(BitrateModal())

    @discord.ui.button(emoji="✏️", style=discord.ButtonStyle.secondary,
                       row=2, custom_id="jtc_rename")
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = await _get_owner_vc(interaction)
        if not vc:
            return
        await interaction.response.send_modal(RenameModal())


# ── Panel embed ───────────────────────────────────────

def _panel_embed(guild: discord.Guild) -> discord.Embed:
    e = discord.Embed(
        title="🔊 Voice Channel Control Panel",
        description=(
            "Join the **Join to Create** channel to get your own voice channel, "
            "then use the buttons below to manage it.\n\n"
            "🔒 Lock · 🔓 Unlock · 🙈 Hide · 👁️ Unhide\n"
            "🎭 Role · ✅ User · 👢 Kick · 👑 Transfer\n"
            "🌐 Region · 👥 Limit · 🎙️ Bitrate · ✏️ Rename"
        ),
        color=Config.COLOR_INFO,
    )
    e.set_footer(text="Only the channel owner can use these buttons.")
    if guild.icon:
        e.set_thumbnail(url=guild.icon.url)
    return e

# ── Cog ───────────────────────────────────────────────

class JTC(commands.Cog):
    """🔊 Join-to-Create voice channel system."""

    slash = app_commands.Group(name="jtc", description="Join-to-Create voice system commands")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(JTCControlPanel())

    # ── Voice events ──────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after:  discord.VoiceState,
    ):
        guild  = member.guild
        s      = _settings(guild.id)
        jtc_id = s.get("jtc_channel")
        if not jtc_id:
            return

        # ── Joined the trigger channel ─────────────────
        if after.channel and str(after.channel.id) == str(jtc_id):
            name_template = s.get("name_template", "{username}'s Channel")
            user_limit    = s.get("user_limit", 0)
            channel_name  = name_template.replace("{username}", member.display_name)
            category      = after.channel.category

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(connect=True, view_channel=True),
                member:             discord.PermissionOverwrite(
                    connect=True, view_channel=True,
                    manage_channels=True, move_members=True,
                ),
                guild.me:           discord.PermissionOverwrite(
                    connect=True, view_channel=True,
                    manage_channels=True, move_members=True,
                ),
            }
            try:
                vc = await guild.create_voice_channel(
                    name=channel_name,
                    category=category,
                    user_limit=user_limit,
                    overwrites=overwrites,
                )
                await member.move_to(vc)
                _save_channel(guild.id, vc.id, {
                    "owner_id": member.id,
                    "name":     channel_name,
                })
            except Exception as e:
                print(f"[JTC] Failed to create channel: {e}")

        # ── Left a JTC channel ─────────────────────────
        if before.channel and before.channel != after.channel:
            ch_data = _get_channel(guild.id, before.channel.id)
            if not ch_data:
                return

            human_members = [m for m in before.channel.members if not m.bot]

            if not human_members:
                try:
                    await before.channel.delete(reason="JTC: Empty channel")
                except Exception:
                    pass
                _remove_channel(guild.id, before.channel.id)

            elif ch_data.get("owner_id") == member.id:
                new_owner           = human_members[0]
                ch_data["owner_id"] = new_owner.id
                _save_channel(guild.id, before.channel.id, ch_data)
                try:
                    ow                 = before.channel.overwrites_for(new_owner)
                    ow.manage_channels = True
                    ow.move_members    = True
                    await before.channel.set_permissions(new_owner, overwrite=ow)
                    await before.channel.send(
                        f"👑 {new_owner.mention} is now the channel owner."
                    )
                except Exception:
                    pass

    # ── /jtc setup ────────────────────────────────────

    @slash.command(name="setup", description="Set the JTC trigger voice channel and post the control panel.")
    @app_commands.describe(
        trigger="Voice channel members join to create their own",
        panel_channel="Text channel where the persistent control panel will be posted",
    )
    @app_commands.default_permissions(administrator=True)
    async def jtc_setup(
        self,
        interaction: discord.Interaction,
        trigger: discord.VoiceChannel,
        panel_channel: discord.TextChannel,
    ):
        await interaction.response.defer(ephemeral=True)

        s = _settings(interaction.guild.id)
        s["jtc_channel"] = trigger.id

        old_panel_msg = s.get("panel_message_id")
        old_panel_ch  = s.get("control_panel_channel")
        if old_panel_msg and old_panel_ch:
            try:
                ch  = interaction.guild.get_channel(int(old_panel_ch))
                msg = await ch.fetch_message(int(old_panel_msg))
                await msg.delete()
            except Exception:
                pass

        msg = await panel_channel.send(
            embed=_panel_embed(interaction.guild),
            view=JTCControlPanel(),
        )
        s["control_panel_channel"] = panel_channel.id
        s["panel_message_id"]      = msg.id
        _save_settings(interaction.guild.id, s)

        await interaction.followup.send(
            f"✅ JTC trigger set to **{trigger.name}**.\n"
            f"📋 Control panel posted in {panel_channel.mention}.",
            ephemeral=True,
        )

    # ── /jtc nametemplate ─────────────────────────────

    @slash.command(name="nametemplate", description="Set the name template for new JTC channels.")
    @app_commands.describe(template="Use {username} as a placeholder for the member's display name.")
    @app_commands.default_permissions(administrator=True)
    async def jtc_nametemplate(self, interaction: discord.Interaction, template: str):
        s = _settings(interaction.guild.id)
        s["name_template"] = template
        _save_settings(interaction.guild.id, s)
        await interaction.response.send_message(
            f"✅ Name template set to: `{template}`", ephemeral=True
        )

    # ── /jtc setlimit ─────────────────────────────────

    @slash.command(name="setlimit", description="Set the default user limit for new JTC channels.")
    @app_commands.describe(limit="Max users per channel (0 = unlimited)")
    @app_commands.default_permissions(administrator=True)
    async def jtc_setlimit(self, interaction: discord.Interaction, limit: int):
        if not (0 <= limit <= 99):
            return await interaction.response.send_message(
                "❌ Limit must be 0–99.", ephemeral=True
            )
        s = _settings(interaction.guild.id)
        s["user_limit"] = limit
        _save_settings(interaction.guild.id, s)
        await interaction.response.send_message(
            f"✅ Default user limit set to **{limit or 'Unlimited'}**.", ephemeral=True
        )

    # ── /jtc updatepanel ──────────────────────────────

    @slash.command(name="updatepanel", description="Refresh the control panel embed (if it was edited or lost).")
    @app_commands.default_permissions(administrator=True)
    async def jtc_updatepanel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        s      = _settings(interaction.guild.id)
        ch_id  = s.get("control_panel_channel")
        msg_id = s.get("panel_message_id")
        if not ch_id or not msg_id:
            return await interaction.followup.send(
                "❌ No panel found. Run `/jtc setup` first.", ephemeral=True
            )
        ch = interaction.guild.get_channel(int(ch_id))
        if not ch:
            return await interaction.followup.send(
                "❌ Panel channel no longer exists. Run `/jtc setup` again.", ephemeral=True
            )
        try:
            msg = await ch.fetch_message(int(msg_id))
            await msg.edit(embed=_panel_embed(interaction.guild), view=JTCControlPanel())
            await interaction.followup.send("✅ Panel updated.", ephemeral=True)
        except discord.NotFound:
            msg = await ch.send(
                embed=_panel_embed(interaction.guild), view=JTCControlPanel()
            )
            s["panel_message_id"] = msg.id
            _save_settings(interaction.guild.id, s)
            await interaction.followup.send("✅ Panel was missing — reposted it.", ephemeral=True)

    # ── /jtc info ─────────────────────────────────────

    @slash.command(name="info", description="Show the current JTC configuration.")
    @app_commands.default_permissions(manage_channels=True)
    async def jtc_info(self, interaction: discord.Interaction):
        s        = _settings(interaction.guild.id)
        jtc_id   = s.get("jtc_channel")
        panel_id = s.get("control_panel_channel")
        jtc_ch   = interaction.guild.get_channel(int(jtc_id))   if jtc_id   else None
        panel_ch = interaction.guild.get_channel(int(panel_id)) if panel_id else None
        active   = len(s.get("channels", {}))

        e = discord.Embed(title="🔊 JTC Configuration", color=Config.COLOR_INFO)
        e.add_field(name="Trigger Channel", value=jtc_ch.mention   if jtc_ch   else "Not set", inline=True)
        e.add_field(name="Panel Channel",   value=panel_ch.mention if panel_ch else "Not set", inline=True)
        e.add_field(name="Name Template",   value=s.get("name_template", "{username}'s Channel"), inline=False)
        e.add_field(name="Default Limit",   value=str(s.get("user_limit", 0)) + (" (unlimited)" if not s.get("user_limit") else ""), inline=True)
        e.add_field(name="Active Channels", value=str(active), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── Prefix convenience commands ───────────────────

    @commands.command(name="jtcsetup")
    @commands.has_permissions(administrator=True)
    async def jtcsetup_prefix(self, ctx, trigger: discord.VoiceChannel, panel: discord.TextChannel):
        """Set the JTC trigger channel and post the control panel."""
        s = _settings(ctx.guild.id)
        s["jtc_channel"] = trigger.id
        msg = await panel.send(embed=_panel_embed(ctx.guild), view=JTCControlPanel())
        s["control_panel_channel"] = panel.id
        s["panel_message_id"]      = msg.id
        _save_settings(ctx.guild.id, s)
        await ctx.reply(
            f"✅ JTC trigger: **{trigger.name}** | Panel posted in {panel.mention}"
        )

    @commands.command(name="jtcinfo")
    async def jtcinfo_prefix(self, ctx):
        """Show JTC config."""
        s        = _settings(ctx.guild.id)
        jtc_id   = s.get("jtc_channel")
        panel_id = s.get("control_panel_channel")
        jtc_ch   = ctx.guild.get_channel(int(jtc_id))   if jtc_id   else None
        panel_ch = ctx.guild.get_channel(int(panel_id)) if panel_id else None
        active   = len(s.get("channels", {}))
        e = discord.Embed(title="🔊 JTC Info", color=Config.COLOR_INFO)
        e.add_field(name="Trigger",  value=jtc_ch.mention   if jtc_ch   else "Not set")
        e.add_field(name="Panel",    value=panel_ch.mention if panel_ch else "Not set")
        e.add_field(name="Template", value=s.get("name_template", "{username}'s Channel"))
        e.add_field(name="Limit",    value=s.get("user_limit", 0) or "Unlimited")
        e.add_field(name="Active",   value=active)
        await ctx.reply(embed=e)


async def setup(bot: commands.Bot):
    await bot.add_cog(JTC(bot))
