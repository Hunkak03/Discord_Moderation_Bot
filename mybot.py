# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────

import discord
from discord.ext import commands
from discord import app_commands
from groq import Groq
import asyncio
import logging
import time
import sqlite3
import json
import re
from datetime import datetime, timezone
from dotenv import load_dotenv
import os

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY  = os.getenv("GROQ_API_KEY")

if not DISCORD_TOKEN or not GROQ_API_KEY:
    raise ValueError("❌ Faltan variables de entorno. Revisa tu archivo .env")

ROLE_HEAD_STAFF  = 1485050306751631512
ROLE_PROPIETARIO = 1484011451936145571
ROLE_ADMIN       = 1388949033082683402
ROLE_MODERADOR   = 1396472162113552464
ROLE_STAFF       = 1484223094569828452
STAFF_ROLES      = {ROLE_HEAD_STAFF, ROLE_PROPIETARIO, ROLE_ADMIN, ROLE_MODERADOR, ROLE_STAFF}

CANAL_LOGS       = 1484665486544212140
CANAL_BIENVENIDA = 1388948752122904708
CANAL_TICKETS    = 1484665704925102081

MAX_REPORTES  = 5
SPAM_MENSAJES = 5
SPAM_SEGUNDOS = 5
MUTE_DURACION = 10

