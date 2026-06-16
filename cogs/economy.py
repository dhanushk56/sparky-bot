"""
cogs/economy.py
Slash group: /economy
Prefix commands still work with ~
"""

import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
from datetime import datetime, timezone, timedelta
from config import Config
from utils.data import load, save

ECO_FILE = "economy.json"

SHOP_ITEMS = {
    "vip_role":       {"name": "⭐ VIP Role",        "price": 5000,  "desc": "Get the VIP role"},
    "nickname":       {"name": "✏️ Custom Nickname",  "price": 1000,  "desc": "Change your nickname"},
    "color_role":     {"name": "🎨 Color Role",       "price": 2000,  "desc": "Custom color role"},
    "trophy":         {"name": "🏆 Trophy",            "price": 500,   "desc": "A shiny trophy collectible"},
    "diamond":        {"name": "💎 Diamond",           "price": 10000, "desc": "Ultra rare gem collectible"},
    "lucky_charm":    {"name": "🍀 Lucky Charm",       "price": 750,   "desc": "+10% gamble win chance"},
    "lottery_ticket": {"name": "🎟️ Lottery Ticket",   "price": 100,   "desc": "Enter the daily lottery"},
}


def _get(guild_id: int, user_id: int) -> dict:
    data = load(ECO_FILE)
    gk, uk = str(guild_id), str(user_id)
    data.setdefault(gk, {}).setdefault(uk, {
        "wallet":     Config.STARTING_BALANCE,
        "bank":       0,
        "last_daily": None,
        "last_work":  None,
        "inventory":  [],
    })
    return data[gk][uk]


def _save_user(guild_id: int, user_id: int, user: dict):
    data = load(ECO_FILE)
    data.setdefault(str(guild_id), {})[str(user_id)] = user
    save(ECO_FILE, data)


def eco_embed(title: str, desc: str, color=Config.COLOR_GOLD) -> discord.Embed:
    return discord.Embed(title=title, description=desc, color=color)


