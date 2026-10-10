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

        target_team = find_team_in_queue(queue, member.id)

        if author_team and member.id in author_team:
            await ctx.send(f"❌ {member.mention} is already in your team.")
            continue

        if target_team:
            await ctx.send(f"❌ {member.mention} is already in another team in this SQ.")
            continue

        if member.id in queue["pending"]:
            await ctx.send(f"❌ {member.mention} already has a pending invite in this SQ.")
            continue

        queue["pending"][member.id] = {
            "proposer_id": author_id,
            "team": author_team
        }
        invited_mentions.append(member.mention)

    if invited_mentions:
        plist = ", ".join(invited_mentions)
        await ctx.send(
            f"📨 {plist}, {ctx.author.mention} invited you to join their team in **{queue['name']}**.\n"
            f"👉 Use `!c` to **accept**."
        )


@bot.command()
@commands.guild_only()
async def c(ctx, *args):
    """
    Usages:
    !c -> Accept a pending invite
    !c @player1 @player2... -> Invite player(s) (if 1 active SQ)
    !c <sq_name> @player1 @player2... -> Invite player(s) to a specific SQ
    """
    guild_id = ctx.guild.id
    server_queues = get_server_queues(guild_id)

    if not server_queues:
        await ctx.send("❌ No SQs are open/available.")
        return

    # Case 1: !c (Accept pending invite)
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

    # Case 2: Parse args to separate SQ identifier and target member pings
    members = []
    sq_key = None
    converter = commands.MemberConverter()

    for arg in args:
        try:
            m = await converter.convert(ctx, arg)
            if m:
                members.append(m)
                continue
        except Exception:
            pass

        # If it's not a valid member mention/ID, assume it's the SQ name
        if sq_key is None and not members:
            sq_key = arg.lower()

    if not members:
        await ctx.send("❌ Player not found. Usage: `!c @player1 @player2` or `!c <sq_name> @player1 @player2`.")
        return

    target_queue = None
    if sq_key:
        if sq_key in server_queues:
            target_queue = server_queues[sq_key]
        else:
            await ctx.send(f"❌ No SQ named `{sq_key}` found.")
            return
    else:
        # Detect active SQ for author or default to single open SQ
        author_sqs = []
        for s_key, queue in server_queues.items():
            if find_team_in_queue(queue, ctx.author.id):
                author_sqs.append((s_key, queue))

        if len(author_sqs) == 1:
            target_queue = author_sqs[0][1]
        elif len(author_sqs) > 1:
            names = ", ".join([q["name"] for _, q in author_sqs])
            await ctx.send(f"❌ You are in multiple SQs ({names}). Specify name: `!c <sq_name> @player1 @player2`.")
            return
        else:
            if len(server_queues) == 1:
                target_queue = list(server_queues.values())[0]
            else:
                names = ", ".join([q["name"] for q in server_queues.values()])
                await ctx.send(f"❌ Multiple SQs open ({names}). Specify name: `!c <sq_name> @player1 @player2`.")
                return

    await handle_invites(ctx, target_queue, members)


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
            "`!c @p1 @p2` — invites players\n"
            "`!c <name> @p1 @p2` — invites players to a specific SQ\n"
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
        await ctx.send("❌ Player not found. Use member mentions/pings.")
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