# Palabras prohibidas (filtro de contenido)
PALABRAS_PROHIBIDAS = [
    "nigger", "nigga", "faggot", "retard", "kys", "kill yourself",
    "mátate", "suicídate", "puta madre", "hijo de puta"
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

client_groq = Groq(api_key=GROQ_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
intents.members          = True
intents.presences        = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")

# ─────────────────────────────────────────────
# BASE DE DATOS SQLite (PERSISTENCIA)
# ─────────────────────────────────────────────

def init_db():
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS warns (
            user_id    INTEGER PRIMARY KEY,
            count      INTEGER DEFAULT 0,
            monitored  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS mod_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id   INTEGER,
            target_id  INTEGER,
            mod_id     INTEGER,
            action     TEXT,
            reason     TEXT,
            timestamp  REAL
        );

        CREATE TABLE IF NOT EXISTS reports (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            reported_id INTEGER,
            reporter_id INTEGER,
            reason      TEXT,
            timestamp   REAL
        );

        CREATE TABLE IF NOT EXISTS tickets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id  INTEGER UNIQUE,
            user_id     INTEGER,
            guild_id    INTEGER,
            status      TEXT DEFAULT 'open',
            created_at  REAL
        );

        CREATE TABLE IF NOT EXISTS tempbans (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            guild_id    INTEGER,
            unban_at    REAL,
            reason      TEXT
        );
    """)
    con.commit()
    con.close()

init_db()

# ─────────────────────────────────────────────
# HELPERS DE BASE DE DATOS
# ─────────────────────────────────────────────

def db_get_warns(user_id: int) -> tuple[int, bool]:
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.execute("SELECT count, monitored FROM warns WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    if row:
        return row[0], bool(row[1])
    return 0, False

def db_set_warns(user_id: int, count: int, monitored: bool):
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.execute(
        "INSERT INTO warns (user_id, count, monitored) VALUES (?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET count=excluded.count, monitored=excluded.monitored",
        (user_id, count, int(monitored))
    )
    con.commit()
    con.close()

def db_delete_warns(user_id: int):
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.execute("DELETE FROM warns WHERE user_id=?", (user_id,))
    con.commit()
    con.close()

def db_add_mod_action(guild_id, target_id, mod_id, action, reason):
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.execute(
        "INSERT INTO mod_history (guild_id, target_id, mod_id, action, reason, timestamp) VALUES (?,?,?,?,?,?)",
        (guild_id, target_id, mod_id, action, reason, time.time())
    )
    con.commit()
    con.close()

def db_get_mod_history(target_id: int) -> list[dict]:
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.execute(
        "SELECT action, reason, mod_id, timestamp FROM mod_history WHERE target_id=? ORDER BY timestamp DESC LIMIT 20",
        (target_id,)
    )
    rows = cur.fetchall()
    con.close()
    return [{"action": r[0], "reason": r[1], "mod_id": r[2], "ts": r[3]} for r in rows]

def db_add_report(reported_id, reporter_id, reason) -> int:
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.execute(
        "INSERT INTO reports (reported_id, reporter_id, reason, timestamp) VALUES (?,?,?,?)",
        (reported_id, reporter_id, reason, time.time())
    )
    con.commit()
    cur.execute("SELECT COUNT(*) FROM reports WHERE reported_id=?", (reported_id,))
    total = cur.fetchone()[0]
    con.close()
    return total

def db_get_reports(reported_id: int) -> list[dict]:
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.execute(
        "SELECT reporter_id, reason, timestamp FROM reports WHERE reported_id=? ORDER BY timestamp DESC",
        (reported_id,)
    )
    rows = cur.fetchall()
    con.close()
    return [{"reporter_id": r[0], "reason": r[1], "ts": r[2]} for r in rows]

def db_already_reported(reported_id, reporter_id) -> bool:
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.execute(
        "SELECT 1 FROM reports WHERE reported_id=? AND reporter_id=?",
        (reported_id, reporter_id)
    )
    result = cur.fetchone() is not None
    con.close()
    return result

def db_create_ticket(channel_id, user_id, guild_id):
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.execute(
        "INSERT INTO tickets (channel_id, user_id, guild_id, created_at) VALUES (?,?,?,?)",
        (channel_id, user_id, guild_id, time.time())
    )
    con.commit()
    con.close()

def db_close_ticket(channel_id):
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.execute("UPDATE tickets SET status='closed' WHERE channel_id=?", (channel_id,))
    con.commit()
    con.close()

def db_get_ticket(channel_id) -> dict | None:
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.execute(
        "SELECT user_id, guild_id, status, created_at FROM tickets WHERE channel_id=?",
        (channel_id,)
    )
    row = cur.fetchone()
    con.close()
    if row:
        return {"user_id": row[0], "guild_id": row[1], "status": row[2], "created_at": row[3]}
    return None

def db_user_has_open_ticket(user_id, guild_id) -> bool:
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.execute(
        "SELECT 1 FROM tickets WHERE user_id=? AND guild_id=? AND status='open'",
        (user_id, guild_id)
    )
    result = cur.fetchone() is not None
    con.close()
    return result

def db_add_tempban(user_id: int, guild_id: int, unban_at: float, reason: str):
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.execute(
        "INSERT INTO tempbans (user_id, guild_id, unban_at, reason) VALUES (?,?,?,?)",
        (user_id, guild_id, unban_at, reason)
    )
    con.commit()
    con.close()

def db_remove_tempban(user_id: int, guild_id: int):
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.execute("DELETE FROM tempbans WHERE user_id=? AND guild_id=?", (user_id, guild_id))
    con.commit()
    con.close()

def db_get_pending_tempbans() -> list[dict]:
    con = sqlite3.connect("jin_sakai.db")
    cur = con.cursor()
    cur.execute("SELECT user_id, guild_id, unban_at, reason FROM tempbans WHERE unban_at <= ?", (time.time(),))
    rows = cur.fetchall()
    con.close()
    return [{"user_id": r[0], "guild_id": r[1], "unban_at": r[2], "reason": r[3]} for r in rows]

# ─────────────────────────────────────────────
# ESTADO EN MEMORIA (TEMPORAL)
# ─────────────────────────────────────────────
spam_tracker:        dict[int, list[float]] = {}
spam_notified:       set[int]               = set()
report_notified:     set[int]               = set()
pending_staff_alert: dict[int, int]         = {}
anti_raid_tracker:   list[float]            = []
raid_mode:           bool                   = False

ANTI_RAID_JOINS    = 8
ANTI_RAID_SEGUNDOS = 10

# ─────────────────────────────────────────────
# ALIAS MULTILINGÜE
# ─────────────────────────────────────────────
COMMAND_ALIASES: dict[str, str] = {
    "ping": "ping", "info": "info",
    "help": "help", "ayuda": "help", "aide": "help", "hilfe": "help", "ajuda": "help",
    "kick": "kick", "expulsar": "kick", "expulser": "kick", "rauswerfen": "kick", "expelir": "kick",
    "ban": "ban", "banear": "ban", "bannir": "ban", "verbannen": "ban", "banir": "ban",
    "mute": "mute", "mutear": "mute", "silenciar": "mute", "stummschalten": "mute",
    "unmute": "unmute", "desmutear": "unmute", "dessilenciar": "unmute", "unmuten": "unmute",
    "dar_role": "dar_role", "give_role": "dar_role", "donner_role": "dar_role", "dar_cargo": "dar_role",
    "quitar_role": "quitar_role", "remove_role": "quitar_role", "retirer_role": "quitar_role",
    "activar_avisos": "activar_avisos", "enable_warnings": "activar_avisos",
    "desactivar_avisos": "desactivar_avisos", "disable_warnings": "desactivar_avisos",
    "ver_avisos": "ver_avisos", "check_warnings": "ver_avisos",
    "contactar": "contactar", "contact": "contactar", "contacter": "contactar",
    "reportar": "reportar", "report": "reportar", "signaler": "reportar", "melden": "reportar",
    "comandos": "comandos", "commands": "comandos", "cmds": "comandos",
    "clear": "clear", "limpiar": "clear", "purge": "clear", "purger": "clear", "bereinigen": "clear",
    "warn": "warn", "avisar": "warn", "advertir": "warn",
    "historial": "historial", "history": "historial", "verlauf": "historial",
    "userinfo": "userinfo", "perfil": "userinfo", "whois": "userinfo",
    "serverinfo": "serverinfo", "servidor": "serverinfo",
    "ticket": "ticket",
    "cerrar_ticket": "cerrar_ticket", "close_ticket": "cerrar_ticket",
    "tempban": "tempban", "banear_temp": "tempban",
    "poll": "poll", "encuesta": "poll", "sondage": "poll",
    "unlock": "unlock", "desbloquear": "unlock",
    "lockdown": "lockdown", "bloquear": "lockdown",
    "avatar": "avatar", "pfp": "avatar",
    "unban": "unban", "desbanear": "unban", "débannir": "unban",
}

# ─────────────────────────────────────────────
# UTILIDADES MULTILINGÜE
# ─────────────────────────────────────────────

async def traducir_mensaje(texto: str, idioma_destino: str) -> str:
    try:
        result = await asyncio.to_thread(
            client_groq.chat.completions.create,
            model="llama-3.3-70b-versatile",
            max_tokens=300,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Translate the following text to {idioma_destino}. "
                        "Return ONLY the translated text. "
                        "Keep Discord mentions, markdown and emojis exactly as they are."
                    ),
                },
                {"role": "user", "content": texto},
            ],
        )
        return result.choices[0].message.content.strip()
    except Exception as e:
        log.warning(f"Error traduciendo: {e}")
        return texto


async def detectar_idioma(texto: str) -> str:
    try:
        result = await asyncio.to_thread(
            client_groq.chat.completions.create,
            model="llama-3.3-70b-versatile",
            max_tokens=10,
            messages=[
                {
                    "role": "system",
                    "content": "Detect the language of the text. Reply with ONLY the language name in English.",
                },
                {"role": "user", "content": texto},
            ],
        )
        return result.choices[0].message.content.strip()
    except Exception:
        return "Spanish"


async def respuesta_localizada(ctx_or_message, texto_es: str) -> str:
    if hasattr(ctx_or_message, "message"):
        contenido = ctx_or_message.message.content
    else:
        contenido = ctx_or_message.content
    partes  = contenido.split(maxsplit=1)
    muestra = partes[1] if len(partes) > 1 else partes[0]
    if len(muestra.strip()) < 3:
        return texto_es
    idioma = await detectar_idioma(muestra)
    if idioma.lower() in ("spanish", "español"):
        return texto_es
    return await traducir_mensaje(texto_es, idioma)


# ─────────────────────────────────────────────
# LOGS DE MODERACIÓN
# ─────────────────────────────────────────────

async def log_mod_action(
    guild: discord.Guild,
    accion: str,
    target: discord.Member | discord.User,
    moderador: discord.Member,
    razon: str,
    color: discord.Colour = discord.Colour.orange(),
    extra: dict | None = None,
):
    db_add_mod_action(guild.id, target.id, moderador.id, accion, razon)

    canal = guild.get_channel(CANAL_LOGS)
    if canal is None:
        return

    emoji_map = {
        "WARN": "⚠️", "MUTE": "🔇", "UNMUTE": "🔊",
        "KICK": "👢", "BAN": "🔨", "TEMPBAN": "⏳", "UNBAN": "🔓",
        "CLEAR": "🗑️", "ROLE_ADD": "➕", "ROLE_REMOVE": "➖",
        "TICKET_OPEN": "🎫", "TICKET_CLOSE": "🔒",
        "AUTOMOD_SPAM": "🤖", "AUTOMOD_WORDS": "🚫",
        "LOCKDOWN": "🔐", "UNLOCK": "🔓",
    }
    emoji = emoji_map.get(accion, "📋")

    embed = discord.Embed(
        title=f"{emoji} {accion}",
        colour=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Usuario", value=f"{target.mention} (`{target.id}`)", inline=True)
    embed.add_field(name="Moderador", value=f"{moderador.mention}", inline=True)
    embed.add_field(name="Motivo", value=razon, inline=False)

    if extra:
        for k, v in extra.items():
            embed.add_field(name=k, value=str(v), inline=True)

    embed.set_footer(text=f"ID objetivo: {target.id}")
    try:
        await canal.send(embed=embed)
    except discord.Forbidden:
        pass


# ─────────────────────────────────────────────
# UTILIDADES DE MODERACIÓN
# ─────────────────────────────────────────────

async def get_or_create_muted_role(guild: discord.Guild) -> discord.Role:
    role = discord.utils.get(guild.roles, name="Muted")
    if role is None:
        log.info(f"Creando rol Muted en {guild.name}...")
        role = await guild.create_role(
            name="Muted",
            colour=discord.Colour.dark_grey(),
            reason="Creado automáticamente por Jin Sakai Bot",
        )
        for channel in guild.channels:
            try:
                if isinstance(channel, discord.TextChannel):
                    await channel.set_permissions(role, send_messages=False, add_reactions=False)
                elif isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                    await channel.set_permissions(role, connect=False, speak=False)
            except discord.Forbidden:
                pass
        log.info("Rol Muted creado y configurado.")
    return role


async def aplicar_mute(
    member: discord.Member,
    minutos: int,
    razon: str = "Sin razón",
    moderador: discord.Member | None = None,
) -> bool:
    try:
        role = await get_or_create_muted_role(member.guild)
        await member.add_roles(role, reason=razon)
        log.info(f"MUTE {minutos}m | {member} — {razon}")

        if moderador:
            await log_mod_action(
                member.guild, "MUTE", member, moderador, razon,
                discord.Colour.orange(), {"Duración": f"{minutos} min"}
            )

        async def auto_unmute():
            await asyncio.sleep(minutos * 60)
            try:
                await member.remove_roles(role, reason="Mute expirado automáticamente")
                log.info(f"UNMUTE automático | {member}")
            except Exception:
                pass

        asyncio.create_task(auto_unmute())
        return True
    except discord.Forbidden:
        return False


# ─────────────────────────────────────────────
# TAREA DE FONDO: TEMPBAN AUTO-UNBAN
# ─────────────────────────────────────────────

async def tempban_checker():
    """Comprueba cada 60 s si hay tempbans que hayan expirado y los levanta."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            pendientes = db_get_pending_tempbans()
            for entry in pendientes:
                guild = bot.get_guild(entry["guild_id"])
                if guild is None:
                    continue
                try:
                    await guild.unban(discord.Object(id=entry["user_id"]), reason="Tempban expirado")
                    db_remove_tempban(entry["user_id"], entry["guild_id"])
                    canal_logs = guild.get_channel(CANAL_LOGS)
                    if canal_logs:
                        embed = discord.Embed(
                            title="⏳ TEMPBAN EXPIRADO",
                            description=f"El ban temporal de <@{entry['user_id']}> ha expirado y ha sido levantado.",
                            colour=discord.Colour.green(),
                            timestamp=datetime.now(timezone.utc),
                        )
                        await canal_logs.send(embed=embed)
                    log.info(f"Tempban expirado levantado para user_id={entry['user_id']}")
                except discord.NotFound:
                    db_remove_tempban(entry["user_id"], entry["guild_id"])
                except discord.Forbidden:
                    log.warning(f"Sin permisos para levantar tempban de {entry['user_id']}")
        except Exception as e:
            log.error(f"Error en tempban_checker: {e}")
        await asyncio.sleep(60)


# ─────────────────────────────────────────────
# ANTI-RAID
# ─────────────────────────────────────────────

async def activar_modo_raid(guild: discord.Guild):
    global raid_mode
    raid_mode = True

    canal_logs = guild.get_channel(CANAL_LOGS)
    mentions   = " ".join(f"<@&{rid}>" for rid in STAFF_ROLES)

    embed = discord.Embed(
        title="🚨 MODO RAID ACTIVADO",
        description=(
            f"Se han detectado **{ANTI_RAID_JOINS}+ entradas** en los últimos "
            f"**{ANTI_RAID_SEGUNDOS} segundos**.\n\n"
            "✅ Verificación activada en el servidor.\n"
            "Usa `/desactivar_raid` cuando la situación esté controlada."
        ),
        colour=discord.Colour.red(),
        timestamp=datetime.now(timezone.utc),
    )

    try:
        await guild.edit(
            verification_level=discord.VerificationLevel.high,
            reason="Anti-raid automático — Jin Sakai Bot"
        )
    except discord.Forbidden:
        pass

    if canal_logs:
        await canal_logs.send(f"🚨 {mentions}", embed=embed)

    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            await channel.send(f"⚠️ {mentions} — **POSIBLE RAID DETECTADO**. Nivel de verificación elevado.", embed=embed)
            break


# ─────────────────────────────────────────────
# FILTRO DE PALABRAS
# ─────────────────────────────────────────────

def contiene_palabras_prohibidas(texto: str) -> bool:
    texto_lower = texto.lower()
    for palabra in PALABRAS_PROHIBIDAS:
        if palabra in texto_lower:
            return True
    return False


# ─────────────────────────────────────────────
# SISTEMA DE TICKETS — VISTA BOTÓN
# ─────────────────────────────────────────────

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Abrir Ticket", style=discord.ButtonStyle.green, custom_id="abrir_ticket")
    async def abrir_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild  = interaction.guild
        member = interaction.user

        if db_user_has_open_ticket(member.id, guild.id):
            await interaction.response.send_message(
                "⚠️ Ya tienes un ticket abierto. Ciérralo antes de abrir otro.", ephemeral=True
            )
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        for role_id in STAFF_ROLES:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        canal = await guild.create_text_channel(
            name=f"ticket-{member.name}",
            overwrites=overwrites,
            reason=f"Ticket creado por {member}",
        )
        db_create_ticket(canal.id, member.id, guild.id)

        mentions_staff = " ".join(f"<@&{rid}>" for rid in STAFF_ROLES)
        embed = discord.Embed(
            title="🎫 Ticket Abierto",
            description=(
                f"Bienvenido/a {member.mention}.\n\n"
                "Explica tu problema o consulta y el staff te atenderá lo antes posible.\n"
                f"Para cerrar el ticket usa `/cerrar_ticket` o el botón de abajo."
            ),
            colour=discord.Colour.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Jin Sakai Bot • Sistema de Tickets")

        await canal.send(f"{member.mention} | {mentions_staff}", embed=embed, view=CerrarTicketView())
        await interaction.response.send_message(f"✅ Ticket creado: {canal.mention}", ephemeral=True)

        canal_logs = guild.get_channel(CANAL_LOGS)
        if canal_logs:
            log_embed = discord.Embed(
                title="🎫 TICKET_OPEN",
                description=f"{member.mention} abrió el ticket {canal.mention}",
                colour=discord.Colour.green(),
                timestamp=datetime.now(timezone.utc),
            )
            await canal_logs.send(embed=log_embed)


class CerrarTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Cerrar Ticket", style=discord.ButtonStyle.red, custom_id="cerrar_ticket_btn")
    async def cerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal  = interaction.channel
        member = interaction.user

        ticket = db_get_ticket(canal.id)
        if not ticket:
            await interaction.response.send_message("⚠️ Este canal no es un ticket válido.", ephemeral=True)
            return

        es_staff  = any(r.id in STAFF_ROLES for r in member.roles)
        es_dueño  = ticket["user_id"] == member.id
        if not es_staff and not es_dueño:
            await interaction.response.send_message("🚫 No tienes permiso para cerrar este ticket.", ephemeral=True)
            return

        db_close_ticket(canal.id)
        await interaction.response.send_message("🔒 Cerrando ticket en 5 segundos...")
        await asyncio.sleep(5)

        canal_logs = interaction.guild.get_channel(CANAL_LOGS)
        if canal_logs:
            log_embed = discord.Embed(
                title="🔒 TICKET_CLOSE",
                description=f"Ticket {canal.name} cerrado por {member.mention}",
                colour=discord.Colour.red(),
                timestamp=datetime.now(timezone.utc),
            )
            await canal_logs.send(embed=log_embed)

        try:
            await canal.delete(reason=f"Ticket cerrado por {member}")
        except discord.Forbidden:
            pass


# ─────────────────────────────────────────────
# UTILIDADES DE REPORTES
# ─────────────────────────────────────────────

async def notificar_staff_reporte(guild: discord.Guild, reported: discord.Member, channel: discord.TextChannel):
    reportes       = db_get_reports(reported.id)
    total          = len(reportes)
    mentions_staff = " ".join(f"<@&{rid}>" for rid in STAFF_ROLES)
    resumen        = "\n".join(f"• <@{r['reporter_id']}>: {r['reason']}" for r in reportes)

    embed = discord.Embed(
        title=f"🚨 {total} reportes acumulados — {reported.display_name}",
        description=(
            f"El usuario {reported.mention} ha alcanzado **{total} reportes**.\n\n"
            f"**Motivos reportados:**\n{resumen}"
        ),
        colour=discord.Colour.red(),
    )
    embed.set_footer(text="Revisad los reportes y tomad las medidas necesarias.")

    online_staff_members = [
        m for m in guild.members
        if any(r.id in STAFF_ROLES for r in m.roles)
        and m.status != discord.Status.offline
        and not m.bot
    ]

    canal_logs = guild.get_channel(CANAL_LOGS)
    if canal_logs:
        await canal_logs.send(embed=embed)

    if online_staff_members:
        await channel.send(f"⚠️ {mentions_staff} — Se requiere vuestra atención.", embed=embed)
        for staff_member in online_staff_members:
            try:
                await staff_member.send(f"⚠️ **Alerta de reportes en {guild.name}**", embed=embed)
            except discord.Forbidden:
                pass
        report_notified.add(reported.id)
    else:
        await channel.send(
            f"⚠️ {reported.mention} ha acumulado **{total} reportes**, pero no hay staff online. "
            f"El staff será notificado automáticamente cuando se conecte."
        )
        pending_staff_alert[reported.id] = guild.id


# ─────────────────────────────────────────────
# EVENTOS
# ─────────────────────────────────────────────

@bot.event
async def on_ready():
    bot.add_view(TicketView())
    bot.add_view(CerrarTicketView())
    try:
        synced = await bot.tree.sync()
        log.info(f"✅ Comandos sincronizados: {len(synced)}")
    except Exception as e:
        log.error(f"❌ Error sincronizando: {e}")
    # ✅ CORREGIDO: reemplaza bot.loop.create_task (deprecado) por asyncio.ensure_future
    asyncio.ensure_future(tempban_checker())
    log.info("🤖 Jin Sakai Online | Multilingüe activo | SQLite activo | Head Staff activo")


@bot.event
async def on_member_join(member: discord.Member):
    global raid_mode, anti_raid_tracker

    now              = time.time()
    anti_raid_tracker = [t for t in anti_raid_tracker if now - t < ANTI_RAID_SEGUNDOS]
    anti_raid_tracker.append(now)

    if len(anti_raid_tracker) >= ANTI_RAID_JOINS and not raid_mode:
        await activar_modo_raid(member.guild)

    if raid_mode:
        try:
            await member.kick(reason="Raid detectado — Jin Sakai Bot")
        except discord.Forbidden:
            pass
        return

    canal_bienvenida = member.guild.get_channel(CANAL_BIENVENIDA)
    if canal_bienvenida:
        embed = discord.Embed(
            title=f"👋 ¡Bienvenido/a, {member.display_name}!",
            description=(
                f"Hola {member.mention}, nos alegra tenerte en **{member.guild.name}**.\n\n"
                "📋 Asegúrate de leer las reglas antes de participar.\n"
                "🎫 Si necesitas ayuda, abre un ticket o menciona al staff.\n"
                "💬 ¡Disfruta del servidor!"
            ),
            colour=discord.Colour.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Miembro #{member.guild.member_count}")
        await canal_bienvenida.send(embed=embed)

    try:
        dm_embed = discord.Embed(
            title=f"¡Hola, {member.display_name}! 👋",
            description=(
                f"Te damos la bienvenida a **{member.guild.name}**.\n\n"
                "Aquí tienes un resumen rápido:\n"
                "• Lee las reglas del servidor antes de participar.\n"
                "• Si tienes dudas o problemas, usa `/ticket` o `/help`.\n"
                "• El staff está aquí para ayudarte.\n\n"
                "¡Que lo pases genial! 🎉"
            ),
            colour=discord.Colour.blurple(),
        )
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        pass


@bot.event
async def on_presence_update(before: discord.Member, after: discord.Member):
    if not any(r.id in STAFF_ROLES for r in after.roles):
        return
    if before.status == discord.Status.offline and after.status != discord.Status.offline:
        for reported_id, guild_id in list(pending_staff_alert.items()):
            guild    = bot.get_guild(guild_id)
            reported = guild.get_member(reported_id) if guild else None
            reportes = db_get_reports(reported_id)
            if not guild or not reported or not reportes:
                continue
            resumen = "\n".join(f"• <@{r['reporter_id']}>: {r['reason']}" for r in reportes)
            embed   = discord.Embed(
                title=f"🚨 Alerta pendiente — {reported.display_name}",
                description=(
                    f"{reported.mention} acumuló **{len(reportes)} reportes** mientras estabas offline.\n\n"
                    f"**Motivos:**\n{resumen}"
                ),
                colour=discord.Colour.orange(),
            )
            try:
                await after.send(f"👋 Bienvenido/a de vuelta. Alertas pendientes en **{guild.name}**:", embed=embed)
            except discord.Forbidden:
                pass
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    mentions_staff = " ".join(f"<@&{rid}>" for rid in STAFF_ROLES)
                    await channel.send(
                        f"📢 {after.mention} se ha conectado. {mentions_staff} — "
                        f"Hay una alerta pendiente sobre {reported.mention} con **{len(reportes)} reportes**.",
                        embed=embed,
                    )
                    break
            del pending_staff_alert[reported_id]
            report_notified.add(reported_id)


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user or message.guild is None:
        return

    user_id  = message.author.id
    is_staff = any(r.id in STAFF_ROLES for r in message.author.roles)

    # ── Filtro de palabras prohibidas ────────────────────────────────
    if not is_staff and contiene_palabras_prohibidas(message.content):
        try:
            await message.delete()
        except discord.Forbidden:
            pass
        idioma = await detectar_idioma(message.content)
        aviso  = await traducir_mensaje(
            f"🚫 {message.author.mention}, ese tipo de lenguaje no está permitido en este servidor.", idioma
        )
        await message.channel.send(aviso, delete_after=8)
        await log_mod_action(
            message.guild, "AUTOMOD_WORDS", message.author, bot.user,
            f"Palabra prohibida detectada: '{message.content[:50]}'",
            discord.Colour.dark_red()
        )
        return

    # ── Automod de spam ──────────────────────────────────────────────
    if not is_staff:
        now       = time.time()
        historial = spam_tracker.get(user_id, [])
        historial = [t for t in historial if now - t < SPAM_SEGUNDOS]
        historial.append(now)
        spam_tracker[user_id] = historial

        if len(historial) >= SPAM_MENSAJES:
            spam_tracker[user_id] = []
            warn_count, monitored  = db_get_warns(user_id)

            if monitored:
                warn_count += 1
                db_set_warns(user_id, warn_count, True)
                idioma = await detectar_idioma(message.content)

                if warn_count == 1:
                    ok = await aplicar_mute(message.author, MUTE_DURACION, "Spam — Aviso 1/3", bot.user)
                    if ok:
                        txt = await traducir_mensaje(
                            f"🔇 {message.author.mention} ha sido **muteado {MUTE_DURACION} minutos** "
                            f"por spam. *(Aviso 1/3 — siguiente: expulsión)*", idioma
                        )
                        await message.channel.send(txt)
                elif warn_count == 2:
                    try:
                        await message.author.kick(reason="Spam — Aviso 2/3")
                        db_delete_warns(user_id)
                        await log_mod_action(
                            message.guild, "KICK", message.author, bot.user,
                            "Automod — Spam Aviso 2/3", discord.Colour.red()
                        )
                        txt = await traducir_mensaje(
                            f"👢 {message.author.mention} ha sido **expulsado** por spam. "
                            f"*(Aviso 2/3 — si vuelve y reincide: baneo)*", idioma
                        )
                        await message.channel.send(txt)
                    except discord.Forbidden:
                        await message.channel.send("🚫 No pude expulsar al usuario.")
                elif warn_count >= 3:
                    try:
                        await message.author.ban(reason="Spam — Aviso 3/3")
                        db_delete_warns(user_id)
                        await log_mod_action(
                            message.guild, "BAN", message.author, bot.user,
                            "Automod — Spam Aviso 3/3", discord.Colour.dark_red()
                        )
                        txt = await traducir_mensaje(
                            f"🔨 {message.author.mention} ha sido **baneado** por spam. *(Aviso 3/3)*", idioma
                        )
                        await message.channel.send(txt)
                    except discord.Forbidden:
                        await message.channel.send("🚫 No pude banear al usuario.")

            elif user_id not in spam_notified:
                spam_notified.add(user_id)
                idioma         = await detectar_idioma(message.content)
                mentions_staff = " ".join(f"<@&{rid}>" for rid in STAFF_ROLES)
                aviso          = await traducir_mensaje(
                    f"😅 Oye {message.author.mention}, estás enviando mensajes muy rápido. "
                    f"Baja el ritmo o podrías acabar muteado. 😉", idioma
                )
                await message.channel.send(
                    f"{aviso}\n\n📢 {mentions_staff} — Posible spam de "
                    f"**{message.author.display_name}**. "
                    f"Usad `/activar_avisos @{message.author.display_name}` para avisos formales."
                )

                async def limpiar_notificado(uid=user_id):
                    await asyncio.sleep(30)
                    spam_notified.discard(uid)

                asyncio.create_task(limpiar_notificado())

    # ── Alias multilingüe ────────────────────────────────────────────
    if message.content.startswith("!"):
        partes    = message.content[1:].split(maxsplit=1)
        cmd_usado = partes[0].lower()
        cmd_canon = COMMAND_ALIASES.get(cmd_usado)
        if cmd_canon and cmd_canon != cmd_usado:
            resto           = (" " + partes[1]) if len(partes) > 1 else ""
            message.content = f"!{cmd_canon}{resto}"

    # ── Chat con IA por mención ──────────────────────────────────────
    if bot.user.mentioned_in(message):
        clean_text = (
            message.content
            .replace(f"<@!{bot.user.id}>", "")
            .replace(f"<@{bot.user.id}>", "")
            .strip()
        )
        if not clean_text:
            await message.reply("¿En qué puedo ayudarte? / How can I help you?")
            return
        async with message.channel.typing():
            try:
                completion = await asyncio.to_thread(
                    client_groq.chat.completions.create,
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are Jin Sakai, a smart and friendly Discord assistant. "
                                "ALWAYS detect the language the user is writing in and respond "
                                "in EXACTLY that same language. Never switch languages unless asked."
                            ),
                        },
                        {"role": "user", "content": clean_text},
                    ],
                )
                await message.reply(completion.choices[0].message.content[:1900])
            except Exception as e:
                log.error(f"Error Groq: {e}")
                await message.reply("⚠️ Error conectando con la IA.")

    # ── Reacción 🚫 para borrar mensaje ─────────────────────────────
    await bot.process_commands(message)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if str(payload.emoji) != "🚫":
        return
    guild  = bot.get_guild(payload.guild_id)
    if not guild:
        return
    member = guild.get_member(payload.user_id)
    if not member or not any(r.id in STAFF_ROLES for r in member.roles):
        return

    canal   = guild.get_channel(payload.channel_id)
    mensaje = await canal.fetch_message(payload.message_id)
    autor   = mensaje.author

    if autor == bot.user:
        return

    await mensaje.delete()
    await log_mod_action(
        guild, "AUTOMOD_WORDS", autor, member,
        f"Mensaje eliminado por reacción 🚫 del staff",
        discord.Colour.dark_orange(),
        {"Contenido (preview)": mensaje.content[:100] or "[sin texto]"}
    )
    try:
        await autor.send(
            f"⚠️ Un moderador de **{guild.name}** eliminó uno de tus mensajes por incumplir las normas."
        )
    except discord.Forbidden:
        pass


