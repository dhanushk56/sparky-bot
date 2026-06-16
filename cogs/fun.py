"""
cogs/fun.py
Slash group: /fun + /counting
Prefix commands still work with ~
"""

import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
from config import Config
from utils.data import load, save

COUNTING_FILE = "counting.json"

EIGHT_BALL = [
    "It is certain.", "It is decidedly so.", "Without a doubt.",
    "Yes, definitely.", "You may rely on it.", "As I see it, yes.",
    "Most likely.", "Outlook good.", "Yes.", "Signs point to yes.",
    "Reply hazy, try again.", "Ask again later.", "Better not tell you now.",
    "Cannot predict now.", "Concentrate and ask again.",
    "Don't count on it.", "My reply is no.", "My sources say no.",
    "Outlook not so good.", "Very doubtful.",
]

FACTS = [
    "Honey never spoils. Archaeologists have found 3000-year-old honey in Egyptian tombs.",
    "A group of flamingos is called a flamboyance.",
    "Octopuses have three hearts and blue blood.",
    "Bananas are berries, but strawberries are not.",
    "The shortest war in history lasted 38-45 minutes (Anglo-Zanzibar War, 1896).",
    "A day on Venus is longer than a year on Venus.",
    "Cleopatra lived closer in time to the Moon landing than to the construction of the Great Pyramid.",
    "The human nose can detect over 1 trillion different scents.",
    "There are more possible iterations of a chess game than atoms in the known universe.",
    "Crows can recognize and remember human faces.",
    "The first oranges were green.",
    "Sharks are older than trees.",
    "A snail can sleep for 3 years.",
    "The dot over a lowercase i and j is called a tittle.",
    "Wombat poop is cube-shaped.",
]

ROASTS = [
    "You're the reason they put instructions on shampoo.",
    "I'd agree with you but then we'd both be wrong.",
    "You're not stupid. You just have bad luck thinking.",
    "Your secrets are always safe with me — I never listen when you talk.",
    "I'd explain it to you but I left my crayons at home.",
    "You're proof that evolution can go in reverse.",
    "If laughter is the best medicine, your face must be curing diseases.",
]

COMPLIMENTS = [
    "You light up every room you walk into!",
    "Your smile could end world hunger.",
    "You have the energy of a golden retriever and it's infectious!",
    "You're basically a walking ray of sunshine.",
    "Your brain is big and your heart is bigger.",
    "Whoever is lucky enough to know you is truly blessed.",
    "You could make even a Monday feel like a Friday!",
]

# ---------------------------------------------------------------------------
# Counting helpers
# ---------------------------------------------------------------------------

def _load_counting(guild_id):
    data = load(COUNTING_FILE)
    default = {
        "channel":          None,
        "count":            0,
        "high_score":       0,
        "last_user":        None,
        "ruined_by":        None,
        "saves":            {},      # {user_id: count}
        "checkpoint":       0,       # saved count to resume from on fail
        "scores":           {},      # {user_id: total_correct}
        "fails":            {},      # {user_id: total_fails}
        "allow_same_user":  False,
        "reset_on_fail":    True,
        "emojis": {
            "correct":     "✅",
            "wrong":       "❌",
            "milestone":   "🎉",
            "high_score":  "🏆",
            "save":        "🛡️",
        },
        "milestones":       [100, 250, 500, 1000, 2500, 5000, 10000],
        "save_limit":       3,       # max saves per user (0 = disabled, -1 = unlimited)
    }
    gd = data.get(str(guild_id), {})
    # Merge defaults for any missing keys
    for k, v in default.items():
        if k not in gd:
            gd[k] = v
        elif isinstance(v, dict):
            for dk, dv in v.items():
                if dk not in gd[k]:
                    gd[k][dk] = dv
    return gd


def _save_counting(guild_id, gd):
    data = load(COUNTING_FILE)
    data[str(guild_id)] = gd
    save(COUNTING_FILE, data)


def _is_milestone(count, milestones):
    return count in milestones or (count > 0 and count % 1000 == 0)


# ---------------------------------------------------------------------------
# Counting cog listener
# ---------------------------------------------------------------------------

