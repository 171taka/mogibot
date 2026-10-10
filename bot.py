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
            f"📨 To invite : `!c @player` or `!c {name.strip()} @player`\n"
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


async def handle_invite(ctx, queue, member):
    size = queue["size"]
    author_id = ctx.author.id

    if member.bot:
        await ctx.send("❌ You cannot invite a bot.")
        return

    if member.id == author_id:
        await ctx.send("❌ You cannot invite yourself.")
        return

    author_team = find_team_in_queue(queue, author_id)
    target_team = find_team_in_queue(queue, member.id)

    if author_team:
        if member.id in author_team:
            await ctx.send("❌ This player is already in your team.")
            return

        if len(author_team) >= size:
            await ctx.send(f"❌ Your team is full ({size}/{size}).")
            return

    if target_team:
        if target_team == author_team:
            await ctx.send("❌ This player is already in your team.")
            return
        await ctx.send("❌ This player is already in another team in this SQ.")
        return

    if member.id in queue["pending"]:
        await ctx.send("❌ This player already has a pending invite in this SQ.")
        return

    queue["pending"][member.id] = {
        "proposer_id": author_id,
        "team": author_team
    }

    await ctx.send(
        f"📨 {member.mention}, {ctx.author.mention} invited you to join their team in **{queue['name']}**.\n"
        f"👉 Use `!c` to **accept**."
    )


@bot.command()
@commands.guild_only()
async def c(ctx, *args):
    """
    Usages:
    !c -> Accepter une invitation en attente
    !c @joueur -> Inviter un joueur (si 1 SQ active)
    !c <sq_name> @joueur -> Inviter un joueur dans une SQ spécifique
    """
    guild_id = ctx.guild.id
    server_queues = get_server_queues(guild_id)

    if not server_queues:
        await ctx.send("❌ No SQs are open/available.")
        return

    # Cas 1: !c (Confirmer une invitation)
    if not args:
        user_pendings = []
        for sq_key, queue in server_queues.items():
            if ctx.author.id in queue["pending"]:
                user_pendings.append((sq_key, queue))

        if not user_pendings:
            await ctx.send("❌ You don't have any pending team requests.")
            return

        if len(user_pendings) > 1:
            names = ", ".join([q["name"] for _, q in user_pendings])
            await ctx.send(f"❌ Pending invites in multiple SQs ({names}). Please specify name: `!c <sq_name>`.")
            return

        await handle_accept(ctx, user_pendings[0][1])
        return

    # Cas 2: Analyse des arguments pour trouver le membre et l'éventuel nom de SQ
    member = None
    sq_key = None

    for arg in args:
        try:
            converter = commands.MemberConverter()
            m = await converter.convert(ctx, arg)
            if m:
                member = m
                continue
        except Exception:
            pass
        sq_key = arg.lower()

    if not member:
        await ctx.send("❌ Player not found. Usage: `!c @player` or `!c <sq_name> @player`.")
        return

    target_queue = None
    if sq_key:
        if sq_key in server_queues:
            target_queue = server_queues[sq_key]
        else:
            await ctx.send(f"❌ No SQ named `{sq_key}` found.")
            return
    else:
        # Trouver la SQ de l'auteur ou utiliser l'unique SQ ouverte
        author_sqs = []
        for s_key, queue in server_queues.items():
            if find_team_in_queue(queue, ctx.author.id):
                author_sqs.append((s_key, queue))

        if len(author_sqs) == 1:
            target_queue = author_sqs[0][1]
        elif len(author_sqs) > 1:
            names = ", ".join([q["name"] for _, q in author_sqs])
            await ctx.send(f"❌ You are in multiple SQs ({names}). Please specify the name: `!c <sq_name> @player`.")
            return
        else:
            if len(server_queues) == 1:
                target_queue = list(server_queues.values())[0]
            else:
                names = ", ".join([q["name"] for q in server_queues.values()])
                await ctx.send(f"❌ Multiple SQs are open ({names}). Please specify the name: `!c <sq_name> @player`.")
                return

    await handle_invite(ctx, target_queue, member)


# ============================================================
# !d = quitter son équipe
# ============================================================

