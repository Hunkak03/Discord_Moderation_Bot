<div align="center">

<!-- BANNER -->
<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6,11,20&height=200&section=header&text=Jin%20Sakai%20Bot&fontSize=80&fontColor=fff&animation=twinkling&fontAlignY=35&desc=Discord%20Moderation%20Bot&descAlignY=60&descSize=20" width="100%"/>

<!-- BADGES -->
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discordpy.readthedocs.io)
[![Railway](https://img.shields.io/badge/Hosted%20on-Railway-0B0D0E?style=for-the-badge&logo=railway&logoColor=white)](https://railway.app)
[![Groq](https://img.shields.io/badge/AI-Groq%20LLaMA-F55036?style=for-the-badge&logo=meta&logoColor=white)](https://groq.com)
[![SQLite](https://img.shields.io/badge/Database-SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

<br/>

**[🇪🇸 Español](#-español) · [🇬🇧 English](#-english)**

</div>

---

# 🇪🇸 Español

## 📖 ¿Qué es Jin Sakai Bot?

**Jin Sakai** es un bot de Discord completo para moderación, gestión y asistencia con IA. Diseñado para servidores que necesitan un sistema robusto, persistente y multilingüe — todo en uno.

> 💡 Responde en el idioma del usuario automáticamente gracias a LLaMA 3.3 70B vía Groq.

---

## ✨ Funcionalidades

### 🛡️ Moderación
| Comando | Descripción |
|---|---|
| `/warn @user` | Aviso formal (3→Mute, 4→Kick, 5→Ban automático) |
| `/mute @user [min]` | Mutea temporalmente |
| `/unmute @user` | Quita el mute |
| `/kick @user` | Expulsa del servidor |
| `/ban @user` | Baneo permanente con confirmación |
| `/tempban @user <min>` | Baneo temporal con desbaneo automático |
| `/unban <id>` | Desbanea por ID |
| `/clear [n]` | Borra mensajes del canal |
| `/lockdown` | Bloquea el canal actual |
| `/unlock` | Desbloquea el canal |

### 🎫 Sistema de Tickets
- Botón interactivo para abrir tickets privados
- Solo el dueño del ticket y el staff pueden verlo y cerrarlo
- Logs automáticos al abrir y cerrar

### 🤖 AutoMod
- **Anti-spam**: detecta mensajes en ráfaga y aplica Mute → Kick → Ban progresivo
- **Filtro de palabras**: elimina mensajes con lenguaje prohibido automáticamente
- **Anti-raid**: eleva la verificación del servidor ante entradas masivas y expulsa automáticamente
- **Reacción 🚫**: el staff puede borrar cualquier mensaje reaccionando con 🚫

### 📊 Sistema de Reportes
- Usuarios pueden reportar a otros con motivo
- La IA valida si el reporte es legítimo antes de registrarlo
- Al acumular `MAX_REPORTES` el staff es notificado por DM y en el canal de logs
- Si el staff está offline, la alerta se envía cuando se conecta

### 📜 Historial y Persistencia
- Base de datos **SQLite** — todo persiste entre reinicios
- Historial completo de acciones de moderación por usuario
- Warns, reportes y tempbans guardados permanentemente

### 🌐 Multilingüe con IA
- Detecta automáticamente el idioma del usuario
- Responde en el mismo idioma en todos los comandos
- Chat con IA mencionando al bot (`@Jin Sakai`)

### 👋 Bienvenida Automática
- Mensaje embed en el canal de bienvenida
- DM privado al nuevo miembro con instrucciones

### 📈 Información
| Comando | Descripción |
|---|---|
| `/userinfo [@user]` | Perfil detallado (warns, reportes, historial para staff) |
| `/serverinfo` | Estadísticas del servidor |
| `/avatar [@user]` | Avatar en alta resolución (PNG, JPG, WEBP) |
| `/poll <pregunta> <op1> <op2>` | Encuesta con hasta 4 opciones |
| `/historial @user` | Historial de moderación completo |

---

## ⚙️ Configuración

Edita las siguientes constantes al inicio de `mybot.py`:

```python
CANAL_LOGS       = ID_del_canal_de_logs
CANAL_BIENVENIDA = ID_del_canal_de_bienvenida
CANAL_TICKETS    = ID_del_canal_de_tickets

MAX_REPORTES  = 5   # Reportes para alertar al staff
SPAM_MENSAJES = 5   # Mensajes en X segundos = spam
SPAM_SEGUNDOS = 5
MUTE_DURACION = 10  # Minutos de mute automático
```

---

<br/>

---

# 🇬🇧 English

## 📖 What is Jin Sakai Bot?

**Jin Sakai** is a full-featured Discord bot for moderation, server management, and AI-powered assistance. Built for servers that need a robust, persistent, and multilingual system — all in one.

> 💡 Automatically replies in the user's language using LLaMA 3.3 70B via Groq.

---

## ✨ Features

### 🛡️ Moderation
| Command | Description |
|---|---|
| `/warn @user` | Formal warning (3→Mute, 4→Kick, 5→Ban auto) |
| `/mute @user [min]` | Temporarily mute a member |
| `/unmute @user` | Remove mute |
| `/kick @user` | Kick from server |
| `/ban @user` | Permanent ban with confirmation |
| `/tempban @user <min>` | Temporary ban with auto-unban |
| `/unban <id>` | Unban by user ID |
| `/clear [n]` | Delete messages from channel |
| `/lockdown` | Lock current channel |
| `/unlock` | Unlock current channel |

### 🎫 Ticket System
- Interactive button to open private support tickets
- Only the ticket owner and staff can view and close it
- Automatic logs on open and close

### 🤖 AutoMod
- **Anti-spam**: detects message bursts and applies progressive Mute → Kick → Ban
- **Word filter**: automatically deletes messages with prohibited language
- **Anti-raid**: raises server verification on mass joins and auto-kicks
- **🚫 reaction**: staff can delete any message by reacting with 🚫

### 📊 Report System
- Members can report others with a reason
- AI validates if the report is legitimate before registering it
- On reaching `MAX_REPORTS`, staff are notified via DM and in the logs channel
- If staff is offline, the alert is sent when they come online

### 📜 History & Persistence
- **SQLite** database — everything persists across restarts
- Full moderation action history per user
- Warns, reports and tempbans saved permanently

### 🌐 AI Multilingual
- Automatically detects the user's language
- Replies in the same language across all commands
- AI chat by mentioning the bot (`@Jin Sakai`)

### 👋 Auto Welcome
- Embed message in the welcome channel
- Private DM to new members with instructions

---

## ⚙️ Configuration

Edit the following variables at the beggining of `mybot.py`:

```python
CANAL_LOGS       = ID_del_canal_de_logs
CANAL_BIENVENIDA = ID_del_canal_de_bienvenida
CANAL_TICKETS    = ID_del_canal_de_tickets

MAX_REPORTES  = 5   # Reportes para alertar al staff
SPAM_MENSAJES = 5   # Mensajes en X segundos = spam
SPAM_SEGUNDOS = 5
MUTE_DURACION = 10  # Minutos de mute automático
```

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6,11,20&height=100&section=footer" width="100%"/>

**Made with ❤️ by [Hunkak03](https://github.com/Hunkak03)**

[![GitHub](https://img.shields.io/badge/GitHub-Hunkak03-181717?style=for-the-badge&logo=github)](https://github.com/Hunkak03)

</div>
