"""
cogs/application.py
Slash group: /application
Advanced application system — paginated single-embed session (no DM spam).
Navigate questions with << < > >> buttons, submit at any time.
Session timer shown in embed footer. Constraint errors auto-dismiss after 5s.

Review buttons: Accept, Deny, Accept w/ Reason, Deny w/ Reason,
                Open Ticket w/ User, Under Consideration.
"""

import discord
import asyncio
import re
import time
from discord.ext import commands
from discord import app_commands
from config import Config
from utils.data import load, save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_FILE = "applications.json"

QUESTION_TYPES = [
    "short_answer", "long_answer", "multiple_choice", "dropdown",
    "numeric", "range", "yes_no", "paragraph", "url",
]

TYPE_LABELS = {
    "short_answer":    "Short Answer",
    "long_answer":     "Long Answer",
    "multiple_choice": "Multiple Choice",
    "dropdown":        "Dropdown",
    "numeric":         "Numeric Only",
    "range":           "Range (min–max)",
    "yes_no":          "Yes / No",
    "paragraph":       "Paragraph",
    "url":             "URL",
}

REAPPLY_COOLDOWN = 300  # seconds

_submission_times: dict[tuple, float] = {}
_active_sessions:  set[tuple]         = set()

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _load_guild(guild_id: int) -> dict:
    data = load(APP_FILE)
    return data.get(str(guild_id), {})

def _save_guild(guild_id: int, guild_data: dict):
    data = load(APP_FILE)
    data[str(guild_id)] = guild_data
    save(APP_FILE, data)

def _get_app(guild_id: int, app_name: str) -> dict | None:
    return _load_guild(guild_id).get(app_name.lower())

def _save_app(guild_id: int, app_name: str, app_data: dict):
    gd = _load_guild(guild_id)
    gd[app_name.lower()] = app_data
    _save_guild(guild_id, gd)

def _delete_app(guild_id: int, app_name: str) -> bool:
    gd = _load_guild(guild_id)
    if app_name.lower() in gd:
        del gd[app_name.lower()]
        _save_guild(guild_id, gd)
        return True
    return False

def _list_apps(guild_id: int) -> list[str]:
    return list(_load_guild(guild_id).keys())

def _check_cooldown(guild_id: int, user_id: int, app_name: str) -> float | None:
    key  = (guild_id, user_id, app_name)
    last = _submission_times.get(key)
    if last is None:
        return None
    remaining = REAPPLY_COOLDOWN - (time.time() - last)
    return remaining if remaining > 0 else None

# ---------------------------------------------------------------------------
# Embed helpers
# ---------------------------------------------------------------------------

def _ok(title: str, desc: str = "") -> discord.Embed:
    return discord.Embed(title=title, description=desc or None, color=Config.COLOR_OK)

def _err(desc: str) -> discord.Embed:
    return discord.Embed(description="ERROR: " + desc, color=Config.COLOR_ERR)

def _info(title: str, desc: str = "") -> discord.Embed:
    return discord.Embed(title=title, description=desc or None, color=Config.COLOR_INFO)

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _word_count(text: str) -> int:
    return len(text.split())

def _validate_answer(answer: str, question: dict) -> str | None:
    qtype  = question["type"]
    answer = answer.strip()

    if qtype == "short_answer":
        min_c = question.get("min_chars", 1)
        max_c = question.get("max_chars", 200)
        min_w = question.get("min_words")
        max_w = question.get("max_words")
        if len(answer) < min_c:   return "Answer too short (min {} characters).".format(min_c)
        if len(answer) > max_c:   return "Answer too long (max {} characters).".format(max_c)
        if min_w and _word_count(answer) < min_w: return "Needs at least {} words.".format(min_w)
        if max_w and _word_count(answer) > max_w: return "Too long (max {} words).".format(max_w)

    elif qtype in ("long_answer", "paragraph"):
        min_c = question.get("min_chars", 1)
        max_c = question.get("max_chars", 4000)
        min_w = question.get("min_words")
        max_w = question.get("max_words")
        if len(answer) < min_c:   return "Answer too short (min {} characters).".format(min_c)
        if len(answer) > max_c:   return "Answer too long (max {} characters).".format(max_c)
        if min_w and _word_count(answer) < min_w: return "Needs at least {} words.".format(min_w)
        if max_w and _word_count(answer) > max_w: return "Too long (max {} words).".format(max_w)

    elif qtype == "numeric":
        if not answer.lstrip("-").isdigit():
            return "Answer must be a whole number."

    elif qtype == "range":
        try:
            val = float(answer)
        except ValueError:
            return "Answer must be a number."
        rmin = question.get("range_min")
        rmax = question.get("range_max")
        if rmin is not None and val < rmin: return "Value must be at least {}.".format(rmin)
        if rmax is not None and val > rmax: return "Value must be at most {}.".format(rmax)

    elif qtype == "yes_no":
        if answer.lower() not in ("yes", "no", "y", "n"):
            return "Answer must be Yes or No."

    elif qtype == "url":
        if not re.match(r"^https?://\S+\.\S+", answer):
            return "Must be a valid URL starting with http:// or https://"

    return None

# ---------------------------------------------------------------------------
# Add / Edit Question Modals
# ---------------------------------------------------------------------------

