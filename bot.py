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

# Une SQ active par serveur.
# {
#   guild_id: {
#       "size": 3,
#       "teams": {
#           frozenset({user_id, ...}): set(user_id, ...)
#       },
#       "pending": {
#           target_id: proposer_id
#       }
#   }
# }
queues = {}


def is_sq_admin(member: discord.Member) -> bool:
    """Vérifie si un membre peut lancer/fermer/reset une SQ."""
    if member.guild_permissions.administrator:
        return True

    return any(role.id in ADMIN_ROLE_IDS for role in member.roles)


def get_queue(guild_id: int):
    return queues.get(guild_id)


def find_team(guild_id: int, user_id: int):
    """Retourne l'équipe contenant user_id, ou None."""
    queue = queues.get(guild_id)
    if not queue:
        return None

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
# !sq 2v2 / 3v3 / 4v4 / 5v5 / 6v6
# ============================================================

@bot.command()
@commands.guild_only()
async def sq(ctx, format_: str = None):
    """Ouvre une SQ."""
    if not is_sq_admin(ctx.author):
        await ctx.send("❌ You need to be an administrator to open SQ.")
        return

    if not format_:
        await ctx.send("❌ Usage: `!sq 2v2`, `!sq 3v3`, `!sq 4v4`, `!sq 5v5` or `!sq 6v6`.")
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
        await ctx.send("❌ Invalid format. Use `2v2`, `3v3`, `4v4`, `5v5` ou `6v6`.")
        return

    guild_id = ctx.guild.id

    if guild_id in queues:
        old_size = queues[guild_id]["size"]
        await ctx.send(
            f"❌ A SQ **{format_name(old_size)}** is already opened. "
            f"Use `!sqclose` to close it before opening another."
        )
        return

    size = allowed[format_clean]

    queues[guild_id] = {
        "size": size,
        "teams": [],
        "pending": {}
    }

    embed = discord.Embed(
        title=f"🎮 SQ {format_clean} opened!",
        description=(
            f"Format : **{format_clean}**\n\n"
            f"👥 Each team has **{size} players**.\n"
            f"📨 To invite a teammate : `!c @player`\n"
            f"✅ If someone has invited you, type `!c` to confirm.\n"
            f"🚪 To leave a team : `!d`\n"
            f"📋 To see all teams : `!sqlist`"
        )
    )

    await ctx.send(embed=embed)


# ============================================================
# !c @joueur
# ============================================================

@bot.command()
@commands.guild_only()
async def c(ctx, members: commands.Greedy[discord.Member]):
    """
    Deux usages :
    !c @joueur -> proposer ce joueur comme mate
    !c         -> confirmer une proposition reçue
    """
    queue = get_queue(ctx.guild.id)

    if not queue:
        await ctx.send("❌ No SQ is open/available.")
        return

    size = queue["size"]
    author_id = ctx.author.id

    # --------------------------------------------------------
    # !c = confirmer une proposition reçue
    # --------------------------------------------------------
    if member is None:
        proposer_id = queue["pending"].get(author_id)

        if proposer_id is None:
            await ctx.send(
                "❌ You don't have any pending team requests. "
                "To invite someone else, use `!c @player`."
            )
            return

        proposer = ctx.guild.get_member(proposer_id)

        if find_team(ctx.guild.id, author_id):
            queue["pending"].pop(author_id, None)
            await ctx.send("❌ You are already in a team.")
            return

        if find_team(ctx.guild.id, proposer_id):
            queue["pending"].pop(author_id, None)
            await ctx.send("❌ The player you specified is already in a team.")
            return

        # Création de l'équipe à partir du proposant et du joueur qui confirme.
        team = frozenset({proposer_id, author_id})
        queue["teams"].append(team)
        queue["pending"].pop(author_id, None)

        await ctx.send(
            f"✅ {ctx.author.mention} has accepted the invite of "
            f"{proposer.mention if proposer else f'<@{proposer_id}>'}.\n"
            f"👥 Team created : {team_label(team, ctx.guild)} "
            f"(**{len(team)}/{size}**)."
        )

        if len(team) == size:
            await ctx.send(
                f"🔥 **Team full!**\n"
                f"{team_label(team, ctx.guild)}"
            )

        return

    # --------------------------------------------------------
    # !c @joueur = proposer un mate
    # --------------------------------------------------------

    if member.bot:
        await ctx.send("❌ You cannot invite a bot.")
        return

    if member.id == author_id:
        await ctx.send("❌ You cannot invite yourself.")
        return

    author_team = find_team(ctx.guild.id, author_id)
    target_team = find_team(ctx.guild.id, member.id)

    if author_team:
        if member.id in author_team:
            await ctx.send("❌ This player is in your team.")
            return

        if len(author_team) >= size:
            await ctx.send(
                f"❌ Your team is full ({size}/{size}). "
                f"If you want to leave, use `!d`."
            )
            return

        # Une proposition ne peut pas être faite à quelqu'un déjà dans une autre équipe.
        if target_team:
            await ctx.send("❌ This player is already in another team.")
            return

        # Une proposition en attente pour cette personne existe déjà.
        if member.id in queue["pending"]:
            await ctx.send("❌ This player already has a pending invite.")
            return

        queue["pending"][member.id] = author_id

        await ctx.send(
            f"📨 {member.mention}, {ctx.author.mention} has invited you to join their team.\n"
            f"👉 Use `!c` to **accept**."
        )
        return

    # Si le joueur n'a pas encore d'équipe, il peut proposer un joueur.
    if target_team:
        await ctx.send("❌ This player is already in a team.")
        return

    if member.id in queue["pending"]:
        await ctx.send("❌ This player already has a pending invite.")
        return

    # Un joueur seul peut faire plusieurs propositions, mais une seule
    # confirmation de chaque côté permet de créer une équipe.
    queue["pending"][member.id] = author_id

    await ctx.send(
        f"📨 {member.mention}, {ctx.author.mention} has invited you to join their team.\n"
        f"👉 Use `!c` to **accept**."
    )