@bot.event
async def on_guild_channel_create(channel):
    muted_role = discord.utils.get(channel.guild.roles, name="Muted")
    if muted_role is None:
        return
    try:
        if isinstance(channel, discord.TextChannel):
            await channel.set_permissions(muted_role, send_messages=False, add_reactions=False)
        elif isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            await channel.set_permissions(muted_role, connect=False, speak=False)
    except discord.Forbidden:
        pass


# ─────────────────────────────────────────────
# COMANDOS GENERALES
# ─────────────────────────────────────────────

@bot.hybrid_command(name="ping", description="Latencia del bot / Bot latency")
async def ping(ctx):
    await ctx.send(f"🏓 Pong! **{round(bot.latency * 1000)}ms**")


@bot.hybrid_command(name="info", description="Información del bot / Bot info")
async def info(ctx):
    msg = await respuesta_localizada(ctx, "🛡️ **Jin Sakai Bot** activo. Moderación e IA multilingüe.")
    await ctx.send(msg)


# ─────────────────────────────────────────────
# AVATAR
# ─────────────────────────────────────────────

@bot.hybrid_command(name="avatar", description="Muestra el avatar de un usuario en alta resolución")
@commands.cooldown(1, 5, commands.BucketType.user)
@app_commands.describe(member="Usuario (omite para verte a ti)")
async def avatar(ctx, member: discord.Member = None):
    target = member or ctx.author
    embed = discord.Embed(
        title=f"🖼️ Avatar de {target.display_name}",
        colour=target.colour if target.colour != discord.Colour.default() else discord.Colour.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    avatar_url = target.display_avatar.url
    embed.set_image(url=avatar_url)
    links = f"[PNG]({target.display_avatar.replace(format='png', size=4096).url}) | "
    links += f"[JPG]({target.display_avatar.replace(format='jpg', size=4096).url}) | "
    links += f"[WEBP]({target.display_avatar.replace(format='webp', size=4096).url})"
    embed.add_field(name="Descargar", value=links, inline=False)
    if target.guild_avatar:
        embed.set_thumbnail(url=target.avatar.url if target.avatar else avatar_url)
        embed.set_footer(text="Mostrando avatar del servidor | Miniatura: avatar global")
    else:
        embed.set_footer(text=f"Solicitado por {ctx.author.display_name}")
    await ctx.send(embed=embed)


# ─────────────────────────────────────────────
# PANEL DE AYUDA
# ─────────────────────────────────────────────

@bot.hybrid_command(name="comandos", description="[SOLO STAFF] Lista de todos los comandos disponibles")
async def comandos(ctx):
    es_staff = any(r.id in STAFF_ROLES for r in ctx.author.roles)
    if not es_staff:
        msg = await respuesta_localizada(ctx, "🚫 Este comando es exclusivo del staff.")
        await ctx.send(msg, ephemeral=True)
        return

    embed = discord.Embed(
        title="📋 Panel de Comandos — Jin Sakai Bot",
        description="Guía completa de comandos. Solo visible para el Staff.",
        colour=discord.Colour.gold(),
    )

    embed.add_field(
        name="🌐 Generales (todos los miembros)",
        value=(
            "`/ping` — Latencia\n"
            "`/info` — Info del bot\n"
            "`/help` · `!ayuda` — Solicitar ayuda al staff\n"
            "`/contactar @user <msg>` — Enviar DM\n"
            "`/reportar @user <motivo>` — Reportar\n"
            "`/userinfo [@user]` — Perfil de usuario\n"
            "`/avatar [@user]` — Avatar en alta resolución\n"
            "`/serverinfo` — Info del servidor\n"
            "`/ticket` — Abrir ticket de soporte\n"
        ),
        inline=False,
    )

    embed.add_field(
        name="⚠️ Advertencias",
        value=(
            "`/warn @user <motivo>` — Emitir aviso formal\n"
            "→ 3 warns: Mute → Kick → Ban automático\n\n"
            "`/historial [@user]` — Ver historial de moderación\n"
        ),
        inline=False,
    )

    embed.add_field(
        name="🔇 Moderación",
        value=(
            "`/clear [n]` · `!limpiar` · `!purge` — Borra mensajes\n"
            "`/mute @user [min] [motivo]` — Mutear (default 10 min)\n"
            "`/unmute @user` — Quitar mute\n"
            "`/kick @user [motivo]` — Expulsar\n"
            "`/ban @user [motivo]` — Banear permanente (pide confirmación)\n"
            "`/tempban @user <minutos> [motivo]` — Ban temporal con desbaneo automático\n"
            "`/unban <user_id> [motivo]` — Desbanear usuario\n"
            "`/lockdown [motivo]` — Bloquear el canal actual\n"
            "`/unlock [motivo]` — Desbloquear el canal actual\n"
            "`/poll <pregunta> <op1> <op2> [op3] [op4]` — Crear encuesta\n"
            "`/cerrar_ticket` — Cerrar ticket desde el canal\n"
        ),
        inline=False,
    )

    embed.add_field(
        name="👑 Gestión de roles",
        value=(
            "`/dar_role @user @rol` — Asignar rol staff\n"
            "`/quitar_role @user @rol` — Quitar rol staff\n"
        ),
        inline=False,
    )

    embed.add_field(
        name="🤖 Automod — Vigilancia",
        value=(
            "`/activar_avisos @user` — Activar vigilancia de spam\n"
            "→ Siguiente spam: Mute → Kick → Ban\n\n"
            "`/desactivar_avisos @user` — Desactivar vigilancia\n"
            "`/ver_avisos @user` — Consultar estado\n"
            "`/desactivar_raid` — Desactivar modo anti-raid\n"
        ),
        inline=False,
    )

    embed.add_field(
        name="⚙️ Umbrales configurados",
        value=(
            f"• Spam: **{SPAM_MENSAJES} msgs** en **{SPAM_SEGUNDOS}s**\n"
            f"• Mute automático: **{MUTE_DURACION} min**\n"
            f"• Reportes para alertar staff: **{MAX_REPORTES}**\n"
            f"• Anti-raid: **{ANTI_RAID_JOINS} entradas** en **{ANTI_RAID_SEGUNDOS}s**\n"
        ),
        inline=False,
    )

    embed.add_field(
        name="✨ Funciones activas",
        value=(
            "• 🗃️ **Persistencia SQLite** — warns, reportes, tempbans e historial entre reinicios\n"
            "• 📋 **Logs de moderación** — todas las acciones registradas en canal de logs\n"
            "• 🎫 **Sistema de tickets** — botón en el canal de tickets\n"
            "• 🚨 **Anti-raid automático** — eleva la verificación y expulsa entradas masivas\n"
            "• 👋 **Bienvenida automática** — mensaje y DM al entrar nuevos miembros\n"
            "• 🚫 **Filtro de palabras** — elimina lenguaje prohibido automáticamente\n"
            "• 🚫 **Reacción moderación** — reacciona con 🚫 a un mensaje para borrarlo\n"
            "• ⏳ **Tempban con auto-unban** — desbaneo automático al expirar el tiempo\n"
            "• 📊 **Encuestas** — hasta 4 opciones con reacciones de emoji\n"
            "• 🔐 **Lockdown / Unlock** — bloqueo y desbloqueo de canales\n"
            "• 🖼️ **Avatar HD** — descarga en PNG, JPG y WEBP\n"
            "• 🔓 **Unban** — desbaneo manual de usuarios\n"
            "• 👑 **Head Staff** — nuevo rol de alta jerarquía integrado\n"
            "• ⏱️ **Cooldowns** — evita abuso de comandos\n"
        ),
        inline=False,
    )

    embed.set_footer(text="Jin Sakai Bot • Solo staff puede ver este panel")
    await ctx.send(embed=embed, ephemeral=True)
    log.info(f"COMANDOS consultado por {ctx.author}")


# ─────────────────────────────────────────────
# USERINFO
# ─────────────────────────────────────────────

@bot.hybrid_command(name="userinfo", description="Información detallada de un usuario")
@commands.cooldown(1, 10, commands.BucketType.user)
@app_commands.describe(member="Usuario (omite para verte a ti)")
async def userinfo(ctx, member: discord.Member = None):
    member    = member or ctx.author
    es_staff  = any(r.id in STAFF_ROLES for r in ctx.author.roles)
    warn_cnt, monitored = db_get_warns(member.id)
    historial = db_get_mod_history(member.id)
    reportes  = db_get_reports(member.id)

    estado_vigilancia = "🔴 En vigilancia" if monitored else "🟢 Sin vigilancia"
    roles_list = [r.mention for r in member.roles if r.name != "@everyone"]
    roles_str  = " ".join(roles_list) if roles_list else "Ninguno"
    joined     = discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Desconocido"
    created    = discord.utils.format_dt(member.created_at, "R")

    embed = discord.Embed(
        title=f"👤 {member.display_name}",
        colour=member.colour if member.colour != discord.Colour.default() else discord.Colour.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="🏷️ Tag", value=str(member), inline=True)
    embed.add_field(name="🆔 ID", value=str(member.id), inline=True)
    embed.add_field(name="🤖 Bot", value="Sí" if member.bot else "No", inline=True)
    embed.add_field(name="📅 Cuenta creada", value=created, inline=True)
    embed.add_field(name="📥 Entró al servidor", value=joined, inline=True)
    embed.add_field(name="🎭 Roles", value=roles_str[:1024], inline=False)

    if es_staff:
        embed.add_field(name="⚠️ Warns", value=f"**{warn_cnt}/3**", inline=True)
        embed.add_field(name="👁️ Vigilancia", value=estado_vigilancia, inline=True)
        embed.add_field(name="🚨 Reportes", value=str(len(reportes)), inline=True)

        if historial:
            ultimas = historial[:5]
            hist_str = "\n".join(
                f"`{h['action']}` — {h['reason'][:40]} (<t:{int(h['ts'])}:R>)"
                for h in ultimas
            )
            embed.add_field(name="📜 Últimas acciones", value=hist_str, inline=False)

    embed.set_footer(text=f"Solicitado por {ctx.author.display_name}")
    await ctx.send(embed=embed)


# ─────────────────────────────────────────────
# SERVERINFO
# ─────────────────────────────────────────────

@bot.hybrid_command(name="serverinfo", description="Información detallada del servidor")
@commands.cooldown(1, 15, commands.BucketType.guild)
async def serverinfo(ctx):
    guild   = ctx.guild
    created = discord.utils.format_dt(guild.created_at, "R")

    total   = guild.member_count
    bots    = sum(1 for m in guild.members if m.bot)
    humanos = total - bots
    online  = sum(
        1 for m in guild.members
        if m.status != discord.Status.offline and not m.bot
    )

    texto_canales = (
        f"💬 Texto: {len(guild.text_channels)} | "
        f"🔊 Voz: {len(guild.voice_channels)} | "
        f"📂 Categorías: {len(guild.categories)}"
    )

    embed = discord.Embed(
        title=f"🏰 {guild.name}",
        colour=discord.Colour.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.add_field(name="🆔 ID", value=str(guild.id), inline=True)
    embed.add_field(name="👑 Propietario", value=guild.owner.mention if guild.owner else "Desconocido", inline=True)
    embed.add_field(name="📅 Creado", value=created, inline=True)
    embed.add_field(name="👥 Miembros", value=f"Total: **{total}** | Humanos: **{humanos}** | Online: **{online}** | Bots: **{bots}**", inline=False)
    embed.add_field(name="📡 Canales", value=texto_canales, inline=False)
    embed.add_field(name="🎭 Roles", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="😀 Emojis", value=str(len(guild.emojis)), inline=True)
    embed.add_field(name="🔒 Verificación", value=str(guild.verification_level).capitalize(), inline=True)
    embed.add_field(name="💎 Boosts", value=f"Nivel {guild.premium_tier} ({guild.premium_subscription_count} boosts)", inline=True)

    embed.set_footer(text=f"Solicitado por {ctx.author.display_name}")
    await ctx.send(embed=embed)


# ─────────────────────────────────────────────
# WARN — AVISO MANUAL
# ─────────────────────────────────────────────

@bot.hybrid_command(name="warn", description="[Staff] Emite un aviso formal a un usuario")
@commands.has_permissions(manage_messages=True)
@commands.cooldown(1, 5, commands.BucketType.user)
@app_commands.describe(member="Usuario a advertir", motivo="Motivo del aviso")
async def warn(ctx, member: discord.Member, *, motivo: str = "No especificado"):
    if any(r.id in STAFF_ROLES for r in member.roles):
        msg = await respuesta_localizada(ctx, "⚠️ No puedes advertir a un miembro del staff.")
        await ctx.send(msg, ephemeral=True)
        return

    warn_cnt, monitored = db_get_warns(member.id)
    warn_cnt += 1
    db_set_warns(member.id, warn_cnt, monitored)
    await log_mod_action(
        ctx.guild, "WARN", member, ctx.author, motivo, discord.Colour.yellow(),
        {"Avisos acumulados": f"{warn_cnt}/5"}
    )

    try:
        dm = discord.Embed(
            title="⚠️ Has recibido un aviso",
            description=(
                f"**Servidor:** {ctx.guild.name}\n"
                f"**Motivo:** {motivo}\n"
                f"**Avisos acumulados:** {warn_cnt}/5\n\n"
                "Si acumulas 5 avisos serás muteado, expulsado o baneado."
            ),
            colour=discord.Colour.yellow(),
        )
        await member.send(embed=dm)
    except discord.Forbidden:
        pass

    escalada = ""
    if warn_cnt == 3:
        ok = await aplicar_mute(member, MUTE_DURACION * 2, f"3 avisos formales — {motivo}", ctx.author)
        escalada = f" → **Muteado {MUTE_DURACION * 2} min** automáticamente."
    elif warn_cnt == 4:
        try:
            await member.kick(reason=f"4 avisos formales — {motivo}")
            await log_mod_action(ctx.guild, "KICK", member, ctx.author, f"4 avisos — {motivo}", discord.Colour.red())
            escalada = " → **Expulsado** automáticamente."
        except discord.Forbidden:
            escalada = " (no se pudo expulsar — sin permisos)"
    elif warn_cnt >= 5:
        try:
            await member.ban(reason=f"5+ avisos formales — {motivo}")
            await log_mod_action(ctx.guild, "BAN", member, ctx.author, f"5+ avisos — {motivo}", discord.Colour.dark_red())
            escalada = " → **Baneado** automáticamente."
        except discord.Forbidden:
            escalada = " (no se pudo banear — sin permisos)"

    msg = await respuesta_localizada(
        ctx,
        f"⚠️ Aviso emitido a **{member.display_name}** ({warn_cnt}/5). Motivo: {motivo}{escalada}"
    )
    await ctx.send(msg, ephemeral=True)


# ─────────────────────────────────────────────
# HISTORIAL DE MODERACIÓN
# ─────────────────────────────────────────────

@bot.hybrid_command(name="historial", description="[Staff] Historial de moderación de un usuario")
@commands.has_permissions(manage_messages=True)
@commands.cooldown(1, 5, commands.BucketType.user)
@app_commands.describe(member="Usuario")
async def historial(ctx, member: discord.Member):
    acciones = db_get_mod_history(member.id)

    embed = discord.Embed(
        title=f"📜 Historial de moderación — {member.display_name}",
        colour=discord.Colour.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    if not acciones:
        embed.description = "✅ Sin acciones de moderación registradas."
    else:
        for idx, a in enumerate(acciones[:15], 1):
            mod_str = f"<@{a['mod_id']}>"
            ts_str  = f"<t:{int(a['ts'])}:R>"
            embed.add_field(
                name=f"{idx}. {a['action']}",
                value=f"**Motivo:** {a['reason'][:80]}\n**Mod:** {mod_str} | {ts_str}",
                inline=False,
            )

    warn_cnt, monitored = db_get_warns(member.id)
    reportes            = db_get_reports(member.id)
    embed.set_footer(
        text=f"Warns: {warn_cnt}/5 | Reportes: {len(reportes)} | Vigilancia: {'Sí' if monitored else 'No'}"
    )
    await ctx.send(embed=embed, ephemeral=True)


# ─────────────────────────────────────────────
# SISTEMA DE TICKETS
# ─────────────────────────────────────────────

@bot.hybrid_command(name="ticket", description="Abre un ticket de soporte con el staff")
@commands.cooldown(1, 30, commands.BucketType.user)
async def ticket(ctx):
    if db_user_has_open_ticket(ctx.author.id, ctx.guild.id):
        msg = await respuesta_localizada(ctx, "⚠️ Ya tienes un ticket abierto. Ciérralo antes de abrir otro.")
        await ctx.send(msg, ephemeral=True)
        return

    guild  = ctx.guild
    member = ctx.author

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
    }
    for role_id in STAFF_ROLES:
        role = guild.get_role(role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    canal = await guild.create_text_channel(
        name=f"ticket-{member.name}",
        overwrites=overwrites,
        reason=f"Ticket abierto por {member}",
    )
    db_create_ticket(canal.id, member.id, guild.id)

    mentions_staff = " ".join(f"<@&{rid}>" for rid in STAFF_ROLES)
    embed = discord.Embed(
        title="🎫 Ticket Abierto",
        description=(
            f"Bienvenido/a {member.mention}.\n\n"
            "Explica tu problema o consulta con el mayor detalle posible.\n"
            "El staff te atenderá lo antes posible.\n\n"
            "Para cerrar el ticket usa el botón de abajo o `/cerrar_ticket`."
        ),
        colour=discord.Colour.green(),
        timestamp=datetime.now(timezone.utc),
    )
    await canal.send(f"{member.mention} | {mentions_staff}", embed=embed, view=CerrarTicketView())

    msg = await respuesta_localizada(ctx, f"✅ Ticket creado: {canal.mention}")
    await ctx.send(msg, ephemeral=True)


@bot.hybrid_command(name="cerrar_ticket", description="Cierra el ticket actual")
async def cerrar_ticket(ctx):
    ticket_data = db_get_ticket(ctx.channel.id)
    if not ticket_data:
        msg = await respuesta_localizada(ctx, "⚠️ Este canal no es un ticket válido.")
        await ctx.send(msg, ephemeral=True)
        return

    es_staff = any(r.id in STAFF_ROLES for r in ctx.author.roles)
    es_dueño = ticket_data["user_id"] == ctx.author.id
    if not es_staff and not es_dueño:
        msg = await respuesta_localizada(ctx, "🚫 No tienes permiso para cerrar este ticket.")
        await ctx.send(msg, ephemeral=True)
        return

    db_close_ticket(ctx.channel.id)
    await log_mod_action(
        ctx.guild, "TICKET_CLOSE",
        ctx.guild.get_member(ticket_data["user_id"]) or ctx.author,
        ctx.author, "Cierre de ticket", discord.Colour.greyple()
    )
    await ctx.send("🔒 Cerrando ticket en 5 segundos...")
    await asyncio.sleep(5)
    try:
        await ctx.channel.delete(reason=f"Ticket cerrado por {ctx.author}")
    except discord.Forbidden:
        pass


@bot.hybrid_command(name="setup_tickets", description="[Staff] Envía el panel de tickets al canal configurado")
@commands.has_permissions(manage_channels=True)
async def setup_tickets(ctx):
    canal = ctx.guild.get_channel(CANAL_TICKETS)
    if canal is None:
        msg = await respuesta_localizada(ctx, "⚠️ No se encontró el canal de tickets configurado.")
        await ctx.send(msg, ephemeral=True)
        return

    embed = discord.Embed(
        title="🎫 Sistema de Soporte — Jin Sakai",
        description=(
            "¿Necesitas ayuda del staff?\n\n"
            "Pulsa el botón de abajo para abrir un ticket privado.\n"
            "Un miembro del equipo te atenderá lo antes posible.\n\n"
            "⚠️ Solo abre un ticket si realmente lo necesitas."
        ),
        colour=discord.Colour.blurple(),
    )
    embed.set_footer(text="Jin Sakai Bot • Sistema de Tickets")
    await canal.send(embed=embed, view=TicketView())
    msg = await respuesta_localizada(ctx, f"✅ Panel de tickets enviado a {canal.mention}.")
    await ctx.send(msg, ephemeral=True)


# ─────────────────────────────────────────────
# ANTI-RAID MANUAL
# ─────────────────────────────────────────────

@bot.hybrid_command(name="desactivar_raid", description="[Staff] Desactiva el modo anti-raid")
@commands.has_permissions(manage_guild=True)
async def desactivar_raid(ctx):
    global raid_mode
    raid_mode = False
    try:
        await ctx.guild.edit(
            verification_level=discord.VerificationLevel.low,
            reason=f"Anti-raid desactivado por {ctx.author}"
        )
    except discord.Forbidden:
        pass
    msg = await respuesta_localizada(ctx, "✅ Modo anti-raid desactivado. Nivel de verificación restaurado.")
    await ctx.send(msg, ephemeral=True)
    await log_mod_action(
        ctx.guild, "AUTOMOD_WORDS", ctx.author, ctx.author,
        "Modo anti-raid desactivado manualmente", discord.Colour.green()
    )


# ─────────────────────────────────────────────
# CONTACTAR
# ─────────────────────────────────────────────

@bot.hybrid_command(name="contactar", description="Envía un DM a otro usuario a través del bot")
@commands.cooldown(1, 30, commands.BucketType.user)
@app_commands.describe(destinatario="El usuario", mensaje="Tu mensaje")
async def contactar(ctx, destinatario: discord.Member, *, mensaje: str):
    if destinatario == bot.user:
        await ctx.send("⚠️ No puedes enviarme mensajes directamente.", ephemeral=True)
        return
    if destinatario == ctx.author:
        await ctx.send("⚠️ No puedes enviarte un mensaje a ti mismo.", ephemeral=True)
        return

    await ctx.defer(ephemeral=True)

    try:
        analisis = await asyncio.to_thread(
            client_groq.chat.completions.create,
            model="llama-3.3-70b-versatile",
            max_tokens=60,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a content moderator for a Discord server. "
                        "Analyze the message and respond with ONLY one word:\n"
                        "PERMITIDO — genuine help request, important notice, report, or legitimate communication.\n"
                        "BLOQUEADO — spam, threats, insults, harassment, or inappropriate content."
                    ),
                },
                {"role": "user", "content": mensaje},
            ],
        )
        veredicto = analisis.choices[0].message.content.strip().upper()
    except Exception as e:
        log.error(f"Error IA contactar: {e}")
        veredicto = "PERMITIDO"

    if "BLOQUEADO" in veredicto:
        msg = await respuesta_localizada(
            ctx,
            "🚫 Tu mensaje ha sido bloqueado por la IA. Este comando es solo para comunicados legítimos.",
        )
        await ctx.send(msg, ephemeral=True)
        return

    idioma = await detectar_idioma(mensaje)
    embed  = discord.Embed(
        title="📩 Mensaje privado vía Jin Sakai Bot",
        description=mensaje,
        colour=discord.Colour.blurple(),
    )
    embed.set_author(name=f"{ctx.author.display_name} ({ctx.author})", icon_url=ctx.author.display_avatar.url)
    embed.set_footer(text=f"Servidor: {ctx.guild.name}")

    try:
        await destinatario.send(embed=embed)
        msg = await traducir_mensaje(f"✅ Mensaje enviado a **{destinatario.display_name}**.", idioma)
        await ctx.send(msg, ephemeral=True)
    except discord.Forbidden:
        msg = await traducir_mensaje(f"⚠️ No pude enviar el mensaje (DMs cerrados).", idioma)
        await ctx.send(msg, ephemeral=True)