class AddQuestionModal(discord.ui.Modal, title="Add Question"):
    q_text        = discord.ui.TextInput(label="Question text", placeholder="What is your age?", max_length=300)
    q_type        = discord.ui.TextInput(label="Type (short/long/mcq/dropdown/numeric…)", placeholder="short_answer | long_answer | mcq | dropdown | numeric | range | yes_no | paragraph | url", max_length=30)
    q_options     = discord.ui.TextInput(label="Options (MCQ/Dropdown, comma separated)", placeholder="Option A, Option B, Option C", required=False, max_length=500)
    q_constraints = discord.ui.TextInput(label="Constraints (optional, key:value pairs)", placeholder="min_chars:10, max_chars:200, range_min:1, range_max:100", required=False, max_length=300)
    q_required    = discord.ui.TextInput(label="Required? (yes/no)", placeholder="yes", max_length=3, default="yes")

    def __init__(self, app_name: str, guild_id: int):
        super().__init__()
        self.app_name = app_name
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        raw_type = self.q_type.value.strip().lower().replace(" ", "_").replace("-", "_")
        aliases  = {
            "short": "short_answer", "long": "long_answer",
            "mcq": "multiple_choice", "mc": "multiple_choice", "multiple": "multiple_choice",
            "drop": "dropdown", "num": "numeric", "number": "numeric",
            "yesno": "yes_no", "bool": "yes_no", "para": "paragraph", "link": "url",
        }
        qtype = aliases.get(raw_type, raw_type)
        if qtype not in QUESTION_TYPES:
            return await interaction.response.send_message(
                embed=_err("Unknown type `{}`. Valid: {}".format(raw_type, ", ".join(QUESTION_TYPES))),
                ephemeral=True,
            )

        options = []
        if self.q_options.value.strip():
            options = [o.strip() for o in self.q_options.value.split(",") if o.strip()]

        if qtype == "multiple_choice" and not (2 <= len(options) <= 5):
            return await interaction.response.send_message(embed=_err("Multiple choice requires 2–5 options."), ephemeral=True)
        if qtype == "dropdown" and not (2 <= len(options) <= 25):
            return await interaction.response.send_message(embed=_err("Dropdown requires 2–25 options."), ephemeral=True)

        constraints = {}
        for part in self.q_constraints.value.split(","):
            part = part.strip()
            if ":" in part:
                k, v = part.split(":", 1)
                try:
                    constraints[k.strip()] = int(v.strip()) if "." not in v else float(v.strip())
                except ValueError:
                    constraints[k.strip()] = v.strip()

        question = {
            "text": self.q_text.value.strip(), "type": qtype, "options": options,
            "required": self.q_required.value.strip().lower() not in ("no", "n", "false"),
            **constraints,
        }
        app = _get_app(self.guild_id, self.app_name)
        if app is None:
            return await interaction.response.send_message(embed=_err("Application not found."), ephemeral=True)
        app.setdefault("questions", []).append(question)
        _save_app(self.guild_id, self.app_name, app)
        q_num = len(app["questions"])
        await interaction.response.send_message(
            embed=_ok("Question #{} Added".format(q_num), "**{}**\nType: `{}`{}".format(
                question["text"], TYPE_LABELS.get(qtype, qtype),
                "\nOptions: " + ", ".join(options) if options else "",
            )),
            ephemeral=True,
        )


class EditQuestionModal(discord.ui.Modal, title="Edit Question"):
    q_text        = discord.ui.TextInput(label="New question text (blank = keep)", required=False, max_length=300)
    q_options     = discord.ui.TextInput(label="New options, comma separated (blank=keep)", required=False, max_length=500)
    q_constraints = discord.ui.TextInput(label="New constraints (blank = keep)", required=False, max_length=300)
    q_required    = discord.ui.TextInput(label="Required? yes/no (blank = keep)", required=False, max_length=3)

    def __init__(self, app_name: str, guild_id: int, q_index: int):
        super().__init__()
        self.app_name = app_name
        self.guild_id = guild_id
        self.q_index  = q_index

    async def on_submit(self, interaction: discord.Interaction):
        app = _get_app(self.guild_id, self.app_name)
        if not app or self.q_index >= len(app.get("questions", [])):
            return await interaction.response.send_message(embed=_err("Question not found."), ephemeral=True)
        q = app["questions"][self.q_index]
        if self.q_text.value.strip():
            q["text"] = self.q_text.value.strip()
        if self.q_options.value.strip():
            q["options"] = [o.strip() for o in self.q_options.value.split(",") if o.strip()]
        for part in self.q_constraints.value.split(","):
            if ":" in part:
                k, v = part.split(":", 1)
                try:
                    q[k.strip()] = int(v.strip()) if "." not in v else float(v.strip())
                except ValueError:
                    q[k.strip()] = v.strip()
        if self.q_required.value.strip():
            q["required"] = self.q_required.value.strip().lower() not in ("no", "n", "false")
        app["questions"][self.q_index] = q
        _save_app(self.guild_id, self.app_name, app)
        await interaction.response.send_message(embed=_ok("Question Updated", q["text"]), ephemeral=True)

# ---------------------------------------------------------------------------
# Text Answer Modal (modal popup for text-based questions)
# ---------------------------------------------------------------------------

class TextAnswerModal(discord.ui.Modal):
    answer = discord.ui.TextInput(label="Your answer", style=discord.TextStyle.paragraph, required=True, max_length=4000)

    def __init__(self, question: dict, q_num: int, total: int):
        super().__init__(title="Question {}/{}".format(q_num, total))
        self.question     = question
        self.given_answer = None
        # FIX: Use label attribute properly
        self.answer.label = question["text"][:45]
        qtype = question["type"]
        if qtype == "short_answer":
            self.answer.style      = discord.TextStyle.short
            self.answer.max_length = question.get("max_chars", 200)
            self.answer.placeholder = "Short answer (max {} chars)".format(question.get("max_chars", 200))
        elif qtype in ("long_answer", "paragraph"):
            self.answer.style      = discord.TextStyle.paragraph
            self.answer.max_length = question.get("max_chars", 4000)
            self.answer.placeholder = "Detailed answer..."
        elif qtype == "numeric":
            self.answer.style      = discord.TextStyle.short
            self.answer.max_length = 20
            self.answer.placeholder = "Numbers only"
        elif qtype == "range":
            self.answer.style      = discord.TextStyle.short
            self.answer.max_length = 20
            self.answer.placeholder = "Enter a number between {} and {}".format(
                question.get("range_min", ""), question.get("range_max", "")
            )
        elif qtype == "url":
            self.answer.style      = discord.TextStyle.short
            self.answer.max_length = 500
            self.answer.placeholder = "https://..."
        if not question["required"]:
            self.answer.required    = False
            self.answer.placeholder = (self.answer.placeholder or "") + " (optional)"

    async def on_submit(self, interaction: discord.Interaction):
        self.given_answer = self.answer.value.strip()
        self.interaction  = interaction
        await interaction.response.defer(ephemeral=True)
        self.stop()

# ---------------------------------------------------------------------------
# MCQ / Dropdown / YesNo child views (used inside the session view)
# ---------------------------------------------------------------------------

class MCQView(discord.ui.View):
    def __init__(self, options: list[str]):
        super().__init__(timeout=120)
        self.chosen = None
        for opt in options[:5]:
            btn          = discord.ui.Button(label=opt, style=discord.ButtonStyle.secondary)
            btn.callback = self._make_cb(opt)
            self.add_item(btn)

    def _make_cb(self, option: str):
        async def cb(interaction: discord.Interaction):
            self.chosen = option
            self.stop()
            for child in self.children:
                child.disabled = True
                if hasattr(child, "label") and child.label == option:
                    child.style = discord.ButtonStyle.primary
            await interaction.response.edit_message(view=self)
        return cb


class DropdownSelect(discord.ui.Select):
    def __init__(self, options: list[str]):
        super().__init__(placeholder="Choose an option…", options=[discord.SelectOption(label=o, value=o) for o in options[:25]])
        self.chosen = None

    async def callback(self, interaction: discord.Interaction):
        self.chosen = self.values[0]
        self.view.chosen = self.chosen
        self.view.stop()
        self.disabled = True
        await interaction.response.edit_message(view=self.view)