# ============================================================
# !d = quitter son équipe
# ============================================================

@bot.command()
@commands.guild_only()
async def d(ctx):
    queue = get_queue(ctx.guild.id)

    if not queue:
        await ctx.send("❌ No SQ is open/available.")
        return

    user_id = ctx.author.id

    # Si le joueur avait seulement une proposition reçue en attente,
    # !d l'annule également.
    if user_id in queue["pending"]:
        queue["pending"].pop(user_id, None)
        await ctx.send("✅ The invite has been declined.")
        return

    team = find_team(ctx.guild.id, user_id)

    if not team:
        await ctx.send("❌ You are not in a team.")
        return

    old_members = list(team)

    queue["teams"].remove(team)

    # Les autres joueurs de l'équipe sont remis en attente comme groupe
    # individuel : ils pourront reformer une équipe.
    for other_id in old_members:
        if other_id == user_id:
            continue

    await ctx.send(
        f"🚪 {ctx.author.mention} has left their team.\n"
        f"📋 The others are availble to form a team."
    )


# ============================================================
# !sqlist = voir les équipes
# ============================================================

@bot.command()
@commands.guild_only()
async def sqlist(ctx):
    queue = get_queue(ctx.guild.id)

    if not queue:
        await ctx.send("❌ No SQ is open/available.")
        return

    size = queue["size"]

    embed = discord.Embed(
        title=f"📋 SQ {format_name(size)}",
        description=build_status(ctx.guild, queue)
    )

    pending = queue["pending"]

    if pending:
        mentions = []
        for target_id, proposer_id in pending.items():
            mentions.append(f"<@{target_id}> ← <@{proposer_id}>")
        embed.add_field(
            name="📨 Pending invitations",
            value="\n".join(mentions),
            inline=False
        )

    await ctx.send(embed=embed)


# ============================================================
# !sqclose = fermer la SQ
# ============================================================

@bot.command()
@commands.guild_only()
async def sqclose(ctx):
    if not is_sq_admin(ctx.author):
        await ctx.send("❌ You must be an administrator to close a SQ.")
        return

    queue = get_queue(ctx.guild.id)

    if not queue:
        await ctx.send("❌ No SQ is open.")
        return

    size = queue["size"]
    del queues[ctx.guild.id]

    await ctx.send(f"🛑 SQ **{format_name(size)}** has been closed.")


# ============================================================
# !sqhelp
# ============================================================

@bot.command()
@commands.guild_only()
async def sqhelp(ctx):
    embed = discord.Embed(
        title="📖 Commandes SQ",
        description=(
            "`!sq 2v2` — opens a SQ 2v2 (admin)\n"
            "`!sq 3v3` — opens a SQ 3v3 (admin)\n"
            "`!sq 4v4` — opens a SQ 4v4 (admin)\n"
            "`!sq 5v5` — opens a SQ 5v5 (admin)\n"
            "`!sq 6v6` — opens a SQ 6v6 (admin)\n\n"
            "`!c @joueur` — invites a player\n"
            "`!c` — accept a pending invite\n"
            "`!d` — leave your team\n"
            "`!sqlist` — see all teams\n"
            "`!sqclose` — close a SQ (admin)"
        )
    )
    await ctx.send(embed=embed)


# ============================================================
# ERREURS
# ============================================================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Player not found. Use a member mention/ping, ie. `!c @player`.")
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Missing arguments. Use `!sqhelp` to see all commandss.")
        return

    if isinstance(error, commands.CommandNotFound):
        return

    print(f"Error: {error}")


# ============================================================
# LANCEMENT
# ============================================================

if TOKEN == "MET_TON_TOKEN_ICI":
    print("⚠️ Do not forget to input your token.")

bot.run(TOKEN)