@bot.command()
@commands.guild_only()
async def d(ctx, name: str = None):
    guild_id = ctx.guild.id
    server_queues = get_server_queues(guild_id)

    if not server_queues:
        await ctx.send("❌ No SQs are open/available.")
        return

    target_queue = None
    user_id = ctx.author.id

    if name:
        sq_key = name.lower()
        if sq_key in server_queues:
            target_queue = server_queues[sq_key]
        else:
            await ctx.send(f"❌ No SQ named `{name}` found.")
            return
    else:
        matches = []
        for q_key, queue in server_queues.items():
            if user_id in queue["pending"] or find_team_in_queue(queue, user_id):
                matches.append(queue)

        if len(matches) == 1:
            target_queue = matches[0]
        elif len(matches) > 1:
            names = ", ".join([q["name"] for q in matches])
            await ctx.send(f"❌ Active in multiple SQs ({names}). Specify name: `!d <sq_name>`.")
            return
        else:
            await ctx.send("❌ You are not in any team or pending invite.")
            return

    if user_id in target_queue["pending"]:
        target_queue["pending"].pop(user_id, None)
        await ctx.send(f"✅ The invite in **{target_queue['name']}** has been declined.")
        return

    team = find_team_in_queue(target_queue, user_id)
    if not team:
        await ctx.send("❌ You are not in a team.")
        return

    team.remove(user_id)
    if len(team) == 0:
        target_queue["teams"].remove(team)

    await ctx.send(f"🚪 {ctx.author.mention} has left their team in **{target_queue['name']}**.")


# ============================================================
# !sqlist = voir les équipes
# ============================================================

@bot.command()
@commands.guild_only()
async def sqlist(ctx, name: str = None):
    guild_id = ctx.guild.id
    server_queues = get_server_queues(guild_id)

    if not server_queues:
        await ctx.send("❌ No SQs are open/available.")
        return

    if name:
        sq_key = name.lower()
        if sq_key not in server_queues:
            await ctx.send(f"❌ No SQ named `{name}` found.")
            return
        queues_to_show = [server_queues[sq_key]]
    else:
        queues_to_show = list(server_queues.values())

    for queue in queues_to_show:
        size = queue["size"]
        embed = discord.Embed(
            title=f"📋 SQ '{queue['name']}' ({format_name(size)})",
            description=build_status(ctx.guild, queue)
        )

        pending = queue["pending"]
        if pending:
            mentions = []
            for target_id, data in pending.items():
                proposer_id = data["proposer_id"]
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
async def sqclose(ctx, name: str = None):
    if not is_sq_admin(ctx.author):
        await ctx.send("❌ You must be an administrator to close a SQ.")
        return

    guild_id = ctx.guild.id
    server_queues = get_server_queues(guild_id)

    if not server_queues:
        await ctx.send("❌ No SQs are open.")
        return

    if name:
        sq_key = name.lower()
        if sq_key not in server_queues:
            await ctx.send(f"❌ No SQ named `{name}` found.")
            return
        queue = server_queues.pop(sq_key)
        if not server_queues:
            del queues[guild_id]
        await ctx.send(f"🛑 SQ **{queue['name']}** ({format_name(queue['size'])}) has been closed.")
    else:
        if len(server_queues) == 1:
            sq_key = list(server_queues.keys())[0]
            queue = server_queues.pop(sq_key)
            del queues[guild_id]
            await ctx.send(f"🛑 SQ **{queue['name']}** ({format_name(queue['size'])}) has been closed.")
        else:
            names = ", ".join([q["name"] for q in server_queues.values()])
            await ctx.send(f"❌ Multiple SQs are open ({names}). Please specify the name: `!sqclose <name>`.")


# ============================================================
# !sqhelp
# ============================================================

@bot.command()
@commands.guild_only()
async def sqhelp(ctx):
    embed = discord.Embed(
        title="📖 Commandes SQ",
        description=(
            "`!sq <format> <name>` — opens a named SQ (admin, e.g. `!sq 3v3 RR`)\n\n"
            "`!c @player` — invites a player\n"
            "`!c <name> @player` — invites a player to a specific SQ\n"
            "`!c` — accept a pending invite\n"
            "`!d` — leave your team\n"
            "`!sqlist [name]` — see teams (all or specific SQ)\n"
            "`!sqclose <name>` — close a specific SQ (admin)"
        )
    )
    await ctx.send(embed=embed)


# ============================================================
# ERREURS
# ============================================================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Player not found. Use a member mention/ping.")
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Missing arguments. Use `!sqhelp` to see all commands.")
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