class DropdownView(discord.ui.View):
    def __init__(self, options: list[str]):
        super().__init__(timeout=120)
        self.chosen = None
        self.add_item(DropdownSelect(options))


class YesNoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.chosen = None

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.chosen = "Yes"
        self.stop()
        for c in self.children: c.disabled = True
        button.style = discord.ButtonStyle.primary
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.chosen = "No"
        self.stop()
        for c in self.children: c.disabled = True
        button.style = discord.ButtonStyle.primary
        await interaction.response.edit_message(view=self)

# ---------------------------------------------------------------------------
# Paginated Application Session View
# ---------------------------------------------------------------------------

def _fmt_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return "{}m {}s".format(m, s) if m else "{}s".format(s)


def _build_constraint_hint(q: dict) -> str:
    hints = []
    for k, label in [
        ("min_chars", "Min chars"), ("max_chars", "Max chars"),
        ("min_words", "Min words"), ("max_words", "Max words"),
        ("range_min", "Min value"), ("range_max", "Max value"),
    ]:
        if k in q:
            hints.append("{}: {}".format(label, q[k]))
    return " | ".join(hints) if hints else ""


class ApplicationSessionView(discord.ui.View):
    """
    Single persistent embed that the user pages through.
    One view per session, edited in-place — no new ephemeral messages per question.
    """

    def __init__(
        self,
        session: "ApplicationSession",
        questions: list[dict],
        member: discord.Member,
    ):
        super().__init__(timeout=600)   # 10-minute session timeout
        self.session   = session
        self.questions = questions
        self.member    = member
        self.answers: list[str | None] = [None] * len(questions)
        self.index     = 0
        self.started   = time.time()
        self.message: discord.Message | None = None   # set after first send
        self._update_buttons()

    # ── Navigation helpers ────────────────────────────

    def _update_buttons(self):
        """Enable/disable nav buttons based on current index."""
        total = len(self.questions)
        self.btn_first.disabled  = self.index == 0
        self.btn_prev.disabled   = self.index == 0
        self.btn_next.disabled   = self.index == total - 1
        self.btn_last.disabled   = self.index == total - 1
        # Submit only enabled when all required questions are answered
        unanswered_required = [
            i for i, q in enumerate(self.questions)
            if q.get("required", True) and not self.answers[i]
        ]
        self.btn_submit.disabled = bool(unanswered_required)

    def build_embed(self) -> discord.Embed:
        total    = len(self.questions)
        q        = self.questions[self.index]
        answered = sum(1 for a in self.answers if a)
        elapsed  = _fmt_duration(time.time() - self.started)

        e = discord.Embed(
            title="📋 {} — Question {}/{}".format(self.session.app_name.title(), self.index + 1, total),
            color=Config.COLOR_INFO,
        )

        # Question text
        e.add_field(name="❓ Question", value=q["text"], inline=False)

        # Type + options
        type_label = TYPE_LABELS.get(q["type"], q["type"])
        type_str   = "**Type:** {}".format(type_label)
        if q.get("options"):
            type_str += "\n**Options:** " + ", ".join(q["options"])
        e.add_field(name="ℹ️ Info", value=type_str, inline=True)

        # Constraints
        hint = _build_constraint_hint(q)
        if hint:
            e.add_field(name="📏 Constraints", value=hint, inline=True)

        # Required badge
        e.add_field(
            name="Required",
            value="Yes ✅" if q.get("required", True) else "No (optional) ⏭️",
            inline=True,
        )

        # Current answer
        current = self.answers[self.index]
        e.add_field(
            name="✏️ Your Answer",
            value=current if current else "*Not answered yet*",
            inline=False,
        )

        # Progress overview — show all Q answers compactly
        progress_lines = []
        for i, (ques, ans) in enumerate(zip(self.questions, self.answers)):
            tick = "✅" if ans else ("⚠️" if ques.get("required", True) else "⬜")
            short_q = ques["text"][:40] + ("…" if len(ques["text"]) > 40 else "")
            short_a = (ans[:30] + "…" if ans and len(ans) > 30 else ans) or "*unanswered*"
            progress_lines.append("{} **Q{}:** {} → {}".format(tick, i + 1, short_q, short_a))
        e.add_field(
            name="📊 Progress ({}/{} answered)".format(answered, total),
            value="\n".join(progress_lines),
            inline=False,
        )

        e.set_footer(text="⏱️ Time elapsed: {} | Use << < > >> to navigate • Answer button to respond".format(elapsed))
        return e

    async def _refresh(self, interaction: discord.Interaction | None = None):
        """Edit the session message in place."""
        self._update_buttons()
        embed = self.build_embed()
        if interaction:
            await interaction.response.edit_message(embed=embed, view=self)
        elif self.message:
            await self.message.edit(embed=embed, view=self)

    # FIX: Use interaction.followup instead of interaction.response for ephemeral errors after defer
    async def _send_error(self, interaction: discord.Interaction, msg: str):
        """Send a temporary ephemeral error that auto-deletes after 5s."""
        try:
            await interaction.followup.send(
                embed=discord.Embed(description="⚠️ " + msg, color=Config.COLOR_ERR),
                ephemeral=True,
            )
        except Exception:
            # Fallback: already responded or webhook context
            await interaction.channel.send(
                embed=discord.Embed(description="⚠️ " + msg, color=Config.COLOR_ERR),
                delete_after=5,
            )

    # ── Navigation buttons ────────────────────────────

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="app_first", row=0)
    async def btn_first(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            return await interaction.response.send_message("Not your application.", ephemeral=True)
        self.index = 0
        await self._refresh(interaction)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary, custom_id="app_prev", row=0)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            return await interaction.response.send_message("Not your application.", ephemeral=True)
        if self.index > 0:
            self.index -= 1
        await self._refresh(interaction)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary, custom_id="app_next", row=0)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            return await interaction.response.send_message("Not your application.", ephemeral=True)
        if self.index < len(self.questions) - 1:
            self.index += 1
        await self._refresh(interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="app_last", row=0)
    async def btn_last(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            return await interaction.response.send_message("Not your application.", ephemeral=True)
        self.index = len(self.questions) - 1
        await self._refresh(interaction)

    # ── Answer button (row 1) ─────────────────────────

    @discord.ui.button(label="✏️ Answer", style=discord.ButtonStyle.primary, custom_id="app_answer", row=1)
    async def btn_answer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            return await interaction.response.send_message("Not your application.", ephemeral=True)

        q     = self.questions[self.index]
        qtype = q["type"]

        # -- MCQ --
        if qtype == "multiple_choice":
            view = MCQView(q.get("options", []))
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Q{}: {}".format(self.index + 1, q["text"]),
                    description="Select one of the options below:",
                    color=Config.COLOR_MOD,
                ),
                view=view, ephemeral=True,
            )
            await view.wait()
            if view.chosen:
                self.answers[self.index] = view.chosen
                await self._refresh()

        # -- Dropdown --
        elif qtype == "dropdown":
            view = DropdownView(q.get("options", []))
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Q{}: {}".format(self.index + 1, q["text"]),
                    description="Pick from the dropdown:",
                    color=Config.COLOR_MOD,
                ),
                view=view, ephemeral=True,
            )
            await view.wait()
            if view.chosen:
                self.answers[self.index] = view.chosen
                await self._refresh()

        # -- Yes/No --
        elif qtype == "yes_no":
            view = YesNoView()
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Q{}: {}".format(self.index + 1, q["text"]),
                    color=Config.COLOR_MOD,
                ),
                view=view, ephemeral=True,
            )
            await view.wait()
            if view.chosen:
                self.answers[self.index] = view.chosen
                await self._refresh()

        # -- Text-based (modal) --
        else:
            modal = TextAnswerModal(q, self.index + 1, len(self.questions))
            await interaction.response.send_modal(modal)
            await modal.wait()
            raw = modal.given_answer
            if raw:
                err = _validate_answer(raw, q)
                if err:
                    # FIX: Use followup instead of response (modal already deferred)
                    try:
                        await modal.interaction.followup.send(
                            embed=discord.Embed(description="⚠️ " + err, color=Config.COLOR_ERR),
                            ephemeral=True,
                        )
                    except Exception:
                        pass
                else:
                    self.answers[self.index] = raw
                    await self._refresh()

    # ── Clear answer (row 1) ──────────────────────────

    @discord.ui.button(label="🗑️ Clear", style=discord.ButtonStyle.secondary, custom_id="app_clear", row=1)
    async def btn_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            return await interaction.response.send_message("Not your application.", ephemeral=True)
        self.answers[self.index] = None
        await self._refresh(interaction)

    # ── Submit (row 2) ────────────────────────────────

    @discord.ui.button(label="📨 Submit Application", style=discord.ButtonStyle.success, custom_id="app_submit", row=2)
    async def btn_submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            return await interaction.response.send_message("Not your application.", ephemeral=True)

        # Final required-answer check
        missing = [
            i + 1 for i, q in enumerate(self.questions)
            if q.get("required", True) and not self.answers[i]
        ]
        if missing:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    description="⚠️ Please answer required question(s): **{}**".format(
                        ", ".join("Q{}".format(n) for n in missing)
                    ),
                    color=Config.COLOR_ERR,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        self.stop()
        self.session.answers = [
            {"question": q["text"], "answer": a or "Skipped"}
            for q, a in zip(self.questions, self.answers)
        ]
        self.session.elapsed = _fmt_duration(time.time() - self.started)
        self.session._submit_event.set()

    # ── Cancel (row 2) ────────────────────────────────

    @discord.ui.button(label="✖ Cancel", style=discord.ButtonStyle.danger, custom_id="app_cancel", row=2)
    async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            return await interaction.response.send_message("Not your application.", ephemeral=True)
        self.stop()
        self.session._cancel_event.set()
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Application Cancelled",
                description="Your session has been cancelled. You can apply again later.",
                color=Config.COLOR_ERR,
            ),
            view=None,
        )

    async def on_timeout(self):
        self.session._cancel_event.set()
        if self.message:
            try:
                await self.message.edit(
                    embed=discord.Embed(
                        title="Session Timed Out",
                        description="Your application session expired due to inactivity.",
                        color=Config.COLOR_ERR,
                    ),
                    view=None,
                )
            except Exception:
                pass

