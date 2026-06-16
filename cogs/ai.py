"""
cogs/ai.py
Slash group: /ai
Free AI using Groq — get a free key at https://console.groq.com
Prefix commands still work with ~
"""

import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import traceback
from datetime import datetime, timezone
from config import Config

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

_conversations: dict[str, list] = {}


async def groq_request(api_key: str, prompt: str, history: list = None, max_tokens: int = 512) -> str:
    messages = [{"role": "system", "content": "You are a helpful Discord bot assistant. Keep responses concise and under 1500 characters."}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model":       GROQ_MODEL,
        "messages":    messages,
        "max_tokens":  max_tokens,
        "temperature": 0.7,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(GROQ_URL, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            data = await resp.json()
            if resp.status != 200:
                error_msg = data.get("error", {}).get("message", str(data))
                raise Exception(f"Groq error {resp.status}: {error_msg}")
            return data["choices"][0]["message"]["content"].strip()


def ai_embed(title, content, ctx, color=Config.COLOR_INFO):
    e = discord.Embed(title=title, description=content, color=color, timestamp=datetime.now(timezone.utc))
    e.set_footer(text=f"Requested by {ctx.author} • Powered by Groq AI")
    return e


def ai_embed_i(title, content, interaction: discord.Interaction, color=Config.COLOR_INFO):
    e = discord.Embed(title=title, description=content, color=color, timestamp=datetime.now(timezone.utc))
    e.set_footer(text=f"Requested by {interaction.user} • Powered by Groq AI")
    return e


class AI(commands.Cog):
    """🤖 Free AI powered by Groq."""

    slash = app_commands.Group(name="ai", description="AI-powered commands")

    def __init__(self, bot):
        self.bot = bot

    def _key(self):
        return getattr(Config, "GROQ_API_KEY", "")

    def _check_key(self):
        k = self._key()
        return bool(k and k != "YOUR_GROQ_API_KEY_HERE")

    # ── ASK ───────────────────────────────────────────

    @commands.command(name="ask")
    async def ask(self, ctx, *, question: str):
        """Ask the AI anything."""
        try:
            if not self._check_key():
                return await ctx.reply("❌ No Groq API key set. Get one free at https://console.groq.com")
            msg = await ctx.reply("🤔 Thinking...")
            answer = await groq_request(self._key(), question)
            await msg.edit(content=None, embed=ai_embed("🤖 AI Answer", answer[:2000], ctx))
        except Exception as e:
            print(f"[AI] ask error: {traceback.format_exc()}")
            try:
                await ctx.reply(f"❌ AI error: {e}")
            except Exception:
                pass

    @slash.command(name="ask", description="Ask the AI anything.")
    @app_commands.describe(question="Your question")
    async def ask_slash(self, interaction: discord.Interaction, question: str):
        if not self._check_key():
            return await interaction.response.send_message("❌ No Groq API key set. Get one free at https://console.groq.com", ephemeral=True)
        await interaction.response.defer()
        try:
            answer = await groq_request(self._key(), question)
            await interaction.followup.send(embed=ai_embed_i("🤖 AI Answer", answer[:2000], interaction))
        except Exception as e:
            await interaction.followup.send(f"❌ AI error: {e}")

    # ── CHAT ──────────────────────────────────────────

    @commands.command(name="chat")
    async def chat(self, ctx, *, message: str):
        """Multi-turn AI conversation."""
        try:
            if not self._check_key():
                return await ctx.reply("❌ No Groq API key set.")
            key = f"{ctx.guild.id}:{ctx.author.id}"
            history = _conversations.setdefault(key, [])
            msg = await ctx.reply("🤔 Thinking...")
            reply = await groq_request(self._key(), message, history)
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": reply})
            if len(history) > 20:
                _conversations[key] = history[-20:]
            e = ai_embed("💬 AI Chat", reply[:2000], ctx)
            e.add_field(name="Your message", value=message[:200], inline=False)
            await msg.edit(content=None, embed=e)
        except Exception as e:
            print(f"[AI] chat error: {traceback.format_exc()}")
            try:
                await ctx.reply(f"❌ AI error: {e}")
            except Exception:
                pass

    @slash.command(name="chat", description="Have a multi-turn conversation with the AI.")
    @app_commands.describe(message="Your message")
    async def chat_slash(self, interaction: discord.Interaction, message: str):
        if not self._check_key():
            return await interaction.response.send_message("❌ No Groq API key set.", ephemeral=True)
        await interaction.response.defer()
        try:
            key = f"{interaction.guild.id}:{interaction.user.id}"
            history = _conversations.setdefault(key, [])
            reply = await groq_request(self._key(), message, history)
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": reply})
            if len(history) > 20:
                _conversations[key] = history[-20:]
            e = ai_embed_i("💬 AI Chat", reply[:2000], interaction)
            e.add_field(name="Your message", value=message[:200], inline=False)
            await interaction.followup.send(embed=e)
        except Exception as e:
            await interaction.followup.send(f"❌ AI error: {e}")

    # ── CLEARCHAT ─────────────────────────────────────

    @commands.command(name="clearchat")
    async def clearchat(self, ctx):
        """Clear your AI conversation history."""
        _conversations.pop(f"{ctx.guild.id}:{ctx.author.id}", None)
        await ctx.reply("✅ Conversation history cleared!")

    @slash.command(name="clearchat", description="Clear your AI conversation history.")
    async def clearchat_slash(self, interaction: discord.Interaction):
        _conversations.pop(f"{interaction.guild.id}:{interaction.user.id}", None)
        await interaction.response.send_message("✅ Conversation history cleared!", ephemeral=True)

    # ── TRANSLATE ─────────────────────────────────────

    @commands.command(name="translate")
    async def translate(self, ctx, language: str, *, text: str):
        """Translate text. Usage: ~translate Spanish Hello"""
        try:
            if not self._check_key():
                return await ctx.reply("❌ No Groq API key set.")
            msg = await ctx.reply("🌐 Translating...")
            result = await groq_request(
                self._key(),
                f"Translate to {language}. Only respond with the translation, nothing else: {text}",
                max_tokens=300
            )
            e = ai_embed(f"🌐 Translated to {language}", result, ctx)
            e.add_field(name="Original", value=text[:200], inline=False)
            await msg.edit(content=None, embed=e)
        except Exception as e:
            try:
                await ctx.reply(f"❌ AI error: {e}")
            except Exception:
                pass

    @slash.command(name="translate", description="Translate text to any language.")
    @app_commands.describe(language="Target language (e.g. Spanish, French)", text="Text to translate")
    async def translate_slash(self, interaction: discord.Interaction, language: str, text: str):
        if not self._check_key():
            return await interaction.response.send_message("❌ No Groq API key set.", ephemeral=True)
        await interaction.response.defer()
        try:
            result = await groq_request(
                self._key(),
                f"Translate to {language}. Only respond with the translation, nothing else: {text}",
                max_tokens=300
            )
            e = ai_embed_i(f"🌐 Translated to {language}", result, interaction)
            e.add_field(name="Original", value=text[:200], inline=False)
            await interaction.followup.send(embed=e)
        except Exception as e:
            await interaction.followup.send(f"❌ AI error: {e}")

    # ── SUMMARIZE ─────────────────────────────────────

    @commands.command(name="summarize")
    async def summarize(self, ctx, *, text: str):
        """Summarize a long piece of text."""
        try:
            if not self._check_key():
                return await ctx.reply("❌ No Groq API key set.")
            msg = await ctx.reply("📝 Summarizing...")
            result = await groq_request(self._key(), f"Summarize in 3-5 bullet points, be concise: {text}", max_tokens=300)
            await msg.edit(content=None, embed=ai_embed("📝 Summary", result[:2000], ctx))
        except Exception as e:
            try:
                await ctx.reply(f"❌ AI error: {e}")
            except Exception:
                pass

    @slash.command(name="summarize", description="Summarize a long piece of text.")
    @app_commands.describe(text="Text to summarize")
    async def summarize_slash(self, interaction: discord.Interaction, text: str):
        if not self._check_key():
            return await interaction.response.send_message("❌ No Groq API key set.", ephemeral=True)
        await interaction.response.defer()
        try:
            result = await groq_request(self._key(), f"Summarize in 3-5 bullet points, be concise: {text}", max_tokens=300)
            await interaction.followup.send(embed=ai_embed_i("📝 Summary", result[:2000], interaction))
        except Exception as e:
            await interaction.followup.send(f"❌ AI error: {e}")

    # ── STORY ─────────────────────────────────────────

    @commands.command(name="story")
    async def story(self, ctx, *, prompt: str):
        """Generate a short story."""
        try:
            if not self._check_key():
                return await ctx.reply("❌ No Groq API key set.")
            msg = await ctx.reply("📖 Writing your story...")
            result = await groq_request(self._key(), f"Write a short creative story (under 800 characters) about: {prompt}", max_tokens=400)
            await msg.edit(content=None, embed=ai_embed("📖 Story", result[:2000], ctx, Config.COLOR_MOD))
        except Exception as e:
            try:
                await ctx.reply(f"❌ AI error: {e}")
            except Exception:
                pass

    @slash.command(name="story", description="Generate a short AI story.")
    @app_commands.describe(prompt="What should the story be about?")
    async def story_slash(self, interaction: discord.Interaction, prompt: str):
        if not self._check_key():
            return await interaction.response.send_message("❌ No Groq API key set.", ephemeral=True)
        await interaction.response.defer()
        try:
            result = await groq_request(self._key(), f"Write a short creative story (under 800 characters) about: {prompt}", max_tokens=400)
            await interaction.followup.send(embed=ai_embed_i("📖 Story", result[:2000], interaction, Config.COLOR_MOD))
        except Exception as e:
            await interaction.followup.send(f"❌ AI error: {e}")

    # ── AIROAST ───────────────────────────────────────

    @commands.command(name="airoast")
    async def airoast(self, ctx, member: discord.Member = None):
        """Get an AI-generated roast."""
        try:
            if not self._check_key():
                return await ctx.reply("❌ No Groq API key set.")
            target = member or ctx.author
            msg = await ctx.reply("🔥 Cooking up a roast...")
            result = await groq_request(
                self._key(),
                f"Write a funny lighthearted roast for a Discord user named {target.display_name}. Keep it fun and under 200 characters.",
                max_tokens=100
            )
            await msg.edit(content=f"🔥 {target.mention} — {result}")
        except Exception as e:
            try:
                await ctx.reply(f"❌ AI error: {e}")
            except Exception:
                pass

    @slash.command(name="airoast", description="Get an AI-generated roast for a member.")
    @app_commands.describe(member="Member to roast (leave empty for yourself)")
    async def airoast_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        if not self._check_key():
            return await interaction.response.send_message("❌ No Groq API key set.", ephemeral=True)
        await interaction.response.defer()
        target = member or interaction.user
        try:
            result = await groq_request(
                self._key(),
                f"Write a funny lighthearted roast for a Discord user named {target.display_name}. Keep it fun and under 200 characters.",
                max_tokens=100
            )
            await interaction.followup.send(f"🔥 {target.mention} — {result}")
        except Exception as e:
            await interaction.followup.send(f"❌ AI error: {e}")

    # ── AIHELP ────────────────────────────────────────

    @commands.command(name="aihelp")
    async def aihelp(self, ctx):
        """Show all AI commands."""
        e = discord.Embed(title="🤖 AI Commands", color=Config.COLOR_INFO)
        e.add_field(name="`~ask <question>`",         value="Ask AI anything",            inline=False)
        e.add_field(name="`~chat <message>`",          value="Multi-turn conversation",    inline=False)
        e.add_field(name="`~clearchat`",               value="Clear conversation history", inline=False)
        e.add_field(name="`~translate <lang> <text>`", value="Translate to any language",  inline=False)
        e.add_field(name="`~summarize <text>`",        value="Summarize long text",        inline=False)
        e.add_field(name="`~story <prompt>`",          value="Generate a short story",     inline=False)
        e.add_field(name="`~airoast [@member]`",       value="AI-generated roast",         inline=False)
        e.set_footer(text="Powered by Groq AI — Free at console.groq.com")
        await ctx.reply(embed=e)


async def setup(bot):
    await bot.add_cog(AI(bot))