# ─────────────────────────────────────────────
# REPORTAR
# ─────────────────────────────────────────────

@bot.hybrid_command(name="reportar", description="Reporta a un usuario al staff")
@commands.cooldown(1, 60, commands.BucketType.user)
@app_commands.describe(usuario="El usuario a reportar", motivo="Motivo del reporte")
async def reportar(ctx, usuario: discord.Member, *, motivo: str):
    if usuario == bot.user:
        await ctx.send("⚠️ No puedes reportar al bot.", ephemeral=True)
        return
    if usuario == ctx.author:
        await ctx.send("⚠️ No puedes reportarte a ti mismo.", ephemeral=True)
        return

    await ctx.defer(ephemeral=True)

    try:
        analisis = await asyncio.to_thread(
            client_groq.chat.completions.create,
            model="llama-3.3-70b-versatile",
            max_tokens=60,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a content moderator. Is this report reason legitimate? "
                        "Reply with ONLY: VALIDO or INVALIDO."
                    ),
                },
                {"role": "user", "content": motivo},
            ],
        )
        veredicto = analisis.choices[0].message.content.strip().upper()
    except Exception as e:
        log.error(f"Error IA reportar: {e}")
        veredicto = "VALIDO"

    idioma = await detectar_idioma(motivo)

    if "INVALIDO" in veredicto:
        msg = await traducir_mensaje(
            "🚫 Tu reporte ha sido rechazado (no parece legítimo).", idioma
        )
        await ctx.send(msg, ephemeral=True)
        return

    if db_already_reported(usuario.id, ctx.author.id):
        msg = await traducir_mensaje(
            f"ℹ️ Ya has reportado a **{usuario.display_name}**. El staff ya tiene constancia.", idioma
        )
        await ctx.send(msg, ephemeral=True)
        return

    total = db_add_report(usuario.id, ctx.author.id, motivo)

    embed_reportado = discord.Embed(
        title="⚠️ Has sido reportado",
        description=(
            f"Un miembro de **{ctx.guild.name}** te ha reportado.\n\n"
            f"**Motivo:** {motivo}\n\n"
            "Si crees que este reporte es injusto, contacta al staff con `/contactar`."
        ),
        colour=discord.Colour.orange(),
    )
    embed_reportado.set_footer(text=f"Reporte {total}/{MAX_REPORTES}.")
    try:
        await usuario.send(embed=embed_reportado)
    except discord.Forbidden:
        pass

    msg_ok = await traducir_mensaje(
        f"✅ Reporte registrado sobre **{usuario.display_name}** ({total}/{MAX_REPORTES}).", idioma
    )
    await ctx.send(msg_ok, ephemeral=True)

    if total >= MAX_REPORTES and usuario.id not in report_notified:
        await notificar_staff_reporte(ctx.guild, usuario, ctx.channel)