class Economy(commands.Cog):
    """💰 Full economy system."""

    slash = app_commands.Group(name="economy", description="Economy commands")

    def __init__(self, bot):
        self.bot = bot

    # ── BALANCE ───────────────────────────────────────

    @commands.command(name="balance", aliases=["bal", "wallet"])
    async def balance(self, ctx, member: discord.Member = None):
        m = member or ctx.author
        u = _get(ctx.guild.id, m.id)
        total = u["wallet"] + u["bank"]
        e = discord.Embed(title=f"💰 {m.display_name}'s Balance", color=Config.COLOR_GOLD)
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name="👛 Wallet",     value=f"`{u['wallet']:,}` {Config.CURRENCY_EMOJI}")
        e.add_field(name="🏦 Bank",       value=f"`{u['bank']:,}` {Config.CURRENCY_EMOJI}")
        e.add_field(name="📊 Net Worth",  value=f"`{total:,}` {Config.CURRENCY_EMOJI}", inline=False)
        await ctx.reply(embed=e)

    @slash.command(name="balance", description="Check your or another member's balance.")
    @app_commands.describe(member="Member to check (leave empty for yourself)")
    async def balance_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.balance.callback(self, ctx, member)

    # ── DAILY ─────────────────────────────────────────

    @commands.command(name="daily")
    async def daily(self, ctx):
        u = _get(ctx.guild.id, ctx.author.id)
        now = datetime.now(timezone.utc)
        if u["last_daily"]:
            last = datetime.fromisoformat(u["last_daily"])
            diff = now - last
            if diff < timedelta(hours=24):
                remaining = timedelta(hours=24) - diff
                h, m_ = divmod(int(remaining.total_seconds()), 3600)
                m_, s  = divmod(m_, 60)
                return await ctx.reply(f"⏰ Daily already claimed! Come back in **{h}h {m_}m {s}s**.")
        u["wallet"]    += Config.DAILY_AMOUNT
        u["last_daily"] = now.isoformat()
        _save_user(ctx.guild.id, ctx.author.id, u)
        await ctx.reply(embed=eco_embed("📅 Daily Claimed!", f"You received **{Config.DAILY_AMOUNT:,}** {Config.CURRENCY_EMOJI}!\nNew balance: **{u['wallet']:,}** {Config.CURRENCY_EMOJI}"))

    @slash.command(name="daily", description=f"Claim your daily coins.")
    async def daily_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.daily.callback(self, ctx)

    # ── WORK ──────────────────────────────────────────

    @commands.command(name="work")
    @commands.cooldown(1, 3600, commands.BucketType.member)
    async def work(self, ctx):
        jobs = ["programmer","chef","teacher","nurse","driver","plumber","artist","mechanic"]
        job    = random.choice(jobs)
        amount = random.randint(Config.WORK_MIN, Config.WORK_MAX)
        u = _get(ctx.guild.id, ctx.author.id)
        u["wallet"] += amount
        _save_user(ctx.guild.id, ctx.author.id, u)
        await ctx.reply(embed=eco_embed("💼 Work Completed!", f"You worked as a **{job}** and earned **{amount:,}** {Config.CURRENCY_EMOJI}!"))

    @slash.command(name="work", description="Work to earn coins (1h cooldown).")
    async def work_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.work.callback(self, ctx)

    # ── PAY ───────────────────────────────────────────

    @commands.command(name="pay")
    async def pay(self, ctx, member: discord.Member, amount: int):
        if member == ctx.author:
            return await ctx.reply("❌ You can't pay yourself.")
        if amount <= 0:
            return await ctx.reply("❌ Amount must be positive.")
        giver = _get(ctx.guild.id, ctx.author.id)
        if giver["wallet"] < amount:
            return await ctx.reply(f"❌ Insufficient funds. You have **{giver['wallet']:,}** {Config.CURRENCY_EMOJI} in your wallet.")
        receiver = _get(ctx.guild.id, member.id)
        giver["wallet"]    -= amount
        receiver["wallet"] += amount
        _save_user(ctx.guild.id, ctx.author.id, giver)
        _save_user(ctx.guild.id, member.id, receiver)
        await ctx.reply(embed=eco_embed("💸 Transfer Complete!", f"{ctx.author.mention} → {member.mention}\n**{amount:,}** {Config.CURRENCY_EMOJI}", Config.COLOR_OK))

    @slash.command(name="pay", description="Transfer coins to another member.")
    @app_commands.describe(member="Recipient", amount="Amount to transfer")
    async def pay_slash(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        ctx = await commands.Context.from_interaction(interaction)
        await self.pay.callback(self, ctx, member, amount)

    # ── DEPOSIT ───────────────────────────────────────

    @commands.command(name="deposit", aliases=["dep"])
    async def deposit(self, ctx, amount: str):
        u = _get(ctx.guild.id, ctx.author.id)
        amt = u["wallet"] if amount.lower() == "all" else int(amount)
        if amt <= 0 or amt > u["wallet"]:
            return await ctx.reply(f"❌ Invalid amount. Wallet: **{u['wallet']:,}**.")
        u["wallet"] -= amt
        u["bank"]   += amt
        _save_user(ctx.guild.id, ctx.author.id, u)
        await ctx.reply(embed=eco_embed("🏦 Deposited!", f"**{amt:,}** {Config.CURRENCY_EMOJI} deposited.\nBank: **{u['bank']:,}** | Wallet: **{u['wallet']:,}**"))

    @slash.command(name="deposit", description="Deposit coins into your bank.")
    @app_commands.describe(amount="Amount or 'all'")
    async def deposit_slash(self, interaction: discord.Interaction, amount: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.deposit.callback(self, ctx, amount)

    # ── WITHDRAW ──────────────────────────────────────

    @commands.command(name="withdraw", aliases=["with"])
    async def withdraw(self, ctx, amount: str):
        u = _get(ctx.guild.id, ctx.author.id)
        amt = u["bank"] if amount.lower() == "all" else int(amount)
        if amt <= 0 or amt > u["bank"]:
            return await ctx.reply(f"❌ Invalid amount. Bank: **{u['bank']:,}**.")
        u["bank"]   -= amt
        u["wallet"] += amt
        _save_user(ctx.guild.id, ctx.author.id, u)
        await ctx.reply(embed=eco_embed("🏦 Withdrawn!", f"**{amt:,}** {Config.CURRENCY_EMOJI} withdrawn.\nWallet: **{u['wallet']:,}** | Bank: **{u['bank']:,}**"))

    @slash.command(name="withdraw", description="Withdraw coins from your bank.")
    @app_commands.describe(amount="Amount or 'all'")
    async def withdraw_slash(self, interaction: discord.Interaction, amount: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.withdraw.callback(self, ctx, amount)

    # ── ROB ───────────────────────────────────────────

    @commands.command(name="rob")
    @commands.cooldown(1, 1800, commands.BucketType.member)
    async def rob(self, ctx, member: discord.Member):
        if member == ctx.author:
            return await ctx.reply("❌ You can't rob yourself.")
        victim = _get(ctx.guild.id, member.id)
        robber = _get(ctx.guild.id, ctx.author.id)
        if victim["wallet"] < 100:
            return await ctx.reply(f"❌ {member.mention} doesn't have enough to rob (min 100 {Config.CURRENCY_EMOJI} in wallet).")
        if random.random() < 0.4:
            fine = random.randint(50, 200)
            robber["wallet"] = max(0, robber["wallet"] - fine)
            _save_user(ctx.guild.id, ctx.author.id, robber)
            return await ctx.reply(embed=eco_embed("🚔 Caught!", f"You were caught trying to rob {member.mention}!\nFine: **{fine}** {Config.CURRENCY_EMOJI}", Config.COLOR_ERR))
        stolen = random.randint(100, min(victim["wallet"], 500))
        victim["wallet"] -= stolen
        robber["wallet"] += stolen
        _save_user(ctx.guild.id, ctx.author.id, robber)
        _save_user(ctx.guild.id, member.id, victim)
        await ctx.reply(embed=eco_embed("🦹 Robbed!", f"You stole **{stolen:,}** {Config.CURRENCY_EMOJI} from {member.mention}!", Config.COLOR_WARN))

    @slash.command(name="rob", description="Attempt to rob another member's wallet.")
    @app_commands.describe(member="Member to rob")
    async def rob_slash(self, interaction: discord.Interaction, member: discord.Member):
        ctx = await commands.Context.from_interaction(interaction)
        await self.rob.callback(self, ctx, member)

    # ── GAMBLE ────────────────────────────────────────

    @commands.command(name="gamble")
    @commands.cooldown(1, 30, commands.BucketType.member)
    async def gamble(self, ctx, amount: str):
        u = _get(ctx.guild.id, ctx.author.id)
        amt = u["wallet"] if amount.lower() == "all" else int(amount)
        if amt <= 0:
            return await ctx.reply("❌ Amount must be positive.")
        if amt > u["wallet"]:
            return await ctx.reply(f"❌ Insufficient funds (wallet: **{u['wallet']:,}**).")
        if random.random() > 0.5:
            u["wallet"] += amt
            desc = f"🎉 You won! +**{amt:,}** {Config.CURRENCY_EMOJI}\nBalance: **{u['wallet']:,}**"
            color = Config.COLOR_OK
        else:
            u["wallet"] -= amt
            desc = f"💸 You lost! -**{amt:,}** {Config.CURRENCY_EMOJI}\nBalance: **{u['wallet']:,}**"
            color = Config.COLOR_ERR
        _save_user(ctx.guild.id, ctx.author.id, u)
        await ctx.reply(embed=eco_embed("🎲 Gamble Result", desc, color))

    @slash.command(name="gamble", description="Gamble your coins (50% chance to double).")
    @app_commands.describe(amount="Amount to gamble or 'all'")
    async def gamble_slash(self, interaction: discord.Interaction, amount: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.gamble.callback(self, ctx, amount)

    # ── SLOTS ─────────────────────────────────────────

    @commands.command(name="slots")
    @commands.cooldown(1, 15, commands.BucketType.member)
    async def slots(self, ctx, bet: int):
        u = _get(ctx.guild.id, ctx.author.id)
        if bet <= 0:
            return await ctx.reply("❌ Bet must be positive.")
        if bet > u["wallet"]:
            return await ctx.reply("❌ Insufficient funds.")
        symbols = ["🍒","🍋","🍊","🍇","⭐","💎","7️⃣"]
        weights = [30, 25, 20, 15, 6, 3, 1]
        reels   = random.choices(symbols, weights=weights, k=3)
        display = " | ".join(reels)
        if reels[0] == reels[1] == reels[2]:
            mult = {"7️⃣": 50, "💎": 20, "⭐": 10}.get(reels[0], 5)
            winnings = bet * mult
            u["wallet"] += winnings
            result = f"🎰 **JACKPOT!** {display}\n+**{winnings:,}** {Config.CURRENCY_EMOJI} (x{mult})"
            color = Config.COLOR_OK
        elif reels[0] == reels[1] or reels[1] == reels[2]:
            winnings = bet
            u["wallet"] += winnings
            result = f"🎰 {display}\n**Two of a kind!** +**{winnings:,}** {Config.CURRENCY_EMOJI}"
            color = Config.COLOR_WARN
        else:
            u["wallet"] -= bet
            result = f"🎰 {display}\n**No match.** -**{bet:,}** {Config.CURRENCY_EMOJI}"
            color = Config.COLOR_ERR
        _save_user(ctx.guild.id, ctx.author.id, u)
        result += f"\nBalance: **{u['wallet']:,}** {Config.CURRENCY_EMOJI}"
        await ctx.reply(embed=eco_embed("🎰 Slot Machine", result, color))

    @slash.command(name="slots", description="Play the slot machine!")
    @app_commands.describe(bet="Amount to bet")
    async def slots_slash(self, interaction: discord.Interaction, bet: int):
        ctx = await commands.Context.from_interaction(interaction)
        await self.slots.callback(self, ctx, bet)

    # ── SHOP ──────────────────────────────────────────

    @commands.command(name="shop")
    async def shop(self, ctx):
        e = discord.Embed(title="🛒 Item Shop", color=Config.COLOR_GOLD)
        for key, item in SHOP_ITEMS.items():
            e.add_field(
                name=f"{item['name']} — `{item['price']:,}` {Config.CURRENCY_EMOJI}",
                value=f"{item['desc']}\nBuy with: `~buy {key}`",
                inline=False
            )
        await ctx.reply(embed=e)

    @slash.command(name="shop", description="View the item shop.")
    async def shop_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.shop.callback(self, ctx)

    # ── BUY ───────────────────────────────────────────

    @commands.command(name="buy")
    async def buy(self, ctx, item: str):
        item = item.lower()
        if item not in SHOP_ITEMS:
            return await ctx.reply(f"❌ Item not found. Use `{Config.PREFIX}shop` to browse.")
        shop_item = SHOP_ITEMS[item]
        u = _get(ctx.guild.id, ctx.author.id)
        if u["wallet"] < shop_item["price"]:
            return await ctx.reply(f"❌ Not enough {Config.CURRENCY_EMOJI}. You need **{shop_item['price']:,}**.")
        u["wallet"] -= shop_item["price"]
        u["inventory"].append(item)
        _save_user(ctx.guild.id, ctx.author.id, u)
        await ctx.reply(embed=eco_embed("🛍️ Purchased!", f"You bought **{shop_item['name']}** for **{shop_item['price']:,}** {Config.CURRENCY_EMOJI}!", Config.COLOR_OK))

    @slash.command(name="buy", description="Buy an item from the shop.")
    @app_commands.describe(item="Item key from the shop")
    async def buy_slash(self, interaction: discord.Interaction, item: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.buy.callback(self, ctx, item)

    # ── INVENTORY ─────────────────────────────────────

    @commands.command(name="inventory", aliases=["inv"])
    async def inventory(self, ctx, member: discord.Member = None):
        m = member or ctx.author
        u = _get(ctx.guild.id, m.id)
        if not u["inventory"]:
            return await ctx.reply(f"📦 {m.mention}'s inventory is empty.")
        from collections import Counter
        inv = Counter(u["inventory"])
        e = discord.Embed(title=f"📦 {m.display_name}'s Inventory", color=Config.COLOR_GOLD)
        for key, qty in inv.items():
            shop_item = SHOP_ITEMS.get(key, {"name": key})
            e.add_field(name=shop_item["name"], value=f"x{qty}", inline=True)
        await ctx.reply(embed=e)

    @slash.command(name="inventory", description="View your inventory.")
    @app_commands.describe(member="Member to check (leave empty for yourself)")
    async def inventory_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.inventory.callback(self, ctx, member)

    # ── RICHEST ───────────────────────────────────────

    @commands.command(name="richest", aliases=["ecoleaderboard", "moneylb"])
    async def richest(self, ctx):
        data = load(ECO_FILE).get(str(ctx.guild.id), {})
        if not data:
            return await ctx.reply("No economy data yet. Use `~daily` or `~work` to get started!")
        ranked = sorted(
            ((uid, d.get("wallet", 0) + d.get("bank", 0)) for uid, d in data.items()),
            key=lambda x: x[1], reverse=True
        )[:10]
        medals = ["🥇","🥈","🥉"] + [f"`{i}.`" for i in range(4, 11)]
        lines = []
        for i, (uid, total) in enumerate(ranked):
            member = ctx.guild.get_member(int(uid))
            name = member.display_name if member else f"<@{uid}>"
            wallet = data[uid].get("wallet", 0)
            bank   = data[uid].get("bank", 0)
            lines.append(f"{medals[i]} **{name}** — 👛 `{wallet:,}` | 🏦 `{bank:,}` | Total: `{total:,}` {Config.CURRENCY_EMOJI}")
        e = discord.Embed(title=f"💰 {ctx.guild.name} — Richest Members", description="\n".join(lines), color=Config.COLOR_GOLD)
        e.set_footer(text=f"Your balance: {data.get(str(ctx.author.id), {}).get('wallet', 0):,} in wallet")
        if ctx.guild.icon:
            e.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.reply(embed=e)

    @slash.command(name="richest", description="Show the wealthiest members.")
    async def richest_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.richest.callback(self, ctx)


async def setup(bot):
    await bot.add_cog(Economy(bot))