class CountingListener(commands.Cog):
    """Internal listener for counting channel messages."""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        gd = _load_counting(message.guild.id)
        if not gd["channel"] or message.channel.id != gd["channel"]:
            return

        content = message.content.strip()

        # Ignore non-numeric messages silently
        if not content.lstrip("-").isdigit():
            try:
                await message.delete()
            except Exception:
                pass
            return

        number = int(content)
        emojis = gd["emojis"]
        expected = gd["count"] + 1
        is_admin = message.author.guild_permissions.administrator

        # ── Wrong number ───────────────────────────────────────────────────
        if number != expected:
            # Check if user has a save
            uid = str(message.author.id)
            save_limit = gd["save_limit"]
            user_saves = gd["saves"].get(uid, 0)
            has_save = (
                is_admin or
                (save_limit == -1) or
                (save_limit > 0 and user_saves > 0)
            )

            if has_save and not is_admin:
                gd["saves"][uid] = max(0, user_saves - 1)
                _save_counting(message.guild.id, gd)
                await message.add_reaction(emojis["save"])
                await message.channel.send(
                    "{} used a save! The count is still at **{}**. Saves remaining: **{}**".format(
                        message.author.mention,
                        gd["count"],
                        gd["saves"][uid],
                    )
                )
                try:
                    await message.delete()
                except Exception:
                    pass
                return
            elif is_admin:
                # Admin wrong number — just delete silently, unlimited saves
                try:
                    await message.delete()
                except Exception:
                    pass
                return

            # No save — ruin the count
            gd["fails"][uid] = gd["fails"].get(uid, 0) + 1
            gd["ruined_by"] = message.author.id
            old_count = gd["count"]
            checkpoint = gd.get("checkpoint", 0)
            if gd["reset_on_fail"]:
                gd["count"] = checkpoint
            gd["last_user"] = None
            _save_counting(message.guild.id, gd)
            await message.add_reaction(emojis["wrong"])
            if checkpoint > 0:
                await message.channel.send(
                    "{} ruined the count at **{}**! {}  Resuming from checkpoint **{}**.".format(
                        message.author.mention,
                        old_count,
                        emojis["wrong"],
                        checkpoint,
                    )
                )
            else:
                await message.channel.send(
                    "{} ruined the count at **{}**! {}  Starting back from **1**.".format(
                        message.author.mention,
                        old_count,
                        emojis["wrong"],
                    )
                )
            return

        # ── Same user twice ────────────────────────────────────────────────
        if not gd["allow_same_user"] and gd["last_user"] == message.author.id:
            try:
                await message.delete()
            except Exception:
                pass
            await message.channel.send(
                "{} you can't count twice in a row!".format(message.author.mention),
                delete_after=5,
            )
            return

        # ── Correct number ─────────────────────────────────────────────────
        uid = str(message.author.id)
        gd["count"]     = expected
        gd["last_user"] = message.author.id
        gd["scores"][uid] = gd["scores"].get(uid, 0) + 1

        # High score
        new_high = False
        if expected > gd["high_score"]:
            gd["high_score"] = expected
            new_high = True

        _save_counting(message.guild.id, gd)

        # React
        if new_high and _is_milestone(expected, gd["milestones"]):
            await message.add_reaction(emojis["high_score"])
            await message.add_reaction(emojis["milestone"])
            await message.channel.send(
                "{} New high score AND milestone at **{}**! {} {}".format(
                    message.author.mention, expected, emojis["high_score"], emojis["milestone"]
                )
            )
        elif new_high:
            await message.add_reaction(emojis["high_score"])
            await message.channel.send(
                "{} New high score: **{}**! {}".format(
                    message.author.mention, expected, emojis["high_score"]
                )
            )
        elif _is_milestone(expected, gd["milestones"]):
            await message.add_reaction(emojis["milestone"])
            await message.channel.send(
                "Milestone reached: **{}**! {}".format(expected, emojis["milestone"])
            )
        else:
            await message.add_reaction(emojis["correct"])


# ---------------------------------------------------------------------------
# Fun + Counting slash cog
# ---------------------------------------------------------------------------