# ─────────────────────────────────────────────
# MODERACIÓN
# ─────────────────────────────────────────────

@bot.hybrid_command(name="clear", description="[Staff] Borra mensajes del canal")
@commands.has_permissions(manage_messages=True)
@app_commands.describe(cantidad="Número de mensajes (omite para todos)")
async def clear(ctx, cantidad: int = None):
    es_staff = any(r.id in STAFF_ROLES for r in ctx.author.roles)
    if not es_staff:
        msg = await respuesta_localizada(ctx, "🚫 Solo el staff puede usar este comando.")
        await ctx.send(msg, ephemeral=True)
        return

    await ctx.defer(ephemeral=True)
    canal = ctx.channel

    try:
        if cantidad is None:
            borrados = await canal.purge(limit=None)
            total    = len(borrados)
            log.info(f"CLEAR TOTAL | #{canal.name} ({total} msgs) por {ctx.author}")
            msg = await respuesta_localizada(ctx, f"🗑️ Canal **#{canal.name}** limpiado — **{total} mensajes** eliminados.")
        else:
            if cantidad < 1:
                await ctx.send(await respuesta_localizada(ctx, "⚠️ La cantidad debe ser mayor que 0."), ephemeral=True)
                return
            borrados = await canal.purge(limit=cantidad)
            total    = len(borrados)
            msg = await respuesta_localizada(ctx, f"🗑️ **{total} mensaje(s)** eliminado(s) en **#{canal.name}**.")

        await log_mod_action(
            ctx.guild, "CLEAR", ctx.author, ctx.author,
            f"{total} mensajes borrados en #{canal.name}",
            discord.Colour.greyple(), {"Canal": canal.mention, "Cantidad": total}
        )
        await ctx.send(msg, ephemeral=True)
    except discord.Forbidden:
        await ctx.send(await respuesta_localizada(ctx, "🚫 Sin permisos para borrar mensajes."), ephemeral=True)
    except discord.HTTPException as e:
        log.error(f"Error en clear: {e}")
        await ctx.send(
            await respuesta_localizada(ctx, "⚠️ No se pudieron borrar algunos mensajes (>14 días de antigüedad)."),
            ephemeral=True
        )