# ---------------------------------------------------------------------------
# Application Session (orchestrator)
# ---------------------------------------------------------------------------

class ApplicationSession:
    def __init__(self, bot: commands.Bot, interaction: discord.Interaction, app: dict, app_name: str):
        self.bot         = bot
        self.interaction = interaction
        self.app         = app
        self.app_name    = app_name
        self.answers: list[dict] = []
        self.elapsed     = "0s"
        self._submit_event = asyncio.Event()
        self._cancel_event = asyncio.Event()

    async def run(self):
        questions   = self.app.get("questions", [])
        session_key = (self.interaction.guild_id, self.interaction.user.id, self.app_name)

        if not questions:
            await self.interaction.followup.send(embed=_err("This application has no questions yet."), ephemeral=True)
            return

        _active_sessions.add(session_key)
        try:
            view = ApplicationSessionView(self, questions, self.interaction.user)

            intro = discord.Embed(
                title="📋 {} Application".format(self.app_name.title()),
                description=(
                    (self.app.get("description", "") + "\n\n" if self.app.get("description") else "") +
                    "You have **{}** question(s).\n\n"
                    "Use **◀️ ▶️** to navigate, **✏️ Answer** to respond to each question.\n"
                    "When all required questions are answered the **Submit** button will unlock.\n"
                    "Only you can see this message."
                ).format(len(questions)),
                color=Config.COLOR_INFO,
            )
            await self.interaction.followup.send(embed=intro, ephemeral=True)

            msg = await self.interaction.followup.send(
                embed=view.build_embed(),
                view=view,
                ephemeral=True,
            )
            view.message = msg

            done, _ = await asyncio.wait(
                [
                    asyncio.create_task(self._submit_event.wait()),
                    asyncio.create_task(self._cancel_event.wait()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if self._cancel_event.is_set():
                return

            await self._submit(self.interaction.channel, self.interaction.user)

        finally:
            _active_sessions.discard(session_key)

    async def _submit(self, channel, member: discord.Member):
        elapsed = self.elapsed

        e = discord.Embed(
            title="📋 New Application: {}".format(self.app_name.title()),
            color=Config.COLOR_INFO,
        )
        e.set_author(name=str(member), icon_url=member.display_avatar.url)
        e.add_field(name="Applicant", value=member.mention, inline=True)
        e.add_field(name="User ID",   value=str(member.id),  inline=True)
        e.add_field(name="⏱️ Time Taken", value=elapsed,     inline=True)

        for i, item in enumerate(self.answers):
            e.add_field(
                name="Q{}: {}".format(i + 1, item["question"][:100]),
                value=item["answer"][:1024] or "*(no answer)*",
                inline=False,
            )

        log_channel_id = self.app.get("log_channel")
        if log_channel_id:
            log_ch = channel.guild.get_channel(int(log_channel_id))
            if log_ch:
                grant_role_id = self.app.get("grant_role")
                view = ReviewView(member, self.app_name, grant_role_id, channel.guild)
                await log_ch.send(embed=e, view=view)

        _submission_times[(self.interaction.guild_id, self.interaction.user.id, self.app_name)] = time.time()

        await self.interaction.followup.send(
            embed=discord.Embed(
                title="✅ Application Submitted!",
                description="Your **{}** application has been submitted. You'll be notified of the decision.".format(
                    self.app_name.title()
                ),
                color=Config.COLOR_OK,
            ),
            ephemeral=True,
        )

# ---------------------------------------------------------------------------
# Review decision helper
# ---------------------------------------------------------------------------

async def _apply_decision(
    interaction: discord.Interaction,
    applicant: discord.Member,
    app_name: str,
    grant_role_id: int | None,
    accepted: bool,
    reason: str | None = None,
):
    role_note = ""
    if accepted and grant_role_id:
        role = interaction.guild.get_role(grant_role_id)
        if role:
            try:
                await applicant.add_roles(role, reason="Application accepted: {}".format(app_name))
                role_note = "\nGranted role: **{}**".format(role.name)
            except discord.Forbidden:
                role_note = "\nCould not grant role (missing permissions)."

    decision_word = "ACCEPTED" if accepted else "DENIED"
    decision_val  = "{} by {}{}".format(
        decision_word, interaction.user.mention,
        ("\nReason: " + reason) if reason else "",
    ) + role_note

    if interaction.message and interaction.message.embeds:
        edited = interaction.message.embeds[0]
        edited.colour = discord.Colour(Config.COLOR_OK if accepted else Config.COLOR_ERR)
        edited.add_field(name="Decision", value=decision_val, inline=False)
        await interaction.message.edit(embed=edited, view=None)

    try:
        if accepted:
            dm = discord.Embed(
                title="Your application was accepted! 🎉",
                description="**Application:** {}\nCongratulations!{}{}".format(
                    app_name, role_note,
                    "\n**Note:** " + reason if reason else "",
                ),
                color=Config.COLOR_OK,
            )
        else:
            dm = discord.Embed(
                title="Your application was denied",
                description="**Application:** {}{}".format(
                    app_name, "\n**Reason:** " + reason if reason else "",
                ),
                color=Config.COLOR_ERR,
            )
        await applicant.send(embed=dm)
    except discord.Forbidden:
        pass

    result = "Accepted" if accepted else "Denied"
    await interaction.response.send_message(
        embed=_ok("Application {}".format(result), "{}'s application has been {}.{}".format(
            applicant.mention, result.lower(), role_note,
        )),
        ephemeral=True,
    )

# ---------------------------------------------------------------------------
# Reason modals for review buttons
# ---------------------------------------------------------------------------

class AcceptReasonModal(discord.ui.Modal, title="Accept with Reason"):
    reason = discord.ui.TextInput(label="Note for the applicant (optional)", style=discord.TextStyle.paragraph, required=False, max_length=1000)

    def __init__(self, applicant, app_name, grant_role_id):
        super().__init__()
        self.applicant = applicant; self.app_name = app_name; self.grant_role_id = grant_role_id

    async def on_submit(self, interaction):
        await _apply_decision(interaction, self.applicant, self.app_name, self.grant_role_id, True, self.reason.value.strip() or None)


class DenyReasonModal(discord.ui.Modal, title="Deny with Reason"):
    reason = discord.ui.TextInput(label="Reason for denial", style=discord.TextStyle.paragraph, required=True, max_length=1000)

    def __init__(self, applicant, app_name, grant_role_id):
        super().__init__()
        self.applicant = applicant; self.app_name = app_name; self.grant_role_id = grant_role_id

    async def on_submit(self, interaction):
        await _apply_decision(interaction, self.applicant, self.app_name, self.grant_role_id, False, self.reason.value.strip())

# ---------------------------------------------------------------------------
# "Open Ticket with User"
# ---------------------------------------------------------------------------

async def _open_ticket_for_applicant(
    interaction: discord.Interaction,
    applicant: discord.Member,
    app_name: str,
):
    from utils.data import load, save as _save
    guild    = interaction.guild
    settings = load("guild_settings.json").get(str(guild.id), {})

    cat_name  = settings.get("ticket_category", getattr(Config, "TICKET_CATEGORY_NAME", "Tickets"))
    category  = discord.utils.get(guild.categories, name=cat_name)
    if not category:
        category = await guild.create_category(cat_name)

    overwrites = {
        guild.default_role:  discord.PermissionOverwrite(read_messages=False),
        applicant:           discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        guild.me:            discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
        interaction.user:    discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True),
    }
    for role_id in settings.get("ticket_staff_roles", []):
        role = guild.get_role(int(role_id))
        if role:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True)

    slug    = "app-review"
    channel = await category.create_text_channel(
        "{}-{}".format(slug, applicant.name[:16].lower().replace(" ", "-")),
        overwrites=overwrites,
        topic="Application review: {} — {}".format(app_name, applicant),
    )

    e = discord.Embed(
        title="📋 Application Review — {}".format(app_name.title()),
        description=(
            "{} — this channel has been opened by {} to discuss your **{}** application.\n\n"
            "Please keep the conversation relevant."
        ).format(applicant.mention, interaction.user.mention, app_name.title()),
        color=Config.COLOR_INFO,
    )
    await channel.send(embed=e)

    await interaction.response.send_message(
        embed=_ok("Ticket Opened", "Review channel created: {}".format(channel.mention)),
        ephemeral=True,
    )

# ---------------------------------------------------------------------------
# Review View
# ---------------------------------------------------------------------------

class ReviewView(discord.ui.View):
    def __init__(self, applicant: discord.Member, app_name: str, grant_role_id: int | None, guild: discord.Guild):
        super().__init__(timeout=None)
        self.applicant     = applicant
        self.app_name      = app_name
        self.grant_role_id = grant_role_id
        self.guild         = guild

    def _perm_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.manage_guild

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅", row=0)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._perm_check(interaction):
            return await interaction.response.send_message(embed=_err("No permission."), ephemeral=True)
        await _apply_decision(interaction, self.applicant, self.app_name, self.grant_role_id, True)

    @discord.ui.button(label="Accept w/ Reason", style=discord.ButtonStyle.success, emoji="📝", row=0)
    async def accept_reason(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._perm_check(interaction):
            return await interaction.response.send_message(embed=_err("No permission."), ephemeral=True)
        await interaction.response.send_modal(AcceptReasonModal(self.applicant, self.app_name, self.grant_role_id))

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌", row=1)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._perm_check(interaction):
            return await interaction.response.send_message(embed=_err("No permission."), ephemeral=True)
        await _apply_decision(interaction, self.applicant, self.app_name, self.grant_role_id, False)

    @discord.ui.button(label="Deny w/ Reason", style=discord.ButtonStyle.danger, emoji="📝", row=1)
    async def deny_reason(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._perm_check(interaction):
            return await interaction.response.send_message(embed=_err("No permission."), ephemeral=True)
        await interaction.response.send_modal(DenyReasonModal(self.applicant, self.app_name, self.grant_role_id))

    @discord.ui.button(label="Open Ticket w/ User", style=discord.ButtonStyle.secondary, emoji="🎟️", row=2)
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._perm_check(interaction):
            return await interaction.response.send_message(embed=_err("No permission."), ephemeral=True)
        await _open_ticket_for_applicant(interaction, self.applicant, self.app_name)

    @discord.ui.button(label="Under Consideration", style=discord.ButtonStyle.primary, emoji="🔵", row=2)
    async def under_consideration(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._perm_check(interaction):
            return await interaction.response.send_message(embed=_err("No permission."), ephemeral=True)
        if interaction.message and interaction.message.embeds:
            edited = interaction.message.embeds[0]
            edited.colour = discord.Colour.blue()
            edited.fields = [f for f in edited.fields if f.name != "Status"]
            edited.add_field(name="Status", value="🔵 Under Consideration by {}".format(interaction.user.mention), inline=False)
            await interaction.message.edit(embed=edited)
        try:
            notif = discord.Embed(
                title="Your application is under consideration",
                description="**Application:** {}\nStaff are reviewing your application. You will be notified of the final decision.".format(self.app_name.title()),
                color=discord.Colour.blue(),
            )
            await self.applicant.send(embed=notif)
        except discord.Forbidden:
            pass
        await interaction.response.send_message(
            embed=_ok("Marked Under Consideration", "{} has been notified.".format(self.applicant.mention)),
            ephemeral=True,
        )

# ---------------------------------------------------------------------------
# Shared session-start helper
# ---------------------------------------------------------------------------

async def _start_application_session(interaction: discord.Interaction, bot: commands.Bot, app_name: str):
    app = _get_app(interaction.guild_id, app_name)
    if not app:
        return await interaction.response.send_message(embed=_err("This application no longer exists."), ephemeral=True)
    if not app.get("open", True):
        return await interaction.response.send_message(embed=_err("This application is currently closed."), ephemeral=True)
    if (interaction.guild_id, interaction.user.id, app_name) in _active_sessions:
        return await interaction.response.send_message(
            embed=_err("You already have an active session for this application."), ephemeral=True,
        )
    remaining = _check_cooldown(interaction.guild_id, interaction.user.id, app_name)
    if remaining is not None:
        return await interaction.response.send_message(
            embed=_err("Please wait **{:.0f}s** before applying again.".format(remaining)), ephemeral=True,
        )
    await interaction.response.defer(ephemeral=True)
    session = ApplicationSession(bot, interaction, app, app_name)
    await session.run()

# ---------------------------------------------------------------------------
# Apply button / multi-apply views
# ---------------------------------------------------------------------------

class ApplyButtonView(discord.ui.View):
    def __init__(self, app_name: str, bot: commands.Bot):
        super().__init__(timeout=None)
        self.app_name = app_name
        self.bot      = bot

    @discord.ui.button(label="Apply", style=discord.ButtonStyle.primary, emoji="📋")
    async def apply_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _start_application_session(interaction, self.bot, self.app_name)


class MultiApplySelect(discord.ui.Select):
    def __init__(self, app_names: list[str], guild_id: int, bot: commands.Bot):
        self.bot = bot
        options  = []
        for name in app_names:
            app     = _get_app(guild_id, name)
            q_count = len(app.get("questions", [])) if app else 0
            desc    = (app.get("description") or "{} question(s)".format(q_count))[:100]
            closed  = app and not app.get("open", True)
            options.append(discord.SelectOption(
                label=name.title() + (" [Closed]" if closed else ""),
                value=name, description=desc, emoji="📋",
            ))
        super().__init__(placeholder="Choose an application to apply for…", options=options)

    async def callback(self, interaction: discord.Interaction):
        await _start_application_session(interaction, self.bot, self.values[0])


class MultiApplyView(discord.ui.View):
    def __init__(self, app_names: list[str], guild_id: int, bot: commands.Bot, style: str = "button"):
        super().__init__(timeout=None)
        if style == "dropdown":
            self.add_item(MultiApplySelect(app_names, guild_id, bot))
        else:
            for name in app_names:
                app    = _get_app(guild_id, name)
                closed = app and not app.get("open", True)
                label  = name.title() + (" [Closed]" if closed else "")
                btn    = discord.ui.Button(
                    label=label,
                    style=discord.ButtonStyle.secondary if closed else discord.ButtonStyle.primary,
                    emoji="📋",
                )
                btn.callback = self._make_cb(name, bot)
                self.add_item(btn)

    @staticmethod
    def _make_cb(app_name: str, bot: commands.Bot):
        async def cb(interaction: discord.Interaction):
            await _start_application_session(interaction, bot, app_name)
        return cb

# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class ApplicationCog(commands.Cog, name="Applications"):
    """Advanced application system — paginated single-embed sessions."""

    slash = app_commands.Group(name="application", description="Application system commands")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -- /application create ----------------------------------------------

    @slash.command(name="create", description="Create a new application form.")
    @app_commands.describe(name="Internal name e.g. staff, mod, builder", description="Short description shown to applicants", log_channel="Channel where submissions are sent", grant_role="Role to grant on acceptance (optional)")
    @app_commands.default_permissions(manage_guild=True)
    async def app_create(self, interaction: discord.Interaction, name: str, log_channel: discord.TextChannel, description: str = None, grant_role: discord.Role = None):
        name = name.lower().strip()
        if _get_app(interaction.guild_id, name):
            return await interaction.response.send_message(embed=_err("Application `{}` already exists.".format(name)), ephemeral=True)
        _save_app(interaction.guild_id, name, {
            "name": name, "description": description or "", "log_channel": log_channel.id,
            "grant_role": grant_role.id if grant_role else None, "questions": [], "open": True,
        })
        await interaction.response.send_message(
            embed=_ok("Application Created: {}".format(name.title()),
                "Log channel: {}\n{}\nAdd questions with `/application addquestion name:{}`".format(
                    log_channel.mention, "Grant role: {}".format(grant_role.mention) if grant_role else "", name,
                )),
            ephemeral=True,
        )

    # -- /application addquestion -----------------------------------------

    @slash.command(name="addquestion", description="Add a question to an application.")
    @app_commands.describe(name="Application name")
    @app_commands.default_permissions(manage_guild=True)
    async def app_addquestion(self, interaction: discord.Interaction, name: str):
        if not _get_app(interaction.guild_id, name.lower()):
            return await interaction.response.send_message(embed=_err("Application `{}` not found.".format(name)), ephemeral=True)
        await interaction.response.send_modal(AddQuestionModal(name.lower(), interaction.guild_id))

    # -- /application removequestion --------------------------------------

    @slash.command(name="removequestion", description="Remove a question by number.")
    @app_commands.describe(name="Application name", number="Question number to remove")
    @app_commands.default_permissions(manage_guild=True)
    async def app_removequestion(self, interaction: discord.Interaction, name: str, number: int):
        app = _get_app(interaction.guild_id, name.lower())
        if not app:
            return await interaction.response.send_message(embed=_err("Not found."), ephemeral=True)
        questions = app.get("questions", [])
        idx = number - 1
        if idx < 0 or idx >= len(questions):
            return await interaction.response.send_message(embed=_err("Invalid question number."), ephemeral=True)
        removed = questions.pop(idx)
        app["questions"] = questions
        _save_app(interaction.guild_id, name.lower(), app)
        await interaction.response.send_message(embed=_ok("Question Removed", "Removed: **{}**".format(removed["text"])), ephemeral=True)

    # -- /application editquestion ----------------------------------------

    @slash.command(name="editquestion", description="Edit a question.")
    @app_commands.describe(name="Application name", number="Question number to edit")
    @app_commands.default_permissions(manage_guild=True)
    async def app_editquestion(self, interaction: discord.Interaction, name: str, number: int):
        app = _get_app(interaction.guild_id, name.lower())
        if not app:
            return await interaction.response.send_message(embed=_err("Not found."), ephemeral=True)
        idx = number - 1
        if idx < 0 or idx >= len(app.get("questions", [])):
            return await interaction.response.send_message(embed=_err("Invalid question number."), ephemeral=True)
        await interaction.response.send_modal(EditQuestionModal(name.lower(), interaction.guild_id, idx))

    # -- /application reorderquestion -------------------------------------

    @slash.command(name="reorderquestion", description="Move a question to a different position.")
    @app_commands.describe(name="Application name", from_number="Current position", to_number="New position")
    @app_commands.default_permissions(manage_guild=True)
    async def app_reorder(self, interaction: discord.Interaction, name: str, from_number: int, to_number: int):
        app = _get_app(interaction.guild_id, name.lower())
        if not app:
            return await interaction.response.send_message(embed=_err("Not found."), ephemeral=True)
        questions = app.get("questions", [])
        fi, ti = from_number - 1, to_number - 1
        if not (0 <= fi < len(questions)) or not (0 <= ti < len(questions)):
            return await interaction.response.send_message(embed=_err("Invalid question numbers."), ephemeral=True)
        q = questions.pop(fi)
        questions.insert(ti, q)
        app["questions"] = questions
        _save_app(interaction.guild_id, name.lower(), app)
        await interaction.response.send_message(embed=_ok("Question Moved", "Moved **{}** to position {}.".format(q["text"], to_number)), ephemeral=True)

    # -- /application preview ---------------------------------------------

    @slash.command(name="preview", description="Preview an application and its questions.")
    @app_commands.describe(name="Application name")
    @app_commands.default_permissions(manage_guild=True)
    async def app_preview(self, interaction: discord.Interaction, name: str):
        app = _get_app(interaction.guild_id, name.lower())
        if not app:
            return await interaction.response.send_message(embed=_err("Not found."), ephemeral=True)
        questions  = app.get("questions", [])
        log_ch     = interaction.guild.get_channel(app.get("log_channel", 0))
        grant_role = interaction.guild.get_role(app.get("grant_role", 0)) if app.get("grant_role") else None
        e = discord.Embed(title="Preview: {}".format(name.title()), description=app.get("description") or "No description.", color=Config.COLOR_INFO)
        e.add_field(name="Status",      value="Open" if app.get("open") else "Closed", inline=True)
        e.add_field(name="Questions",   value=str(len(questions)),                      inline=True)
        e.add_field(name="Log Channel", value=log_ch.mention if log_ch else "Not set",  inline=True)
        if grant_role:
            e.add_field(name="Grant Role", value=grant_role.mention, inline=True)
        for i, q in enumerate(questions):
            val = "Type: `{}`".format(TYPE_LABELS.get(q["type"], q["type"]))
            if q.get("options"):
                val += "\nOptions: " + ", ".join(q["options"])
            val += "\n" + _build_constraint_hint(q)
            val += "\n{}".format("Required" if q.get("required", True) else "Optional")
            e.add_field(name="Q{}: {}".format(i+1, q["text"][:80]), value=val.strip(), inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # -- /application list ------------------------------------------------

    @slash.command(name="list", description="List all applications.")
    @app_commands.default_permissions(manage_guild=True)
    async def app_list(self, interaction: discord.Interaction):
        apps = _list_apps(interaction.guild_id)
        if not apps:
            return await interaction.response.send_message(embed=_info("No Applications", "Use `/application create` to make one."), ephemeral=True)
        e = _info("Applications ({})".format(len(apps)))
        gd = _load_guild(interaction.guild_id)
        for app_name in apps:
            app = gd[app_name]
            e.add_field(name=app_name.title(), value="{} | {} question(s)".format("Open" if app.get("open") else "Closed", len(app.get("questions", []))), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # -- /application open / close ----------------------------------------

    @slash.command(name="open", description="Open an application for submissions.")
    @app_commands.describe(name="Application name")
    @app_commands.default_permissions(manage_guild=True)
    async def app_open(self, interaction: discord.Interaction, name: str):
        app = _get_app(interaction.guild_id, name.lower())
        if not app:
            return await interaction.response.send_message(embed=_err("Not found."), ephemeral=True)
        app["open"] = True
        _save_app(interaction.guild_id, name.lower(), app)
        await interaction.response.send_message(embed=_ok("Application Opened", "`{}` is now accepting submissions.".format(name)), ephemeral=True)

    @slash.command(name="close", description="Close an application.")
    @app_commands.describe(name="Application name")
    @app_commands.default_permissions(manage_guild=True)
    async def app_close(self, interaction: discord.Interaction, name: str):
        app = _get_app(interaction.guild_id, name.lower())
        if not app:
            return await interaction.response.send_message(embed=_err("Not found."), ephemeral=True)
        app["open"] = False
        _save_app(interaction.guild_id, name.lower(), app)
        await interaction.response.send_message(embed=_ok("Application Closed", "`{}` is no longer accepting submissions.".format(name)), ephemeral=True)

    # -- /application delete ----------------------------------------------

    @slash.command(name="delete", description="Permanently delete an application.")
    @app_commands.describe(name="Application name")
    @app_commands.default_permissions(administrator=True)
    async def app_delete(self, interaction: discord.Interaction, name: str):
        if _delete_app(interaction.guild_id, name.lower()):
            await interaction.response.send_message(embed=_ok("Deleted", "Application `{}` deleted.".format(name)), ephemeral=True)
        else:
            await interaction.response.send_message(embed=_err("Not found."), ephemeral=True)

    # -- /application setlogchannel ---------------------------------------

    @slash.command(name="setlogchannel", description="Change the log channel.")
    @app_commands.describe(name="Application name", channel="New log channel")
    @app_commands.default_permissions(manage_guild=True)
    async def app_setlog(self, interaction: discord.Interaction, name: str, channel: discord.TextChannel):
        app = _get_app(interaction.guild_id, name.lower())
        if not app:
            return await interaction.response.send_message(embed=_err("Not found."), ephemeral=True)
        app["log_channel"] = channel.id
        _save_app(interaction.guild_id, name.lower(), app)
        await interaction.response.send_message(embed=_ok("Log Channel Updated", "Submissions for `{}` → {}.".format(name, channel.mention)), ephemeral=True)

    # -- /application setrole ---------------------------------------------

    @slash.command(name="setrole", description="Set the role granted on acceptance.")
    @app_commands.describe(name="Application name", role="Role to grant on acceptance")
    @app_commands.default_permissions(manage_guild=True)
    async def app_setrole(self, interaction: discord.Interaction, name: str, role: discord.Role):
        app = _get_app(interaction.guild_id, name.lower())
        if not app:
            return await interaction.response.send_message(embed=_err("Not found."), ephemeral=True)
        app["grant_role"] = role.id
        _save_app(interaction.guild_id, name.lower(), app)
        await interaction.response.send_message(embed=_ok("Role Set", "**{}** granted on acceptance of `{}`.".format(role.name, name)), ephemeral=True)

    # -- /application resetcooldown ---------------------------------------

    @slash.command(name="resetcooldown", description="Clear a user's reapply cooldown.")
    @app_commands.describe(name="Application name", user="Member to reset")
    @app_commands.default_permissions(manage_guild=True)
    async def app_resetcooldown(self, interaction: discord.Interaction, name: str, user: discord.Member):
        app_name = name.lower()
        if not _get_app(interaction.guild_id, app_name):
            return await interaction.response.send_message(embed=_err("Not found."), ephemeral=True)
        key = (interaction.guild_id, user.id, app_name)
        s_cleared = key in _active_sessions
        _active_sessions.discard(key)
        c_cleared = _submission_times.pop(key, None) is not None
        parts = []
        if c_cleared: parts.append("reapply cooldown")
        if s_cleared: parts.append("active session lock")
        desc = "{}'s {} for **{}** cleared.".format(user.mention, " and ".join(parts), name) if parts else "{} had no active cooldown for **{}**.".format(user.mention, name)
        await interaction.response.send_message(embed=_ok("Cooldown Reset", desc), ephemeral=True)

    # -- /application checkstatus -----------------------------------------

    @slash.command(name="checkstatus", description="Check a user's cooldown/session status.")
    @app_commands.describe(name="Application name", user="Member to check")
    @app_commands.default_permissions(manage_guild=True)
    async def app_checkstatus(self, interaction: discord.Interaction, name: str, user: discord.Member):
        app_name = name.lower()
        if not _get_app(interaction.guild_id, app_name):
            return await interaction.response.send_message(embed=_err("Not found."), ephemeral=True)
        key         = (interaction.guild_id, user.id, app_name)
        has_session = key in _active_sessions
        remaining   = _check_cooldown(interaction.guild_id, user.id, app_name)
        if remaining:
            m, s = divmod(int(remaining), 60)
            cd_str = "On cooldown — **{}m {}s** remaining".format(m, s) if m else "On cooldown — **{}s** remaining".format(s)
        else:
            cd_str = "No cooldown active"
        e = _info("Status: {} — {}".format(user.display_name, name.title()),
                  "**Cooldown:** {}\n**Session:** {}".format(cd_str, "Active" if has_session else "None"))
        e.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # -- /application post ------------------------------------------------

    @slash.command(name="post", description="Post an Apply button in a channel.")
    @app_commands.describe(name="Application name", channel="Channel to post in", message="Custom description (optional)")
    @app_commands.default_permissions(manage_guild=True)
    async def app_post(self, interaction: discord.Interaction, name: str, channel: discord.TextChannel = None, message: str = None):
        app = _get_app(interaction.guild_id, name.lower())
        if not app:
            return await interaction.response.send_message(embed=_err("Not found."), ephemeral=True)
        ch = channel or interaction.channel
        e  = discord.Embed(
            title=name.title() + " Application",
            description=message or app.get("description") or "Click the button below to apply.",
            color=Config.COLOR_INFO,
        )
        e.set_footer(text="{} question(s)".format(len(app.get("questions", []))))
        await ch.send(embed=e, view=ApplyButtonView(name.lower(), self.bot))
        await interaction.response.send_message(embed=_ok("Posted", "Apply button posted in {}.".format(ch.mention)), ephemeral=True)

    # -- /application postmulti -------------------------------------------

    @slash.command(name="postmulti", description="Post a multi-app panel.")
    @app_commands.describe(names="Comma-separated application names", style="Buttons or dropdown", channel="Channel to post in", title="Custom embed title", message="Custom description")
    @app_commands.choices(style=[app_commands.Choice(name="Buttons", value="button"), app_commands.Choice(name="Dropdown", value="dropdown")])
    @app_commands.default_permissions(manage_guild=True)
    async def app_postmulti(self, interaction: discord.Interaction, names: str, style: app_commands.Choice[str] = None, channel: discord.TextChannel = None, title: str = None, message: str = None):
        app_names = [n.strip().lower() for n in names.split(",") if n.strip()]
        if not app_names:
            return await interaction.response.send_message(embed=_err("Provide at least one name."), ephemeral=True)
        if len(app_names) > 25:
            return await interaction.response.send_message(embed=_err("Max 25 applications per panel."), ephemeral=True)
        missing = [n for n in app_names if not _get_app(interaction.guild_id, n)]
        if missing:
            return await interaction.response.send_message(embed=_err("Not found: {}".format(", ".join(missing))), ephemeral=True)
        ch = channel or interaction.channel
        e  = discord.Embed(title=title or "Applications", description=message or "Select an application below.", color=Config.COLOR_INFO)
        for name in app_names:
            app = _get_app(interaction.guild_id, name)
            e.add_field(name=name.title(), value="{} | {} Q(s){}".format("Open" if app.get("open") else "Closed", len(app.get("questions", [])), "\n" + app.get("description", "") if app.get("description") else ""), inline=False)
        chosen_style = style.value if style else "button"
        await ch.send(embed=e, view=MultiApplyView(app_names, interaction.guild_id, self.bot, chosen_style))
        await interaction.response.send_message(embed=_ok("Posted", "Panel with {} apps in {}.".format(len(app_names), ch.mention)), ephemeral=True)

    # -- /application apply -----------------------------------------------

    @slash.command(name="apply", description="Apply for an application.")
    @app_commands.describe(name="Application name")
    async def app_apply(self, interaction: discord.Interaction, name: str):
        await _start_application_session(interaction, self.bot, name.lower())


async def setup(bot: commands.Bot):
    await bot.add_cog(ApplicationCog(bot))