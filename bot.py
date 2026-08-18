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
        return "Aucune équipe confirmée pour le moment."

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
    print(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")
    print("Bot SQ prêt.")


# ============================================================
# !sq 2v2 / 3v3 / 4v4 / 5v5 / 6v6
# ============================================================

@bot.command()
@commands.guild_only()
async def sq(ctx, format_: str = None):
    """Ouvre une SQ."""
    if not is_sq_admin(ctx.author):
        await ctx.send("❌ Tu dois être administrateur pour ouvrir une SQ.")
        return

    if not format_:
        await ctx.send("❌ Utilisation : `!sq 2v2`, `!sq 3v3`, `!sq 4v4`, `!sq 5v5` ou `!sq 6v6`.")
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
        await ctx.send("❌ Format invalide. Utilise `2v2`, `3v3`, `4v4`, `5v5` ou `6v6`.")
        return

    guild_id = ctx.guild.id

    if guild_id in queues:
        old_size = queues[guild_id]["size"]
        await ctx.send(
            f"❌ Une SQ **{format_name(old_size)}** est déjà ouverte. "
            f"Utilise `!sqclose` pour la fermer avant d'en ouvrir une autre."
        )
        return

    size = allowed[format_clean]

    queues[guild_id] = {
        "size": size,
        "teams": [],
        "pending": {}
    }

    embed = discord.Embed(
        title=f"🎮 SQ {format_clean} ouverte !",
        description=(
            f"Format : **{format_clean}**\n\n"
            f"👥 Une équipe contient **{size} joueurs**.\n"
            f"📨 Pour proposer un mate : `!c @joueur`\n"
            f"✅ Si quelqu'un te propose comme mate, fais `!c` pour confirmer.\n"
            f"🚪 Pour quitter ton équipe : `!d`\n"
            f"📋 Pour voir les équipes : `!sqlist`"
        )
    )

    await ctx.send(embed=embed)


# ============================================================
# !c @joueur
# ============================================================

@bot.command()
@commands.guild_only()
async def c(ctx, member: discord.Member = None):
    """
    Deux usages :
    !c @joueur -> proposer ce joueur comme mate
    !c         -> confirmer une proposition reçue
    """
    queue = get_queue(ctx.guild.id)

    if not queue:
        await ctx.send("❌ Aucune SQ n'est actuellement ouverte.")
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
                "❌ Tu n'as aucune proposition en attente. "
                "Pour proposer quelqu'un, utilise `!c @joueur`."
            )
            return

        proposer = ctx.guild.get_member(proposer_id)

        if find_team(ctx.guild.id, author_id):
            queue["pending"].pop(author_id, None)
            await ctx.send("❌ Tu es déjà dans une équipe.")
            return

        if find_team(ctx.guild.id, proposer_id):
            queue["pending"].pop(author_id, None)
            await ctx.send("❌ Le joueur qui t'a proposé est déjà dans une équipe.")
            return

        # Création de l'équipe à partir du proposant et du joueur qui confirme.
        team = frozenset({proposer_id, author_id})
        queue["teams"].append(team)
        queue["pending"].pop(author_id, None)

        await ctx.send(
            f"✅ {ctx.author.mention}, tu as confirmé la proposition de "
            f"{proposer.mention if proposer else f'<@{proposer_id}>'}.\n"
            f"👥 Équipe créée : {team_label(team, ctx.guild)} "
            f"(**{len(team)}/{size}**)."
        )

        if len(team) == size:
            await ctx.send(
                f"🔥 **Équipe complète !**\n"
                f"{team_label(team, ctx.guild)}"
            )

        return

    # --------------------------------------------------------
    # !c @joueur = proposer un mate
    # --------------------------------------------------------

    if member.bot:
        await ctx.send("❌ Tu ne peux pas choisir un bot.")
        return

    if member.id == author_id:
        await ctx.send("❌ Tu ne peux pas te choisir toi-même.")
        return

    author_team = find_team(ctx.guild.id, author_id)
    target_team = find_team(ctx.guild.id, member.id)

    if author_team:
        if member.id in author_team:
            await ctx.send("❌ Ce joueur est déjà dans ton équipe.")
            return

        if len(author_team) >= size:
            await ctx.send(
                f"❌ Ton équipe est déjà complète ({size}/{size}). "
                f"Si tu veux partir, utilise `!d`."
            )
            return

        # Une proposition ne peut pas être faite à quelqu'un déjà dans une autre équipe.
        if target_team:
            await ctx.send("❌ Ce joueur est déjà dans une autre équipe.")
            return

        # Une proposition en attente pour cette personne existe déjà.
        if member.id in queue["pending"]:
            await ctx.send("❌ Ce joueur a déjà une proposition en attente.")
            return

        queue["pending"][member.id] = author_id

        await ctx.send(
            f"📨 {member.mention}, {ctx.author.mention} te propose comme mate.\n"
            f"👉 Fais `!c` pour **confirmer**."
        )
        return

    # Si le joueur n'a pas encore d'équipe, il peut proposer un joueur.
    if target_team:
        await ctx.send("❌ Ce joueur est déjà dans une autre équipe.")
        return

    if member.id in queue["pending"]:
        await ctx.send("❌ Ce joueur a déjà une proposition en attente.")
        return

    # Un joueur seul peut faire plusieurs propositions, mais une seule
    # confirmation de chaque côté permet de créer une équipe.
    queue["pending"][member.id] = author_id

    await ctx.send(
        f"📨 {member.mention}, {ctx.author.mention} te propose comme mate.\n"
        f"👉 Fais `!c` pour **confirmer**."
    )