@bot.hybrid_command(name="mute", description="[Staff] Mutea a un miembro")
@commands.has_permissions(manage_roles=True)
@app_commands.describe(member="Usuario", minutos="Minutos (default 10)", reason="Motivo")
async def mute(ctx, member: discord.Member, minutos: int = MUTE_DURACION, *, reason: str = "No especificado"):
    if any(r.id in STAFF_ROLES for r in member.roles):
        await ctx.send(await respuesta_localizada(ctx, "⚠️ No puedo mutear a un miembro del staff."), ephemeral=True)
        return
    muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if muted_role and muted_role in member.roles:
        await ctx.send(await respuesta_localizada(ctx, f"ℹ️ {member.mention} ya está muteado."), ephemeral=True)
        return
    ok = await aplicar_mute(member, minutos, reason, ctx.author)
    if ok:
        await ctx.send(await respuesta_localizada(ctx, f"🔇 **{member.display_name}** muteado {minutos} min. Motivo: {reason}"), ephemeral=True)
    else:
        await ctx.send(await respuesta_localizada(ctx, "🚫 Sin permisos suficientes para mutear."), ephemeral=True)


@bot.hybrid_command(name="unmute", description="[Staff] Quita el mute")
@commands.has_permissions(manage_roles=True)
@app_commands.describe(member="Usuario")
async def unmute(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name="Muted")
    if role is None or role not in member.roles:
        await ctx.send(await respuesta_localizada(ctx, f"ℹ️ {member.mention} no está muteado."), ephemeral=True)
        return
    await member.remove_roles(role, reason=f"Desmute manual por {ctx.author}")
    await log_mod_action(ctx.guild, "UNMUTE", member, ctx.author, "Desmute manual", discord.Colour.green())
    await ctx.send(await respuesta_localizada(ctx, f"🔊 **{member.display_name}** desmuteado."), ephemeral=True)