class Fun(commands.Cog):
    """Fun and entertainment commands."""

    slash    = app_commands.Group(name="fun",      description="Fun and entertainment commands")
    counting = app_commands.Group(name="counting", description="Counting channel commands")

    def __init__(self, bot):
        self.bot = bot

    # =========================================================================
    # FUN COMMANDS
    # =========================================================================

    @commands.command(name="8ball")
    async def eightball(self, ctx, *, question: str):
        answer   = random.choice(EIGHT_BALL)
        positive = EIGHT_BALL[:10]
        neutral  = EIGHT_BALL[10:15]
        color = Config.COLOR_OK if answer in positive else (Config.COLOR_WARN if answer in neutral else Config.COLOR_ERR)
        e = discord.Embed(color=color)
        e.add_field(name="Question", value=question, inline=False)
        e.add_field(name="Answer",   value=answer,   inline=False)
        await ctx.reply(embed=e)

    @slash.command(name="8ball", description="Ask the magic 8-ball a question.")
    @app_commands.describe(question="Your yes/no question")
    async def eightball_slash(self, interaction, question: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.eightball.callback(self, ctx, question=question)

    @commands.command(name="coinflip")
    async def coinflip(self, ctx):
        await ctx.reply(random.choice(["Heads!", "Tails!"]))

    @slash.command(name="coinflip", description="Flip a coin.")
    async def coinflip_slash(self, interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.coinflip.callback(self, ctx)

    @commands.command(name="dice")
    async def dice(self, ctx, notation: str = "1d6"):
        try:
            notation = notation.lower().replace(" ", "")
            if "d" not in notation:
                raise ValueError
            parts = notation.split("d")
            n = int(parts[0]) if parts[0] else 1
            s = int(parts[1])
            if n < 1 or n > 100 or s < 2 or s > 1000:
                raise ValueError
            rolls = [random.randint(1, s) for _ in range(n)]
            total = sum(rolls)
            roll_str = " + ".join("`{}`".format(r) for r in rolls)
            e = discord.Embed(title="Rolled {}".format(notation), color=Config.COLOR_INFO)
            e.add_field(name="Rolls", value=roll_str, inline=False)
            if n > 1:
                e.add_field(name="Total", value="**{}**".format(total))
            await ctx.reply(embed=e)
        except (ValueError, IndexError):
            await ctx.reply("Invalid notation. Use NdS format, e.g. 2d6, d20.")

    @slash.command(name="dice", description="Roll dice. Format: NdS (e.g. 2d6)")
    @app_commands.describe(notation="Dice notation, e.g. 2d6 or d20")
    async def dice_slash(self, interaction, notation: str = "1d6"):
        ctx = await commands.Context.from_interaction(interaction)
        await self.dice.callback(self, ctx, notation)

    @commands.command(name="rps")
    async def rps(self, ctx, choice: str):
        choices = {"rock": "Rock", "paper": "Paper", "scissors": "Scissors"}
        c = choice.lower().strip()
        if c not in choices:
            return await ctx.reply("Choose rock, paper, or scissors.")
        bot_c = random.choice(list(choices.keys()))
        wins  = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
        if c == bot_c:
            result, color = "Tie!", Config.COLOR_WARN
        elif wins[c] == bot_c:
            result, color = "You win!", Config.COLOR_OK
        else:
            result, color = "You lose!", Config.COLOR_ERR
        e = discord.Embed(title="Rock Paper Scissors", color=color)
        e.add_field(name="You", value=choices[c])
        e.add_field(name="Bot", value=choices[bot_c])
        e.add_field(name="Result", value=result, inline=False)
        await ctx.reply(embed=e)

    @slash.command(name="rps", description="Play Rock Paper Scissors against the bot.")
    @app_commands.describe(choice="rock, paper, or scissors")
    async def rps_slash(self, interaction, choice: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.rps.callback(self, ctx, choice)

    @commands.command(name="choose")
    async def choose(self, ctx, *, options: str):
        choices = [o.strip() for o in options.split(",") if o.strip()]
        if len(choices) < 2:
            return await ctx.reply("Provide at least 2 options separated by commas.")
        await ctx.reply("I choose **{}**!".format(random.choice(choices)))

    @slash.command(name="choose", description="Pick one option from a comma-separated list.")
    @app_commands.describe(options="Comma-separated options")
    async def choose_slash(self, interaction, options: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.choose.callback(self, ctx, options=options)

    @commands.command(name="reverse")
    async def reverse(self, ctx, *, text: str):
        await ctx.reply(text[::-1])

    @slash.command(name="reverse", description="Reverse a string of text.")
    @app_commands.describe(text="Text to reverse")
    async def reverse_slash(self, interaction, text: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.reverse.callback(self, ctx, text=text)

    @commands.command(name="mock")
    async def mock(self, ctx, *, text: str):
        await ctx.reply("".join(c.upper() if i % 2 else c.lower() for i, c in enumerate(text)))

    @slash.command(name="mock", description="SpOnGeBoB mOcK tExT.")
    @app_commands.describe(text="Text to mock")
    async def mock_slash(self, interaction, text: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.mock.callback(self, ctx, text=text)

    @commands.command(name="emojify")
    async def emojify(self, ctx, *, text: str):
        result = ""
        for c in text.lower():
            if "a" <= c <= "z":
                result += ":regional_indicator_{}: ".format(c)
            elif c == " ":
                result += "   "
            elif c.isdigit():
                nums = ["0️⃣","1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣"]
                result += nums[int(c)] + " "
        if not result.strip():
            return await ctx.reply("No convertible characters found.")
        await ctx.reply(result[:1900])

    @slash.command(name="emojify", description="Convert text to regional indicator emojis.")
    @app_commands.describe(text="Text to emojify")
    async def emojify_slash(self, interaction, text: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.emojify.callback(self, ctx, text=text)

    @commands.command(name="rate")
    async def rate(self, ctx, *, thing: str):
        rating = random.randint(0, 10)
        bar    = "█" * rating + "░" * (10 - rating)
        emoji  = "💯" if rating == 10 else "😢" if rating == 0 else "⭐"
        await ctx.reply("{} **{}** — `{}` **{}/10**".format(emoji, thing, bar, rating))

    @slash.command(name="rate", description="Rate something out of 10.")
    @app_commands.describe(thing="What to rate")
    async def rate_slash(self, interaction, thing: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.rate.callback(self, ctx, thing=thing)

    @commands.command(name="fact")
    async def fact(self, ctx):
        e = discord.Embed(description=random.choice(FACTS), color=Config.COLOR_INFO)
        await ctx.reply(embed=e)

    @slash.command(name="fact", description="Get a random interesting fact.")
    async def fact_slash(self, interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.fact.callback(self, ctx)

    @commands.command(name="roast")
    async def roast(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        await ctx.reply("{} — {}".format(target.mention, random.choice(ROASTS)))

    @slash.command(name="roast", description="Roast a member.")
    @app_commands.describe(member="Member to roast (leave empty for yourself)")
    async def roast_slash(self, interaction, member: discord.Member = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.roast.callback(self, ctx, member)

    @commands.command(name="compliment")
    async def compliment(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        await ctx.reply("{} — {}".format(target.mention, random.choice(COMPLIMENTS)))

    @slash.command(name="compliment", description="Send a compliment to a member.")
    @app_commands.describe(member="Member to compliment")
    async def compliment_slash(self, interaction, member: discord.Member = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.compliment.callback(self, ctx, member)

    @commands.command(name="ship")
    async def ship(self, ctx, person1: discord.Member, person2: discord.Member = None):
        p2    = person2 or ctx.author
        score = random.randint(0, 100)
        bar   = "❤️" * int(score / 10) + "🖤" * (10 - int(score / 10))
        if score >= 80:   verdict = "Perfect match!"
        elif score >= 60: verdict = "Pretty good!"
        elif score >= 40: verdict = "It could work..."
        elif score >= 20: verdict = "Ehh..."
        else:             verdict = "Absolutely not."
        e = discord.Embed(
            title="{} x {}".format(person1.display_name, p2.display_name),
            description="{}\n\n**{}%** — {}".format(bar, score, verdict),
            color=0xFF69B4,
        )
        await ctx.reply(embed=e)

    @slash.command(name="ship", description="Calculate the love compatibility of two members.")
    @app_commands.describe(person1="First member", person2="Second member (leave empty for yourself)")
    async def ship_slash(self, interaction, person1: discord.Member, person2: discord.Member = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.ship.callback(self, ctx, person1, person2)

    @commands.command(name="trivia")
    async def trivia(self, ctx):
        questions = [
            {"q": "What is the chemical symbol for gold?",       "a": "Au",          "opts": ["Ag","Au","Fe","Gd"]},
            {"q": "How many bones does an adult human have?",    "a": "206",         "opts": ["196","206","215","226"]},
            {"q": "Which planet is closest to the Sun?",         "a": "Mercury",     "opts": ["Venus","Earth","Mercury","Mars"]},
            {"q": "What language has the most native speakers?", "a": "Mandarin",    "opts": ["English","Spanish","Mandarin","Hindi"]},
            {"q": "Who wrote Hamlet?",                           "a": "Shakespeare", "opts": ["Dickens","Shakespeare","Chaucer","Marlowe"]},
        ]
        q = random.choice(questions)
        random.shuffle(q["opts"])
        labels = ["🇦","🇧","🇨","🇩"]
        desc   = "\n".join("{} {}".format(labels[i], opt) for i, opt in enumerate(q["opts"]))
        e = discord.Embed(title=q["q"], description=desc, color=Config.COLOR_INFO)
        e.set_footer(text="You have 15 seconds!")
        msg = await ctx.reply(embed=e)
        for l in labels:
            await msg.add_reaction(l)
        emoji_map = {em: q["opts"][i] for i, em in enumerate(labels)}

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in labels and reaction.message.id == msg.id

        try:
            reaction, _ = await self.bot.wait_for("reaction_add", timeout=15, check=check)
            chosen = emoji_map[str(reaction.emoji)]
            if chosen == q["a"]:
                await ctx.send("{} correct! The answer was **{}**.".format(ctx.author.mention, q["a"]))
            else:
                await ctx.send("{} wrong! The correct answer was **{}**.".format(ctx.author.mention, q["a"]))
        except asyncio.TimeoutError:
            await ctx.send("Time's up! The answer was **{}**.".format(q["a"]))

    @slash.command(name="trivia", description="Answer a trivia question.")
    async def trivia_slash(self, interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.trivia.callback(self, ctx)

    # =========================================================================
    # COUNTING COMMANDS  (all admin-only)
    # =========================================================================

    # ── /counting setchannel ──────────────────────────────────────────────────

    @counting.command(name="setchannel", description="Set the counting channel.")
    @app_commands.describe(channel="Channel to use for counting")
    @app_commands.default_permissions(administrator=True)
    async def counting_setchannel(self, interaction, channel: discord.TextChannel):
        gd = _load_counting(interaction.guild_id)
        gd["channel"] = channel.id
        _save_counting(interaction.guild_id, gd)
        e = discord.Embed(
            title="Counting Channel Set",
            description="Counting is now active in {}.\nCurrent count: **{}** | High score: **{}**".format(
                channel.mention, gd["count"], gd["high_score"]
            ),
            color=Config.COLOR_OK,
        )
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── /counting reset ───────────────────────────────────────────────────────

    @counting.command(name="reset", description="Reset the count and all stats back to zero.")
    @app_commands.describe(keep_high_score="Keep the high score record? (default: yes)")
    @app_commands.default_permissions(administrator=True)
    async def counting_reset(self, interaction, keep_high_score: bool = True):
        gd = _load_counting(interaction.guild_id)
        old_hs   = gd["high_score"]
        old_count = gd["count"]
        gd["count"]     = 0
        gd["last_user"] = None
        gd["ruined_by"] = None
        gd["scores"]    = {}
        gd["fails"]     = {}
        gd["saves"]     = {}
        if not keep_high_score:
            gd["high_score"] = 0
        _save_counting(interaction.guild_id, gd)
        e = discord.Embed(
            title="Counting Reset",
            description=(
                "Count reset from **{}** to **0**.\n"
                "All scores, fails, and saves cleared.\n"
                "High score: **{}**".format(
                    old_count,
                    old_hs if keep_high_score else "also reset to 0",
                )
            ),
            color=Config.COLOR_OK,
        )
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── /counting resetcount ──────────────────────────────────────────────────

    @counting.command(name="resetcount", description="Reset only the current count without wiping leaderboard stats.")
    @app_commands.default_permissions(administrator=True)
    async def counting_resetcount(self, interaction):
        gd = _load_counting(interaction.guild_id)
        old = gd["count"]
        gd["count"]     = 0
        gd["last_user"] = None
        _save_counting(interaction.guild_id, gd)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Count Reset",
                description="Count reset from **{}** to **0**. Leaderboard stats preserved.".format(old),
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

    # ── /counting setcount ────────────────────────────────────────────────────

    @counting.command(name="setcount", description="Manually set the current count to any number.")
    @app_commands.describe(number="Number to set the count to")
    @app_commands.default_permissions(administrator=True)
    async def counting_setcount(self, interaction, number: int):
        if number < 0:
            await interaction.response.send_message("Count cannot be negative.", ephemeral=True)
            return
        gd = _load_counting(interaction.guild_id)
        gd["count"]     = number
        gd["last_user"] = None
        if number > gd["high_score"]:
            gd["high_score"] = number
        _save_counting(interaction.guild_id, gd)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Count Set",
                description="Count manually set to **{}**. Next number: **{}**.".format(number, number + 1),
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

    # ── /counting stats ───────────────────────────────────────────────────────

    @counting.command(name="stats", description="View counting stats for this server or a specific member.")
    @app_commands.describe(member="Member to view stats for (leave blank for server stats)")
    @app_commands.default_permissions(administrator=True)
    async def counting_stats(self, interaction, member: discord.Member = None):
        gd = _load_counting(interaction.guild_id)
        ch = interaction.guild.get_channel(gd["channel"]) if gd["channel"] else None
        emojis = gd["emojis"]

        if member:
            uid    = str(member.id)
            score  = gd["scores"].get(uid, 0)
            fails  = gd["fails"].get(uid, 0)
            saves  = gd["saves"].get(uid, 0)
            total  = score + fails
            acc    = "{}%".format(round(score / total * 100)) if total > 0 else "N/A"
            save_limit = gd["save_limit"]
            save_str = (
                "Unlimited (admin)" if member.guild_permissions.administrator
                else "{} / {}".format(saves, "Unlimited" if save_limit == -1 else save_limit)
            )
            e = discord.Embed(
                title="Counting Stats — {}".format(member.display_name),
                color=Config.COLOR_INFO,
            )
            e.set_thumbnail(url=member.display_avatar.url)
            e.add_field(name="{} Correct".format(emojis["correct"]),   value=str(score), inline=True)
            e.add_field(name="{} Wrong".format(emojis["wrong"]),       value=str(fails), inline=True)
            e.add_field(name="Accuracy",                               value=acc,        inline=True)
            e.add_field(name="{} Saves Left".format(emojis["save"]),   value=save_str,   inline=True)
        else:
            ruiner = interaction.guild.get_member(gd["ruined_by"]) if gd["ruined_by"] else None
            e = discord.Embed(title="Counting Stats", color=Config.COLOR_INFO)
            e.add_field(name="Current Count",  value="**{}**".format(gd["count"]),      inline=True)
            e.add_field(name="{} High Score".format(emojis["high_score"]),
                        value="**{}**".format(gd["high_score"]),                         inline=True)
            e.add_field(name="Channel",        value=ch.mention if ch else "Not set",   inline=True)
            e.add_field(name="Last Ruined By", value=ruiner.mention if ruiner else "No one yet", inline=True)
            e.add_field(name="Reset on Fail",  value="Yes" if gd["reset_on_fail"] else "No", inline=True)
            e.add_field(name="Same User Twice",value="Allowed" if gd["allow_same_user"] else "Not allowed", inline=True)
            e.add_field(name="Save Limit",     value="Unlimited" if gd["save_limit"] == -1 else str(gd["save_limit"]), inline=True)
            e.add_field(name="Total Counters", value=str(len(gd["scores"])), inline=True)

        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── /counting leaderboard ─────────────────────────────────────────────────

    @counting.command(name="leaderboard", description="Show the counting leaderboard.")
    @app_commands.describe(type="Which leaderboard to show")
    @app_commands.choices(type=[
        app_commands.Choice(name="Most Correct",  value="scores"),
        app_commands.Choice(name="Most Fails",    value="fails"),
        app_commands.Choice(name="Most Saves",    value="saves"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def counting_leaderboard(self, interaction, type: str = "scores"):
        gd     = _load_counting(interaction.guild_id)
        data   = gd.get(type, {})
        emojis = gd["emojis"]
        sorted_data = sorted(data.items(), key=lambda x: x[1], reverse=True)[:10]

        titles = {
            "scores": "{} Most Correct".format(emojis["correct"]),
            "fails":  "{} Most Fails".format(emojis["wrong"]),
            "saves":  "{} Most Saves Used".format(emojis["save"]),
        }
        medals = ["🥇","🥈","🥉"] + ["**{}.**".format(i) for i in range(4, 11)]
        lines  = []
        for i, (uid, val) in enumerate(sorted_data):
            member = interaction.guild.get_member(int(uid))
            name   = member.display_name if member else "Unknown"
            lines.append("{} {} — **{}**".format(medals[i], name, val))

        e = discord.Embed(
            title="Counting Leaderboard — {}".format(titles.get(type, type)),
            description="\n".join(lines) if lines else "No data yet.",
            color=Config.COLOR_INFO,
        )
        e.set_footer(text="Current count: {} | High score: {}".format(gd["count"], gd["high_score"]))
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── /counting givesave ────────────────────────────────────────────────────

    @counting.command(name="givesave", description="Give a save to a member.")
    @app_commands.describe(member="Member to give a save to", amount="Number of saves to give (default 1)")
    @app_commands.default_permissions(administrator=True)
    async def counting_givesave(self, interaction, member: discord.Member, amount: int = 1):
        if amount < 1:
            await interaction.response.send_message("Amount must be at least 1.", ephemeral=True)
            return
        gd  = _load_counting(interaction.guild_id)
        uid = str(member.id)
        gd["saves"][uid] = gd["saves"].get(uid, 0) + amount
        _save_counting(interaction.guild_id, gd)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Save Given",
                description="Gave **{}** save(s) to {}.\nThey now have **{}** save(s).".format(
                    amount, member.mention, gd["saves"][uid]
                ),
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

    # ── /counting takesave ────────────────────────────────────────────────────

    @counting.command(name="takesave", description="Remove saves from a member.")
    @app_commands.describe(member="Member to take saves from", amount="Number of saves to remove (default 1)")
    @app_commands.default_permissions(administrator=True)
    async def counting_takesave(self, interaction, member: discord.Member, amount: int = 1):
        gd  = _load_counting(interaction.guild_id)
        uid = str(member.id)
        current = gd["saves"].get(uid, 0)
        gd["saves"][uid] = max(0, current - amount)
        _save_counting(interaction.guild_id, gd)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Saves Removed",
                description="Removed **{}** save(s) from {}.\nThey now have **{}** save(s).".format(
                    amount, member.mention, gd["saves"][uid]
                ),
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

    # ── /counting savelimit ───────────────────────────────────────────────────

    @counting.command(name="savelimit", description="Set the max saves a member can have (0=disabled, -1=unlimited).")
    @app_commands.describe(limit="Max saves per member. 0 = no saves, -1 = unlimited (admins always have unlimited)")
    @app_commands.default_permissions(administrator=True)
    async def counting_savelimit(self, interaction, limit: int):
        if limit < -1:
            await interaction.response.send_message("Use -1 for unlimited, 0 to disable, or a positive number.", ephemeral=True)
            return
        gd = _load_counting(interaction.guild_id)
        gd["save_limit"] = limit
        _save_counting(interaction.guild_id, gd)
        desc = (
            "Saves **disabled** for all non-admins."     if limit == 0
            else "Saves set to **unlimited** for all."   if limit == -1
            else "Save limit set to **{}** per member.".format(limit)
        )
        desc += "\nAdministrators always have unlimited saves."
        await interaction.response.send_message(
            embed=discord.Embed(title="Save Limit Updated", description=desc, color=Config.COLOR_OK),
            ephemeral=True,
        )

    # ── /counting setemoji ────────────────────────────────────────────────────

    @counting.command(name="setemoji", description="Customize the emojis used by the counting system.")
    @app_commands.describe(
        type="Which emoji to change",
        emoji="The new emoji to use",
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="Correct Number",  value="correct"),
        app_commands.Choice(name="Wrong Number",    value="wrong"),
        app_commands.Choice(name="Milestone",       value="milestone"),
        app_commands.Choice(name="High Score",      value="high_score"),
        app_commands.Choice(name="Save Used",       value="save"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def counting_setemoji(self, interaction, type: str, emoji: str):
        gd = _load_counting(interaction.guild_id)
        gd["emojis"][type] = emoji.strip()
        _save_counting(interaction.guild_id, gd)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Emoji Updated",
                description="**{}** emoji set to: {}".format(type.replace("_", " ").title(), emoji.strip()),
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

    # ── /counting setmilestones ───────────────────────────────────────────────

    @counting.command(name="setmilestones", description="Set custom milestone numbers (comma separated).")
    @app_commands.describe(milestones="Comma separated numbers, e.g. 100,500,1000,5000")
    @app_commands.default_permissions(administrator=True)
    async def counting_setmilestones(self, interaction, milestones: str):
        try:
            parsed = [int(x.strip()) for x in milestones.split(",") if x.strip().isdigit()]
            if not parsed:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Invalid input. Use comma-separated numbers e.g. 100,500,1000.", ephemeral=True)
            return
        gd = _load_counting(interaction.guild_id)
        gd["milestones"] = sorted(parsed)
        _save_counting(interaction.guild_id, gd)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Milestones Updated",
                description="Milestones set to: **{}**\nNote: Multiples of 1000 always trigger as milestones.".format(
                    ", ".join(str(m) for m in gd["milestones"])
                ),
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

    # ── /counting toggleresetonfail ───────────────────────────────────────────

    @counting.command(name="toggleresetonfail", description="Toggle whether the count resets to 0 when someone fails.")
    @app_commands.default_permissions(administrator=True)
    async def counting_togglereset(self, interaction):
        gd = _load_counting(interaction.guild_id)
        gd["reset_on_fail"] = not gd["reset_on_fail"]
        _save_counting(interaction.guild_id, gd)
        state = "ON — count resets to 0 on fail" if gd["reset_on_fail"] else "OFF — count stays on fail"
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Reset on Fail: {}".format("Enabled" if gd["reset_on_fail"] else "Disabled"),
                description=state,
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

    # ── /counting togglesameuser ──────────────────────────────────────────────

    @counting.command(name="togglesameuser", description="Toggle whether the same user can count twice in a row.")
    @app_commands.default_permissions(administrator=True)
    async def counting_togglesameuser(self, interaction):
        gd = _load_counting(interaction.guild_id)
        gd["allow_same_user"] = not gd["allow_same_user"]
        _save_counting(interaction.guild_id, gd)
        state = "allowed" if gd["allow_same_user"] else "not allowed"
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Same User Rule Updated",
                description="Counting twice in a row is now **{}**.".format(state),
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

    # ── /counting config ──────────────────────────────────────────────────────

    @counting.command(name="config", description="View the current counting configuration.")
    @app_commands.default_permissions(administrator=True)
    async def counting_config(self, interaction):
        gd     = _load_counting(interaction.guild_id)
        emojis = gd["emojis"]
        ch     = interaction.guild.get_channel(gd["channel"]) if gd["channel"] else None
        e = discord.Embed(title="Counting Configuration", color=Config.COLOR_INFO)
        e.add_field(name="Channel",         value=ch.mention if ch else "Not set",                      inline=True)
        e.add_field(name="Current Count",   value=str(gd["count"]),                                     inline=True)
        e.add_field(name="High Score",      value=str(gd["high_score"]),                                inline=True)
        e.add_field(name="Reset on Fail",   value="Yes" if gd["reset_on_fail"] else "No",              inline=True)
        e.add_field(name="Same User Twice", value="Allowed" if gd["allow_same_user"] else "Blocked",   inline=True)
        e.add_field(name="Save Limit",      value="Unlimited" if gd["save_limit"] == -1 else ("Disabled" if gd["save_limit"] == 0 else str(gd["save_limit"])), inline=True)
        checkpoint = gd.get("checkpoint", 0)
        e.add_field(name="Checkpoint",     value="**{}**".format(checkpoint) if checkpoint > 0 else "Not set", inline=True)
        e.add_field(name="Milestones",     value=", ".join(str(m) for m in gd["milestones"]),          inline=False)
        emoji_lines = "\n".join("{}: {}".format(k.replace("_"," ").title(), v) for k, v in emojis.items())
        e.add_field(name="Emojis",          value=emoji_lines,                                          inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── /counting savecheckpoint ─────────────────────────────────────────────

    @counting.command(name="savecheckpoint", description="Save the current count as a checkpoint to resume from if someone fails.")
    @app_commands.default_permissions(administrator=True)
    async def counting_savecheckpoint(self, interaction):
        gd = _load_counting(interaction.guild_id)
        current = gd["count"]
        if current == 0:
            await interaction.response.send_message(
                "The count is at 0, nothing to save.", ephemeral=True
            )
            return
        gd["checkpoint"] = current
        _save_counting(interaction.guild_id, gd)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Checkpoint Saved",
                description="Checkpoint saved at **{}**. If someone ruins the count, it will resume from here instead of restarting from 1.".format(current),
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

    # ── /counting clearcheckpoint ─────────────────────────────────────────────

    @counting.command(name="clearcheckpoint", description="Clear the saved checkpoint so the count resets to 1 on fail.")
    @app_commands.default_permissions(administrator=True)
    async def counting_clearcheckpoint(self, interaction):
        gd = _load_counting(interaction.guild_id)
        old = gd.get("checkpoint", 0)
        if old == 0:
            await interaction.response.send_message("No checkpoint is currently saved.", ephemeral=True)
            return
        gd["checkpoint"] = 0
        _save_counting(interaction.guild_id, gd)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Checkpoint Cleared",
                description="Checkpoint **{}** has been cleared. The count will now reset to 1 on fail.".format(old),
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

    # ── /counting disqualify ──────────────────────────────────────────────────

    @counting.command(name="disqualify", description="Remove a member from the counting leaderboard.")
    @app_commands.describe(member="Member to disqualify from leaderboard")
    @app_commands.default_permissions(administrator=True)
    async def counting_disqualify(self, interaction, member: discord.Member):
        gd  = _load_counting(interaction.guild_id)
        uid = str(member.id)
        removed = []
        for key in ("scores", "fails", "saves"):
            if uid in gd[key]:
                del gd[key][uid]
                removed.append(key)
        _save_counting(interaction.guild_id, gd)
        if removed:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Member Disqualified",
                    description="{} has been removed from the counting leaderboard.".format(member.mention),
                    color=Config.COLOR_OK,
                ),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "{} has no counting data to remove.".format(member.mention), ephemeral=True
            )


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def setup(bot):
    await bot.add_cog(Fun(bot))
    await bot.add_cog(CountingListener(bot))