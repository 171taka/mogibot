import discord
from discord.ext import commands
import os

# ============================================================
# CONFIGURATION
# ============================================================

TOKEN = os.environ.get("DISCORD_TOKEN")

# ID des rôles autorisés à lancer/fermer une SQ.
# Laisse [] si tu veux utiliser uniquement la permission Administrator.
ADMIN_ROLE_IDS = []

PREFIX = "!"

# ============================================================
# BOT
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# Gestion de plusieurs SQ par serveur (guild_id -> { sq_name_lower: { ... } })
# {
#     guild_id: {
#         "rr": {
#             "name": "RR",
#             "size": 3,
#             "teams": [set({user_id, ...})],
#             "pending": { target_id: {"proposer_id": proposer_id, "team": team_or_none} }
#         }
#     }
# }
queues = {}


def is_sq_admin(member: discord.Member) -> bool:
    """Vérifie si un membre peut lancer/fermer/reset une SQ."""
    if member.guild_permissions.administrator:
        return True

    return any(role.id in ADMIN_ROLE_IDS for role in member.roles)


def get_server_queues(guild_id: int):
    return queues.get(guild_id, {})


def find_team_in_queue(queue, user_id: int):
    """Retourne l'équipe contenant user_id dans une SQ spécifique, ou None."""
    for team in queue["teams"]:
        if user_id in team:
            return team
    return None


def team_label(team, guild: discord.Guild) -> str:
    members = []
    for user_id in team:
        member = guild.get_member(user_id)
        members.append(member.mention if member else f"<@{user_id}>")
    return ", ".join(members)


def format_name(size: int) -> str:
    return f"{size}v{size}"


def build_status(guild: discord.Guild, queue) -> str:
    size = queue["size"]

    if not queue["teams"]:
        return "No team confirmed yet."

    lines = []
    for number, team in enumerate(queue["teams"], start=1):
        lines.append(
            f"**Équipe {number} — {len(team)}/{size}**\n"
            f"{team_label(team, guild)}"
        )

    return "\n\n".join(lines)


# ============================================================
# EVENTS
# ============================================================

@bot.event
async def on_ready():
    print(f"Starting up as {bot.user} (ID: {bot.user.id})")
    print("Started up")


# ============================================================
# !sq <format> <name> (ex: !sq 3v3 RR)
# ============================================================

@bot.command()
@commands.guild_only()
async def sq(ctx, format_: str = None, *, name: str = None):
    """Ouvre une SQ nommée."""
    if not is_sq_admin(ctx.author):
        await ctx.send("❌ You need to be an administrator to open SQ.")
        return

    if not format_ or not name:
        await ctx.send("❌ Usage: `!sq <format> <name>` (ex: `!sq 3v3 RR` or `!sq 5v5 Shine`).")
        return

    format_clean = format_.lower().replace(" ", "")

    allowed = {
        "2v2": 2,
        "3v3": 3,
        "4v4": 4,
        "5v5": 5,
        "6v6": 6,
    }

    if format_clean not in allowed:
        await ctx.send("❌ Invalid format. Use `2v2`, `3v3`, `4v4`, `5v5` or `6v6`.")
        return

    guild_id = ctx.guild.id
    sq_key = name.strip().lower()

    if guild_id not in queues:
        queues[guild_id] = {}

    if sq_key in queues[guild_id]:
        await ctx.send(f"❌ An SQ named **{name}** is already opened on this server.")
        return

    size = allowed[format_clean]

    queues[guild_id][sq_key] = {
        "name": name.strip(),
        "size": size,
        "teams": [],
        "pending": {}
    }

    embed = discord.Embed(
        title=f"🎮 SQ '{name.strip()}' ({format_clean}) opened!",
        description=(
            f"Format : **{format_clean}**\n"
            f"Identifier : **{name.strip()}**\n\n"
            f"👥 Each team has **{size} players**.\n"
            f"📨 To invite : `!c @player1 @player2` or `!c {name.strip()} @player1 @player2`\n"
            f"✅ To accept : `!c`\n"
            f"🚪 To leave : `!d` or `!d {name.strip()}`\n"
            f"📋 To see teams : `!sqlist`"
        )
    )

    await ctx.send(embed=embed)


# ============================================================
# !c (Flexible handling for invitations & acceptances)
# ============================================================

async def handle_accept(ctx, queue):
    size = queue["size"]
    author_id = ctx.author.id
    pending_data = queue["pending"].get(author_id)

    if not pending_data:
        return

    proposer_id = pending_data["proposer_id"]
    target_team = pending_data["team"]
    proposer = ctx.guild.get_member(proposer_id)

    if find_team_in_queue(queue, author_id):
        queue["pending"].pop(author_id, None)
        await ctx.send("❌ You are already in a team in this SQ.")
        return

    if target_team is not None:
        if target_team not in queue["teams"]:
            queue["pending"].pop(author_id, None)
            await ctx.send("❌ The team you were invited to no longer exists.")
            return

        if len(target_team) >= size:
            queue["pending"].pop(author_id, None)
            await ctx.send(f"❌ The team is already full ({size}/{size}).")
            return

        target_team.add(author_id)
        queue["pending"].pop(author_id, None)

        await ctx.send(
            f"✅ {ctx.author.mention} accepted invite from {proposer.mention if proposer else f'<@{proposer_id}>'} in **{queue['name']}**.\n"
            f"👥 Team updated : {team_label(target_team, ctx.guild)} (**{len(target_team)}/{size}**)."
        )

        if len(target_team) == size:
            await ctx.send(f"🔥 **Team full in {queue['name']}!**\n{team_label(target_team, ctx.guild)}")
    else:
        if find_team_in_queue(queue, proposer_id):
            queue["pending"].pop(author_id, None)
            await ctx.send("❌ The player who invited you is already in a team.")
            return

        team = {proposer_id, author_id}
        queue["teams"].append(team)
        queue["pending"].pop(author_id, None)

        await ctx.send(
            f"✅ {ctx.author.mention} accepted invite of {proposer.mention if proposer else f'<@{proposer_id}>'} in **{queue['name']}**.\n"
            f"👥 Team created : {team_label(team, ctx.guild)} (**{len(team)}/{size}**)."
        )

        if len(team) == size:
            await ctx.send(f"🔥 **Team full in {queue['name']}!**\n{team_label(team, ctx.guild)}")


async def handle_invites(ctx, queue, members: list[discord.Member]):
    size = queue["size"]
    author_id = ctx.author.id
    author_team = find_team_in_queue(queue, author_id)

    # Check author team size capacity
    current_team_size = len(author_team) if author_team else 1
    if current_team_size >= size:
        await ctx.send(f"❌ Your team is already full ({size}/{size}).")
        return

    invited_mentions = []

    for member in members:
        # Stop if adding more players exceeds capacity
        if (current_team_size + len(invited_mentions)) >= size:
            await ctx.send(f"⚠️ Reached capacity limit ({size}/{size}). Some invitations could not be sent.")
            break

        if member.bot:
            await ctx.send(f"❌ Cannot invite {member.mention} (Bots are not allowed).")
            continue

        if member.id == author_id:
            await ctx.send("❌ You cannot invite yourself.")
            continue

        target_team = find_team