@bot.hybrid_command(name="kick", description="[Staff] Expulsa a un miembro")
@commands.has_permissions(kick_members=True)
@app_commands.describe(member="Usuario", reason="Motivo")
async def kick(ctx, member: discord.Member, *, reason: str = "No especificado"):
    try:
        await member.kick(reason=reason)
        await log_mod_action(ctx.guild, "KICK", member, ctx.author, reason, discord.Colour.red())
        await ctx.send(await respuesta_localizada(ctx, f"👢 **{member.display_name}** expulsado. Motivo: {reason}"), ephemeral=True)
    except discord.Forbidden:
        await ctx.send(await respuesta_localizada(ctx, "🚫 Sin permisos para expulsar a ese usuario."), ephemeral=True)


@bot.hybrid_command(name="ban", description="[Staff] Banea a un miembro permanentemente")
@commands.has_permissions(ban_members=True)
@app_commands.describe(member="Usuario", reason="Motivo")
async def ban(ctx, member: discord.Member, *, reason: str = "No especificado"):
    msg = await respuesta_localizada(
        ctx, f"⚠️ Escribe `confirmar` en 15 s para banear a **{member.display_name}**, o ignora para cancelar."
    )
    await ctx.send(msg, ephemeral=True)

    def check(m):
        return (
            m.author == ctx.author
            and m.channel == ctx.channel
            and m.content.lower() in ("confirmar", "confirm", "bestätigen", "confirmer", "подтвердить")
        )

    try:
        await bot.wait_for("message", check=check, timeout=15.0)
        await member.ban(reason=reason)
        await log_mod_action(ctx.guild, "BAN", member, ctx.author, reason, discord.Colour.dark_red())
        await ctx.send(await respuesta_localizada(ctx, f"🔨 **{member.display_name}** baneado permanentemente. Motivo: {reason}"), ephemeral=True)
    except asyncio.TimeoutError:
        await ctx.send(await respuesta_localizada(ctx, "⏱️ Ban cancelado."), ephemeral=True)
    except discord.Forbidden:
        await ctx.send(await respuesta_localizada(ctx, "🚫 Sin permisos para banear a ese usuario."), ephemeral=True)


# ─────────────────────────────────────────────
# TEMPBAN — BAN TEMPORAL
# ─────────────────────────────────────────────

@bot.hybrid_command(name="tempban", description="[Staff] Banea temporalmente a un usuario")
@commands.has_permissions(ban_members=True)
@app_commands.describe(member="Usuario", minutos="Duración del ban en minutos", reason="Motivo")
async def tempban(ctx, member: discord.Member, minutos: int, *, reason: str = "No especificado"):
    if minutos < 1:
        await ctx.send(await respuesta_localizada(ctx, "⚠️ La duración debe ser de al menos 1 minuto."), ephemeral=True)
        return
    if any(r.id in STAFF_ROLES for r in member.roles):
        await ctx.send(await respuesta_localizada(ctx, "⚠️ No puedes banear a un miembro del staff."), ephemeral=True)
        return

    unban_at = time.time() + (minutos * 60)
    try:
        await member.ban(reason=f"[TEMPBAN {minutos}min] {reason}")
        db_add_tempban(member.id, ctx.guild.id, unban_at, reason)
        await log_mod_action(
            ctx.guild, "TEMPBAN", member, ctx.author, reason,
            discord.Colour.dark_orange(),
            {"Duración": f"{minutos} min", "Desbaneo": f"<t:{int(unban_at)}:R>"}
        )
        try:
            dm_embed = discord.Embed(
                title="⏳ Has sido baneado temporalmente",
                description=(
                    f"**Servidor:** {ctx.guild.name}\n"
                    f"**Motivo:** {reason}\n"
                    f"**Duración:** {minutos} minutos\n"
                    f"**Desbaneo automático:** <t:{int(unban_at)}:R>"
                ),
                colour=discord.Colour.orange(),
            )
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        msg = await respuesta_localizada(
            ctx,
            f"⏳ **{member.display_name}** baneado por **{minutos} minutos**. "
            f"Desbaneo automático <t:{int(unban_at)}:R>. Motivo: {reason}"
        )
        await ctx.send(msg, ephemeral=True)
    except discord.Forbidden:
        await ctx.send(await respuesta_localizada(ctx, "🚫 Sin permisos para banear a ese usuario."), ephemeral=True)


# ─────────────────────────────────────────────
# UNBAN — DESBANEAR
# ─────────────────────────────────────────────

@bot.hybrid_command(name="unban", description="[Staff] Desbanea a un usuario por su ID")
@commands.has_permissions(ban_members=True)
@app_commands.describe(user_id="ID del usuario a desbanear", reason="Motivo del desbaneo")
async def unban(ctx, user_id: str, *, reason: str = "No especificado"):
    try:
        uid = int(user_id)
    except ValueError:
        await ctx.send(await respuesta_localizada(ctx, "⚠️ ID inválida. Proporciona una ID numérica de Discord."), ephemeral=True)
        return

    try:
        user = await bot.fetch_user(uid)
        await ctx.guild.unban(user, reason=reason)
        db_remove_tempban(uid, ctx.guild.id)
        await log_mod_action(
            ctx.guild, "UNBAN", user, ctx.author, reason, discord.Colour.green()
        )
        msg = await respuesta_localizada(ctx, f"🔓 **{user}** (`{uid}`) ha sido desbaneado. Motivo: {reason}")
        await ctx.send(msg, ephemeral=True)
    except discord.NotFound:
        await ctx.send(await respuesta_localizada(ctx, "❌ No se encontró ningún ban para ese usuario."), ephemeral=True)
    except discord.Forbidden:
        await ctx.send(await respuesta_localizada(ctx, "🚫 Sin permisos para desbanear."), ephemeral=True)
    except Exception as e:
        log.error(f"Error en unban: {e}")
        await ctx.send(await respuesta_localizada(ctx, "⚠️ Error al intentar desbanear."), ephemeral=True)


# ─────────────────────────────────────────────
# LOCKDOWN — BLOQUEAR CANAL
# ─────────────────────────────────────────────