# ============================================================
# !d = quitter son équipe
# ============================================================

@bot.command()
@commands.guild_only()
async def d(ctx):
    queue = get_queue(ctx.guild.id)

    if not queue:
        await ctx.send("❌ Aucune SQ n'est actuellement ouverte.")
        return

    user_id = ctx.author.id

    # Si le joueur avait seulement une proposition reçue en attente,
    # !d l'annule également.
    if user_id in queue["pending"]:
        queue["pending"].pop(user_id, None)
        await ctx.send("✅ Ta proposition en attente a été annulée.")
        return

    team = find_team(ctx.guild.id, user_id)

    if not team:
        await ctx.send("❌ Tu n'es dans aucune équipe.")
        return

    old_members = list(team)

    queue["teams"].remove(team)

    # Les autres joueurs de l'équipe sont remis en attente comme groupe
    # individuel : ils pourront reformer une équipe.
    for other_id in old_members:
        if other_id == user_id:
            continue

    await ctx.send(
        f"🚪 {ctx.author.mention} a quitté son équipe.\n"
        f"📋 Les autres joueurs restent disponibles pour reformer une équipe."
    )


# ============================================================
# !sqlist = voir les équipes
# ============================================================

@bot.command()
@commands.guild_only()
async def sqlist(ctx):
    queue = get_queue(ctx.guild.id)

    if not queue:
        await ctx.send("❌ Aucune SQ n'est actuellement ouverte.")
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
            name="📨 Propositions en attente",
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
        await ctx.send("❌ Tu dois être administrateur pour fermer la SQ.")
        return

    queue = get_queue(ctx.guild.id)

    if not queue:
        await ctx.send("❌ Aucune SQ n'est ouverte.")
        return

    size = queue["size"]
    del queues[ctx.guild.id]

    await ctx.send(f"🛑 SQ **{format_name(size)}** fermée et réinitialisée.")


# ============================================================
# !sqhelp
# ============================================================

@bot.command()
@commands.guild_only()
async def sqhelp(ctx):
    embed = discord.Embed(
        title="📖 Commandes SQ",
        description=(
            "`!sq 2v2` — ouvre une SQ 2v2 (admin)\n"
            "`!sq 3v3` — ouvre une SQ 3v3 (admin)\n"
            "`!sq 4v4` — ouvre une SQ 4v4 (admin)\n"
            "`!sq 5v5` — ouvre une SQ 5v5 (admin)\n"
            "`!sq 6v6` — ouvre une SQ 6v6 (admin)\n\n"
            "`!c @joueur` — proposer un mate\n"
            "`!c` — confirmer une proposition reçue\n"
            "`!d` — quitter son équipe\n"
            "`!sqlist` — voir les équipes\n"
            "`!sqclose` — fermer/reset la SQ (admin)"
        )
    )
    await ctx.send(embed=embed)


# ============================================================
# ERREURS
# ============================================================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Joueur introuvable. Utilise une mention comme `!c @Joueur`.")
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Argument manquant. Utilise `!sqhelp` pour voir les commandes.")
        return

    if isinstance(error, commands.CommandNotFound):
        return

    print(f"Erreur: {error}")


# ============================================================
# LANCEMENT
# ============================================================

if TOKEN == "MET_TON_TOKEN_ICI":
    print("⚠️ N'oublie pas de mettre le token de ton bot dans TOKEN.")