@bot.hybrid_command(name="lockdown", description="[Staff] Bloquea el canal actual para los miembros")
@commands.has_permissions(manage_channels=True)
@app_commands.describe(reason="Motivo del lockdown")
async def lockdown(ctx, *, reason: str = "Sin motivo especificado"):
    es_staff = any(r.id in STAFF_ROLES for r in ctx.author.roles)
    if not es_staff:
        await ctx.send(await respuesta_localizada(ctx, "🚫 Solo el staff puede usar este comando."), ephemeral=True)
        return

    canal = ctx.channel
    try:
        await canal.set_permissions(
            ctx.guild.default_role,
            send_messages=False,
            reason=f"Lockdown por {ctx.author} — {reason}"
        )
        await log_mod_action(
            ctx.guild, "LOCKDOWN", ctx.author, ctx.author, reason,
            discord.Colour.dark_red(), {"Canal": canal.mention}
        )
        embed = discord.Embed(
            title="🔐 Canal bloqueado",
            description=(
                f"Este canal ha sido **bloqueado** por el staff.\n\n"
                f"**Motivo:** {reason}\n"
                f"**Moderador:** {ctx.author.mention}\n\n"
                "Los miembros no pueden enviar mensajes hasta que se desbloquee."
            ),
            colour=discord.Colour.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Usa /unlock para desbloquear")
        await canal.send(embed=embed)
        await ctx.send(await respuesta_localizada(ctx, f"🔐 Canal **#{canal.name}** bloqueado. Motivo: {reason}"), ephemeral=True)
    except discord.Forbidden:
        await ctx.send(await respuesta_localizada(ctx, "🚫 Sin permisos para modificar este canal."), ephemeral=True)


# ─────────────────────────────────────────────
# UNLOCK — DESBLOQUEAR CANAL
# ─────────────────────────────────────────────

@bot.hybrid_command(name="unlock", description="[Staff] Desbloquea el canal actual")
@commands.has_permissions(manage_channels=True)
@app_commands.describe(reason="Motivo del desbloqueo")
async def unlock(ctx, *, reason: str = "Lockdown finalizado"):
    es_staff = any(r.id in STAFF_ROLES for r in ctx.author.roles)
    if not es_staff:
        await ctx.send(await respuesta_localizada(ctx, "🚫 Solo el staff puede usar este comando."), ephemeral=True)
        return

    canal = ctx.channel
    try:
        await canal.set_permissions(
            ctx.guild.default_role,
            send_messages=None,
            reason=f"Unlock por {ctx.author} — {reason}"
        )
        await log_mod_action(
            ctx.guild, "UNLOCK", ctx.author, ctx.author, reason,
            discord.Colour.green(), {"Canal": canal.mention}
        )
        embed = discord.Embed(
            title="🔓 Canal desbloqueado",
            description=(
                f"Este canal ha sido **desbloqueado**.\n\n"
                f"**Motivo:** {reason}\n"
                f"**Moderador:** {ctx.author.mention}\n\n"
                "Los miembros pueden volver a enviar mensajes con normalidad."
            ),
            colour=discord.Colour.green(),
            timestamp=datetime.now(timezone.utc),
        )
        await canal.send(embed=embed)
        await ctx.send(await respuesta_localizada(ctx, f"🔓 Canal **#{canal.name}** desbloqueado. Motivo: {reason}"), ephemeral=True)
    except discord.Forbidden:
        await ctx.send(await respuesta_localizada(ctx, "🚫 Sin permisos para modificar este canal."), ephemeral=True)


# ─────────────────────────────────────────────
# POLL — ENCUESTA
# ─────────────────────────────────────────────

@bot.hybrid_command(name="poll", description="[Staff] Crea una encuesta con hasta 4 opciones")
@commands.has_permissions(manage_messages=True)
@app_commands.describe(
    pregunta="La pregunta de la encuesta",
    opcion1="Opción 1",
    opcion2="Opción 2",
    opcion3="Opción 3 (opcional)",
    opcion4="Opción 4 (opcional)",
)
async def poll(
    ctx,
    pregunta: str,
    opcion1: str,
    opcion2: str,
    opcion3: str = None,
    opcion4: str = None,
):
    emojis   = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
    opciones = [opcion1, opcion2]
    if opcion3:
        opciones.append(opcion3)
    if opcion4:
        opciones.append(opcion4)

    descripcion = "\n".join(f"{emojis[i]} {op}" for i, op in enumerate(opciones))

    embed = discord.Embed(
        title=f"📊 {pregunta}",
        description=descripcion,
        colour=discord.Colour.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=f"Encuesta creada por {ctx.author.display_name} • Reacciona para votar")

    await ctx.defer()
    poll_msg = await ctx.channel.send(embed=embed)

    for i in range(len(opciones)):
        await poll_msg.add_reaction(emojis[i])

    try:
        await ctx.send(f"✅ Encuesta publicada: {poll_msg.jump_url}", ephemeral=True)
    except Exception:
        pass

    log.info(f"POLL creado por {ctx.author} | Pregunta: {pregunta}")


# ─────────────────────────────────────────────
# GESTIÓN DE ROLES
# ─────────────────────────────────────────────

@bot.hybrid_command(name="dar_role", description="[Staff] Asigna un rol de staff")
@commands.has_permissions(manage_roles=True)
async def dar_role(ctx, member: discord.Member, role: discord.Role):
    if role.id in STAFF_ROLES:
        await member.add_roles(role)
        await log_mod_action(ctx.guild, "ROLE_ADD", member, ctx.author, f"Rol: {role.name}", discord.Colour.green())
        await ctx.send(await respuesta_localizada(ctx, f"✅ Rol **{role.name}** asignado a {member.mention}."), ephemeral=True)
    else:
        await ctx.send(await respuesta_localizada(ctx, "⚠️ Solo puedo asignar roles de Staff configurados."), ephemeral=True)


@bot.hybrid_command(name="quitar_role", description="[Staff] Quita un rol de staff")
@commands.has_permissions(manage_roles=True)
async def quitar_role(ctx, member: discord.Member, role: discord.Role):
    if role.id in STAFF_ROLES:
        await member.remove_roles(role)
        await log_mod_action(ctx.guild, "ROLE_REMOVE", member, ctx.author, f"Rol: {role.name}", discord.Colour.orange())
        await ctx.send(await respuesta_localizada(ctx, f"❌ Rol **{role.name}** quitado a {member.mention}."), ephemeral=True)
    else:
        await ctx.send(await respuesta_localizada(ctx, "⚠️ No tengo permiso para gestionar ese rol."), ephemeral=True)


@bot.hybrid_command(name="help", description="Solicita ayuda al Staff")
@commands.cooldown(1, 30, commands.BucketType.user)
async def help_cmd(ctx):
    mentions     = " ".join(f"<@&{rid}>" for rid in STAFF_ROLES)
    online_staff = [
        m for m in ctx.guild.members
        if any(r.id in STAFF_ROLES for r in m.roles) and m.status != discord.Status.offline
    ]
    if not online_staff:
        msg = await respuesta_localizada(ctx, f"❌ No hay staff online. Se ha notificado a {mentions}.")
        await ctx.send(msg)
    else:
        msg = await respuesta_localizada(ctx, f"🆘 {mentions}, el usuario {ctx.author.mention} necesita ayuda aquí.")
        await ctx.send(msg)


# ─────────────────────────────────────────────
# AUTOMOD: VIGILANCIA
# ─────────────────────────────────────────────

@bot.hybrid_command(name="activar_avisos", description="[Staff] Activa vigilancia de spam")
@commands.has_permissions(manage_messages=True)
@app_commands.describe(member="Usuario a vigilar")
async def activar_avisos(ctx, member: discord.Member):
    if any(r.id in STAFF_ROLES for r in member.roles):
        await ctx.send(await respuesta_localizada(ctx, "⚠️ No se puede vigilar a un miembro del staff."), ephemeral=True)
        return
    db_set_warns(member.id, 0, True)
    await ctx.send(
        await respuesta_localizada(
            ctx,
            f"🚨 Vigilancia activada para **{member.display_name}**. Próximo spam: **Mute {MUTE_DURACION}min → Kick → Ban**."
        ),
        ephemeral=True
    )


@bot.hybrid_command(name="desactivar_avisos", description="[Staff] Desactiva vigilancia de spam")
@commands.has_permissions(manage_messages=True)
@app_commands.describe(member="Usuario")
async def desactivar_avisos(ctx, member: discord.Member):
    db_delete_warns(member.id)
    spam_notified.discard(member.id)
    await ctx.send(await respuesta_localizada(ctx, f"✅ Vigilancia desactivada para **{member.display_name}**."), ephemeral=True)


@bot.hybrid_command(name="ver_avisos", description="[Staff] Consulta avisos de un usuario")
@commands.has_permissions(manage_messages=True)
@app_commands.describe(member="Usuario")
async def ver_avisos(ctx, member: discord.Member):
    warn_cnt, monitored = db_get_warns(member.id)
    estado = "🔴 En vigilancia" if monitored else "🟢 Sin vigilancia"
    await ctx.send(
        await respuesta_localizada(ctx, f"**{member.display_name}** — {estado} | Avisos: **{warn_cnt}/5**"),
        ephemeral=True
    )


# ─────────────────────────────────────────────
# MANEJO DE ERRORES
# ─────────────────────────────────────────────

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(await respuesta_localizada(ctx, "🚫 No tienes permisos para usar este comando."), ephemeral=True)
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(await respuesta_localizada(ctx, "❌ No encontré ese usuario."), ephemeral=True)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(await respuesta_localizada(ctx, f"⚠️ Falta el argumento: `{error.param.name}`."), ephemeral=True)
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(
            await respuesta_localizada(ctx, f"⏳ Espera **{error.retry_after:.1f}s** antes de usar este comando de nuevo."),
            ephemeral=True
        )
    elif isinstance(error, commands.CommandInvokeError):
        log.error(f"CommandInvokeError: {error.original}")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        log.error(f"Error no manejado: {error}")


bot.run(DISCORD_TOKEN)
