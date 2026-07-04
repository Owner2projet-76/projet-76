import discord
import asyncio
import os
import time
import json
import io
import logging
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from aiohttp import web
from mcstatus import JavaServer
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("player-tracker")

TOKEN = os.environ["DISCORD_TOKEN"]

# SAVE_FILE : configurable via la variable d'env DATA_FILE.
# Par défaut on écrit à côté du bot, dans un dossier "data" créé automatiquement,
# ce qui marche partout (local, Railway, Render, VPS...).
# Si ta plateforme a un vrai volume persistant monté sur /data, mets
# DATA_FILE=/data/data.json dans les variables d'environnement.
SAVE_FILE = os.environ.get("DATA_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "data.json"))
os.makedirs(os.path.dirname(SAVE_FILE), exist_ok=True)

SERVEURS = {
    "blaise-pascal": {
        "host": "blaise-pascal.mine.fun",
        "port": 25565,
        "channels": {
            "alertes": 1499796586014707885,
            "rapports": 1499796588200198286,
            "statistiques": 1499796592188854292,
            "graphiques": 1500582748770009108,
            "joueurs_surveilles": 1499796600728326436,
        }
    }
    # Pour ajouter un autre serveur plus tard, duplique un bloc ci-dessus avec
    # une nouvelle clé, son host/port, et des IDs de salons Discord différents.
}


CHANNEL_COMMANDES = 1499796590112538874

intents = discord.Intents.default()
intents.message_content = True
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Player Tracker</title>
<style>
  :root {
    --bg: #0f1115; --panel: #171a21; --border: #262a33;
    --text: #e6e8eb; --muted: #8b93a1; --accent: #5865F2; --online: #3ba55d;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    padding: 32px 20px;
  }
  .wrap { max-width: 920px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 28px; }
  .card {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px 24px; margin-bottom: 20px;
  }
  .card h2 { font-size: 15px; margin: 0 0 16px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }
  .server-title { font-size: 18px; font-weight: 700; margin-bottom: 2px; }
  .server-host { color: var(--muted); font-size: 13px; margin-bottom: 16px; }
  .online-badge {
    display: inline-flex; align-items: center; gap: 6px;
    background: rgba(59,165,93,0.15); color: var(--online);
    padding: 4px 12px; border-radius: 20px; font-size: 13px; font-weight: 600;
  }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--online); }
  .players { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
  .chip { background: #21252e; border: 1px solid var(--border); padding: 6px 14px; border-radius: 8px; font-size: 14px; }
  .empty { color: var(--muted); font-style: italic; font-size: 14px; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { text-align: left; padding: 8px 10px; font-size: 14px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; }
  .bar-row { display: flex; align-items: center; gap: 10px; margin: 10px 0; }
  .bar-label { width: 120px; font-size: 13px; flex-shrink: 0; }
  .bar-track { flex: 1; background: #21252e; border-radius: 6px; height: 18px; overflow: hidden; }
  .bar-fill { height: 100%; background: var(--accent); border-radius: 6px; }
  .bar-value { width: 70px; text-align: right; font-size: 12px; color: var(--muted); flex-shrink: 0; }
  .updated { color: var(--muted); font-size: 12px; text-align: center; margin-top: 20px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>🎮 Player Tracker</h1>
  <div class="sub">Surveillance en temps réel</div>
  <div id="content"></div>
  <div class="updated" id="updated"></div>
</div>
<script>
function fmtDuree(sec) {
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return h + "h" + String(m).padStart(2, "0") + "m";
  if (m > 0) return m + "m";
  return sec + "s";
}

async function refresh() {
  try {
    const res = await fetch("/api/stats");
    const data = await res.json();
    const content = document.getElementById("content");
    content.innerHTML = "";

    for (const [nom, s] of Object.entries(data)) {
      const card = document.createElement("div");
      card.className = "card";

      let html = `<div class="server-title">${nom}</div>`;
      html += `<div class="server-host">${s.host}</div>`;
      html += s.online_count > 0
        ? `<span class="online-badge"><span class="dot"></span>${s.online_count} joueur(s) en ligne</span>`
        : `<span class="online-badge" style="background:rgba(139,147,161,0.15);color:var(--muted)"><span class="dot" style="background:var(--muted)"></span>Aucun joueur en ligne</span>`;

      if (s.online_players.length > 0) {
        html += `<div class="players">` + s.online_players.map(p => `<div class="chip">🟢 ${p}</div>`).join("") + `</div>`;
      }

      const entries = Object.entries(s.temps_total_par_joueur).sort((a, b) => b[1] - a[1]).slice(0, 10);
      html += `<h2 style="margin-top:24px">Temps de jeu total (top 10)</h2>`;
      if (entries.length === 0) {
        html += `<div class="empty">Pas encore de données</div>`;
      } else {
        const max = Math.max(...entries.map(e => e[1]));
        html += entries.map(([player, sec]) => `
          <div class="bar-row">
            <div class="bar-label">${player}</div>
            <div class="bar-track"><div class="bar-fill" style="width:${max > 0 ? (sec / max * 100) : 0}%"></div></div>
            <div class="bar-value">${fmtDuree(sec)}</div>
          </div>`).join("");
      }

      const connexions = Object.entries(s.connexions_par_joueur).sort((a, b) => b[1] - a[1]).slice(0, 10);
      html += `<h2 style="margin-top:24px">Nombre de connexions</h2>`;
      if (connexions.length === 0) {
        html += `<div class="empty">Pas encore de données</div>`;
      } else {
        html += `<table><tr><th>Joueur</th><th>Connexions</th></tr>` +
          connexions.map(([p, c]) => `<tr><td>${p}</td><td>${c}</td></tr>`).join("") + `</table>`;
      }

      card.innerHTML = html;
      content.appendChild(card);
    }

    document.getElementById("updated").textContent = "Mis à jour à " + new Date().toLocaleTimeString("fr-FR");
  } catch (e) {
    document.getElementById("content").innerHTML = `<div class="card empty">Erreur de chargement des données</div>`;
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""

async def handle_index(request):
    return web.Response(text=DASHBOARD_HTML, content_type="text/html")

async def handle_api_stats(request):
    data = {}
    for nom, cfg in SERVEURS.items():
        s = states[nom]
        temps_live = dict(s["temps_total_par_joueur"])
        for player, start in s["session_start"].items():
            temps_live[player] = temps_live.get(player, 0) + (time.time() - start)
        data[nom] = {
            "host": cfg["host"],
            "online_players": sorted(s["previously_online"]),
            "online_count": len(s["previously_online"]),
            "connexions_par_joueur": dict(s["connexions_par_joueur"]),
            "temps_total_par_joueur": {k: round(v, 1) for k, v in temps_live.items()},
        }
    return web.json_response(data)

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_api_stats)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("Dashboard web démarré sur le port %s", port)

client = discord.Client(intents=intents)

states = {
    nom: {
        "previously_online": set(),
        "session_start": {},
        "players_this_hour": set(),
        "connexions_par_joueur": defaultdict(int),
        "connexions_par_heure": defaultdict(int),
        "temps_total_par_joueur": defaultdict(float),
    }
    for nom in SERVEURS
}

trackers = {}
hourly_subscribers = []

def sauvegarder():
    try:
        data = {
            "trackers": {k: v for k, v in trackers.items()},
            "hourly_subscribers": hourly_subscribers,
            "states": {
                nom: {
                    "connexions_par_joueur": dict(s["connexions_par_joueur"]),
                    "connexions_par_heure": {str(k): v for k, v in s["connexions_par_heure"].items()},
                    "temps_total_par_joueur": dict(s["temps_total_par_joueur"]),
                }
                for nom, s in states.items()
            }
        }
        # écriture "atomique" : fichier temporaire puis renommage, pour ne jamais
        # corrompre data.json si le bot est coupé en pleine écriture.
        tmp_file = SAVE_FILE + ".tmp"
        with open(tmp_file, "w") as f:
            json.dump(data, f)
        os.replace(tmp_file, SAVE_FILE)
    except Exception:
        log.exception("Échec de la sauvegarde des données")

def charger():
    global trackers, hourly_subscribers
    if not os.path.exists(SAVE_FILE):
        return
    try:
        with open(SAVE_FILE, "r") as f:
            data = json.load(f)
        trackers = {k: [tuple(e) for e in v] for k, v in data.get("trackers", {}).items()}
        hourly_subscribers = [tuple(e) for e in data.get("hourly_subscribers", [])]
        for nom, s in data.get("states", {}).items():
            if nom in states:
                for k, v in s.get("connexions_par_joueur", {}).items():
                    states[nom]["connexions_par_joueur"][k] = v
                for k, v in s.get("connexions_par_heure", {}).items():
                    states[nom]["connexions_par_heure"][int(k)] = v
                for k, v in s.get("temps_total_par_joueur", {}).items():
                    states[nom]["temps_total_par_joueur"][k] = v
        log.info("Données chargées depuis %s", SAVE_FILE)
    except Exception:
        log.exception("Échec du chargement des données, on repart de zéro")

async def get_players(host, port):
    try:
        # .lookup() reproduit le comportement du client Minecraft : si l'adresse
        # ne contient pas de port explicite, il vérifie d'abord un enregistrement
        # DNS SRV avant de se rabattre sur default_port. Beaucoup d'hébergeurs
        # avec sous-domaine (comme ici) redirigent uniquement via un SRV, sans
        # enregistrement A direct sur le sous-domaine -> JavaServer(host, port)
        # échouait avec "No address associated with hostname".
        server = await asyncio.to_thread(JavaServer.lookup, host)
        status = await asyncio.to_thread(server.status)
        if status.players.sample:
            return {p.name for p in status.players.sample}, status.players.online
        return set(), status.players.online
    except Exception as e:
        log.warning("Impossible de joindre %s -> %s", host, e)
        return set(), 0

def format_duree(secondes):
    secondes = int(secondes)
    h = secondes // 3600
    m = (secondes % 3600) // 60
    s = secondes % 60
    if h > 0:
        return f"{h}h{m:02d}m"
    elif m > 0:
        return f"{m}m{s:02d}s"
    else:
        return f"{s}s"

def generer_graphiques(nom_serveur):
    s = states[nom_serveur]
    fichiers = []
    bg = "#2C2F33"
    bg2 = "#23272A"
    text_color = "#DCDDDE"
    plt.rcParams.update({
        'figure.facecolor': bg, 'axes.facecolor': bg2,
        'axes.edgecolor': '#40444B', 'axes.labelcolor': text_color,
        'xtick.color': text_color, 'ytick.color': text_color,
        'text.color': text_color, 'grid.color': '#40444B', 'grid.linewidth': 0.5,
    })

    if s["connexions_par_joueur"]:
        top = sorted(s["connexions_par_joueur"].items(), key=lambda x: x[1], reverse=True)[:10]
        noms, vals = zip(*top)
        fig, ax = plt.subplots(figsize=(10, 5))
        bars = ax.barh(noms, vals, color="#5865F2", height=0.6)
        for bar, val in zip(bars, vals):
            ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height()/2, str(val), va='center', fontsize=11, color=text_color)
        ax.set_xlabel("Connexions")
        ax.set_title(f"Connexions par joueur — {nom_serveur}", fontsize=14, fontweight='bold', pad=15)
        ax.invert_yaxis()
        ax.grid(axis='x', alpha=0.3)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=120, bbox_inches='tight')
        buf.seek(0)
        fichiers.append(("connexions_joueurs.png", buf))
        plt.close()

    if s["temps_total_par_joueur"]:
        top_temps = sorted(s["temps_total_par_joueur"].items(), key=lambda x: x[1], reverse=True)[:10]
        noms, vals = zip(*top_temps)
        vals_heures = [v / 3600 for v in vals]
        labels = [format_duree(v) for v in vals]
        fig, ax = plt.subplots(figsize=(10, 5))
        bars = ax.barh(noms, vals_heures, color="#FAA61A", height=0.6)
        for bar, label in zip(bars, labels):
            ax.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height()/2, label, va='center', fontsize=11, color=text_color)
        ax.set_xlabel("Heures de jeu")
        ax.set_title(f"Temps de jeu — {nom_serveur}", fontsize=14, fontweight='bold', pad=15)
        ax.invert_yaxis()
        ax.grid(axis='x', alpha=0.3)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=120, bbox_inches='tight')
        buf.seek(0)
        fichiers.append(("temps_jeu.png", buf))
        plt.close()

    heures = list(range(24))
    vals = [s["connexions_par_heure"].get(h, 0) for h in heures]
    labels_h = [f"{str(h).zfill(2)}h" for h in heures]
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.fill_between(heures, vals, alpha=0.3, color="#3BA55C")
    ax.plot(heures, vals, color="#3BA55C", linewidth=2.5, marker='o', markersize=5)
    ax.set_xticks(heures)
    ax.set_xticklabels(labels_h, rotation=45, fontsize=9)
    ax.set_ylabel("Connexions")
    ax.set_title(f"Activité par heure — {nom_serveur}", fontsize=14, fontweight='bold', pad=15)
    ax.grid(axis='y', alpha=0.3)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=120, bbox_inches='tight')
    buf.seek(0)
    fichiers.append(("activite_heures.png", buf))
    plt.close()
    return fichiers

async def envoyer_graphiques(nom_serveur):
    channel_id = SERVEURS[nom_serveur]["channels"]["graphiques"]
    channel = client.get_channel(channel_id)
    if not channel:
        return
    fichiers = await asyncio.to_thread(generer_graphiques, nom_serveur)
    await channel.send(f"📊 **Graphiques — {nom_serveur}**")
    for nom, buf in fichiers:
        await channel.send(file=discord.File(buf, filename=nom))

async def envoyer_stats_quotidiennes(nom_serveur):
    s = states[nom_serveur]
    channel_stats = client.get_channel(SERVEURS[nom_serveur]["channels"]["statistiques"])
    if not channel_stats:
        return
    top_str = "\n".join(f"**{i+1}.** {p} — {n} connexion(s)" for i, (p, n) in enumerate(sorted(s["connexions_par_joueur"].items(), key=lambda x: x[1], reverse=True)[:5])) or "Aucune donnée"
    heures_str = "\n".join(f"**{h}h00** — {n} connexion(s)" for h, n in sorted(s["connexions_par_heure"].items(), key=lambda x: x[1], reverse=True)[:3]) or "Aucune donnée"
    temps_str = "\n".join(f"**{i+1}.** {p} — {format_duree(t)}" for i, (p, t) in enumerate(sorted(s["temps_total_par_joueur"].items(), key=lambda x: x[1], reverse=True)[:5])) or "Aucune donnée"
    total = sum(s["connexions_par_joueur"].values())
    embed = discord.Embed(title=f"Rapport quotidien — {nom_serveur}", color=0x5865F2)
    embed.add_field(name="Joueurs les plus actifs", value=top_str, inline=False)
    embed.add_field(name="Temps de jeu total", value=temps_str, inline=False)
    embed.add_field(name="Heures de pointe", value=heures_str, inline=False)
    embed.add_field(name="Total connexions", value=f"**{total}** connexion(s)", inline=False)
    await channel_stats.send(embed=embed)
    await envoyer_graphiques(nom_serveur)
    s["connexions_par_joueur"].clear()
    s["connexions_par_heure"].clear()
    s["temps_total_par_joueur"].clear()
    sauvegarder()

# ─── MODALS ───────────────────────────────────────────────────────────────────

class TrackerModal(discord.ui.Modal, title="Tracker un joueur"):
    pseudo = discord.ui.TextInput(label="Pseudo du joueur", placeholder="Ex: Notch")
    serveur = discord.ui.TextInput(label="Serveur", placeholder="cobblemon ou lego974")

    async def on_submit(self, interaction: discord.Interaction):
        pseudo = self.pseudo.value.strip()
        nom_serveur = self.serveur.value.strip().lower()
        if nom_serveur not in SERVEURS:
            await interaction.response.send_message(f"Serveur inconnu. Disponibles : {', '.join(SERVEURS.keys())}", ephemeral=True)
            return
        key = pseudo.lower()
        if key not in trackers:
            trackers[key] = []
        entry = (interaction.user.id, nom_serveur)
        if entry not in trackers[key]:
            trackers[key].append(entry)
        sauvegarder()
        ch = client.get_channel(SERVEURS[nom_serveur]["channels"]["joueurs_surveilles"])
        if ch:
            await ch.send(f"+ **{pseudo}** ajouté par <@{interaction.user.id}>")
        await interaction.response.send_message(f"Tu seras pingé quand **{pseudo}** se connecte sur **{nom_serveur}** !", ephemeral=True)

class UntrackSelect(discord.ui.Select):
    def __init__(self, user_id, actifs):
        options = [
            discord.SelectOption(label=f"{p} — {s}", value=f"{p}|{s}")
            for p, s in actifs[:25]
        ]
        super().__init__(placeholder="Choisir un tracker à supprimer...", options=options)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        pseudo, nom_serveur = self.values[0].split("|")
        key = pseudo.lower()
        if key in trackers:
            trackers[key] = [e for e in trackers[key] if not (e[0] == self.user_id and e[1] == nom_serveur)]
        sauvegarder()
        await interaction.response.send_message(f"Alerte supprimée pour **{pseudo}** sur **{nom_serveur}**.", ephemeral=True)

class UntrackView(discord.ui.View):
    def __init__(self, user_id, actifs):
        super().__init__()
        self.add_item(UntrackSelect(user_id, actifs))

class ServeurSelect(discord.ui.Select):
    def __init__(self, action):
        options = [discord.SelectOption(label=nom, value=nom) for nom in SERVEURS]
        super().__init__(placeholder="Choisir un serveur...", options=options)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        nom_serveur = self.values[0]
        if self.action == "rapport":
            entry = (interaction.user.id, nom_serveur)
            if entry not in hourly_subscribers:
                hourly_subscribers.append(entry)
                sauvegarder()
                await interaction.response.send_message(f"Rapport horaire activé pour **{nom_serveur}** !", ephemeral=True)
            else:
                await interaction.response.send_message(f"Tu es déjà abonné à **{nom_serveur}**.", ephemeral=True)
        elif self.action == "stoprapport":
            entry = (interaction.user.id, nom_serveur)
            if entry in hourly_subscribers:
                hourly_subscribers.remove(entry)
                sauvegarder()
                await interaction.response.send_message(f"Rapport désactivé pour **{nom_serveur}**.", ephemeral=True)
            else:
                await interaction.response.send_message(f"Tu n'étais pas abonné à **{nom_serveur}**.", ephemeral=True)
        elif self.action == "stats":
            await interaction.response.send_message(f"Envoi des stats pour **{nom_serveur}**...", ephemeral=True)
            await envoyer_stats_quotidiennes(nom_serveur)
        elif self.action == "graphique":
            await interaction.response.send_message(f"Envoi des graphiques pour **{nom_serveur}**...", ephemeral=True)
            await envoyer_graphiques(nom_serveur)

class ServeurSelectView(discord.ui.View):
    def __init__(self, action):
        super().__init__()
        self.add_item(ServeurSelect(action))

# ─── PANEL ────────────────────────────────────────────────────────────────────

class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Tracker un joueur", style=discord.ButtonStyle.primary, emoji="🎯", custom_id="panel:tracker")
    async def tracker(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TrackerModal())

    @discord.ui.button(label="Supprimer un tracker", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="panel:untrack")
    async def untrack(self, interaction: discord.Interaction, button: discord.ui.Button):
        actifs = [(k, e[1]) for k, v in trackers.items() for e in v if e[0] == interaction.user.id]
        if not actifs:
            await interaction.response.send_message("Tu n'as aucun tracker actif.", ephemeral=True)
            return
        await interaction.response.send_message("Choisis le tracker à supprimer :", view=UntrackView(interaction.user.id, actifs), ephemeral=True)

    @discord.ui.button(label="Voir les joueurs", style=discord.ButtonStyle.secondary, emoji="👥", custom_id="panel:joueurs")
    async def joueurs(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        msg = ""
        for nom, cfg in SERVEURS.items():
            players, count = await get_players(cfg["host"], cfg["port"])
            if count == 0:
                msg += f"**{nom}** — Aucun joueur connecté\n"
            elif not players:
                msg += f"**{nom}** — {count} joueur(s) (noms masqués)\n"
            else:
                s = states[nom]
                lines = []
                for p in sorted(players):
                    if p in s["session_start"]:
                        duree = time.time() - s["session_start"][p]
                        lines.append(f"• {p} — depuis {format_duree(duree)}")
                    else:
                        lines.append(f"• {p}")
                msg += f"**{nom}** — {count} joueur(s) :\n" + "\n".join(lines) + "\n\n"
        await interaction.followup.send(msg.strip(), ephemeral=True)

    @discord.ui.button(label="Activer rapport horaire", style=discord.ButtonStyle.secondary, emoji="📋", custom_id="panel:rapport")
    async def rapport(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Choisir le serveur :", view=ServeurSelectView("rapport"), ephemeral=True)

    @discord.ui.button(label="Désactiver rapport", style=discord.ButtonStyle.secondary, emoji="🔕", custom_id="panel:stoprapport")
    async def stoprapport(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Choisir le serveur :", view=ServeurSelectView("stoprapport"), ephemeral=True)

    @discord.ui.button(label="Envoyer les stats", style=discord.ButtonStyle.secondary, emoji="📊", custom_id="panel:stats")
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Choisir le serveur :", view=ServeurSelectView("stats"), ephemeral=True)

    @discord.ui.button(label="Envoyer les graphiques", style=discord.ButtonStyle.secondary, emoji="📈", custom_id="panel:graphiques")
    async def graphique(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Choisir le serveur :", view=ServeurSelectView("graphique"), ephemeral=True)

    @discord.ui.button(label="Mes trackers actifs", style=discord.ButtonStyle.secondary, emoji="📌", custom_id="panel:mestrackers")
    async def mes_trackers(self, interaction: discord.Interaction, button: discord.ui.Button):
        actifs = [(k, e[1]) for k, v in trackers.items() for e in v if e[0] == interaction.user.id]
        if actifs:
            liste = "\n".join(f"• **{p}** sur {s}" for p, s in actifs)
            await interaction.response.send_message(f"Tes trackers actifs :\n{liste}", ephemeral=True)
        else:
            await interaction.response.send_message("Tu n'as aucun tracker actif.", ephemeral=True)

# ─── MONITORING ───────────────────────────────────────────────────────────────

async def monitor_serveur(nom_serveur):
    cfg = SERVEURS[nom_serveur]
    s = states[nom_serveur]
    await client.wait_until_ready()
    last_hour = time.time()
    last_day = time.time()

    log.info("Surveillance démarrée pour %s (%s:%s)", nom_serveur, cfg["host"], cfg["port"])

    while not client.is_closed():
        try:
            current_players, count = await get_players(cfg["host"], cfg["port"])
            new_players = current_players - s["previously_online"]
            left_players = s["previously_online"] - current_players

            s["players_this_hour"].update(new_players)
            heure_actuelle = int(time.strftime("%H"))
            channel_alertes = client.get_channel(cfg["channels"]["alertes"])

            for player in new_players:
                s["connexions_par_joueur"][player] += 1
                s["connexions_par_heure"][heure_actuelle] += 1
                s["session_start"][player] = time.time()
                for key, entries in trackers.items():
                    if player.lower() == key:
                        for (user_id, serveur_tracker) in entries:
                            if serveur_tracker == nom_serveur and channel_alertes:
                                await channel_alertes.send(
                                    f"<@{user_id}> **{player}** vient de se connecter sur **{nom_serveur}** ! ({count} joueur(s) en ligne)"
                                )

            for player in left_players:
                if player in s["session_start"]:
                    duree = time.time() - s["session_start"][player]
                    s["temps_total_par_joueur"][player] += duree
                    del s["session_start"][player]
                    if channel_alertes:
                        await channel_alertes.send(f"**{player}** a quitté **{nom_serveur}** — session : **{format_duree(duree)}**")

            if new_players or left_players:
                sauvegarder()

            s["previously_online"] = current_players

            if time.time() - last_hour >= 3600:
                last_hour = time.time()
                nb = len(s["players_this_hour"])
                liste = ", ".join(f"**{p}**" for p in sorted(s["players_this_hour"])) if s["players_this_hour"] else "aucun"
                channel_rapports = client.get_channel(cfg["channels"]["rapports"])
                for (user_id, serveur_tracker) in hourly_subscribers:
                    if serveur_tracker == nom_serveur and channel_rapports:
                        await channel_rapports.send(
                            f"<@{user_id}> Rapport horaire **{nom_serveur}** : **{nb}** joueur(s) → {liste}"
                        )
                s["players_this_hour"] = set()

            if time.time() - last_day >= 86400:
                last_day = time.time()
                await envoyer_stats_quotidiennes(nom_serveur)

        except Exception:
            log.exception("Erreur dans la boucle de surveillance de %s (on continue)", nom_serveur)

        await asyncio.sleep(30)

# ─── EVENTS ───────────────────────────────────────────────────────────────────

bot_started = False

@client.event
async def on_ready():
    global bot_started
    log.info("Bot connecté : %s", client.user)
    if bot_started:
        # on_ready peut être rappelé après une reconnexion réseau ; on ne relance
        # pas les tâches de surveillance ni le rechargement des données à chaque fois.
        return
    bot_started = True
    charger()
    try:
        client.add_view(PanelView())  # rend les boutons du panel cliquables même après un redémarrage
    except Exception:
        log.exception("Impossible d'enregistrer la vue persistante du panel (non bloquant)")
    for nom in SERVEURS:
        client.loop.create_task(monitor_serveur(nom))
    client.loop.create_task(start_webserver())
    log.info("Surveillance lancée pour : %s", ", ".join(SERVEURS))

@client.event
async def on_error(event, *args, **kwargs):
    log.exception("Erreur non gérée dans l'event %s", event)

@client.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id != CHANNEL_COMMANDES:
        return

    content = message.content.strip()
    channel_commandes = client.get_channel(CHANNEL_COMMANDES)

    if content == "!panel":
        embed = discord.Embed(
            title="Panel de contrôle",
            description="Utilise les boutons ci-dessous pour contrôler le bot.",
            color=0x5865F2
        )
        embed.add_field(name="Serveurs surveillés", value="\n".join(f"• **{nom}**" for nom in SERVEURS), inline=False)
        await channel_commandes.send(embed=embed, view=PanelView())

    elif content == "!aide":
        aide = (
            "**Commandes disponibles :**\n"
            "`!panel` → ouvrir le panel interactif\n"
            "`!joueurs` → voir qui est connecté\n"
            "`!tracker <pseudo> <serveur>` → tracker un joueur\n"
            "`!untrack <pseudo> <serveur>` → arrêter de suivre\n"
            "`!trackers` → voir tes alertes actives\n"
            "`!rapport <serveur>` → activer le rapport horaire\n"
            "`!stoprapport <serveur>` → désactiver le rapport\n"
            "`!stats <serveur>` → envoyer les stats\n"
            "`!graphique <serveur>` → envoyer les graphiques\n\n"
            f"Serveurs : {', '.join(SERVEURS.keys())}"
        )
        await channel_commandes.send(aide)

    elif content == "!joueurs":
        for nom, cfg in SERVEURS.items():
            players, count = await get_players(cfg["host"], cfg["port"])
            if count == 0:
                await channel_commandes.send(f"**{nom}** — Aucun joueur connecté.")
            elif not players:
                await channel_commandes.send(f"**{nom}** — {count} joueur(s) en ligne (noms masqués).")
            else:
                s = states[nom]
                lines = []
                for p in sorted(players):
                    if p in s["session_start"]:
                        duree = time.time() - s["session_start"][p]
                        lines.append(f"• {p} — depuis **{format_duree(duree)}**")
                    else:
                        lines.append(f"• {p}")
                await channel_commandes.send(f"**{nom}** — {count} joueur(s) :\n" + "\n".join(lines))

    elif content.startswith("!tracker "):
        parts = content[9:].strip().split(" ")
        if len(parts) < 2:
            await channel_commandes.send("Usage : `!tracker <pseudo> <serveur>`")
            return
        pseudo, nom_serveur = parts[0], parts[1].lower()
        if nom_serveur not in SERVEURS:
            await channel_commandes.send(f"Serveur inconnu. Disponibles : {', '.join(SERVEURS.keys())}")
            return
        key = pseudo.lower()
        if key not in trackers:
            trackers[key] = []
        entry = (message.author.id, nom_serveur)
        if entry not in trackers[key]:
            trackers[key].append(entry)
        sauvegarder()
        await channel_commandes.send(f"Tu seras pingé quand **{pseudo}** se connecte sur **{nom_serveur}**.")
        ch = client.get_channel(SERVEURS[nom_serveur]["channels"]["joueurs_surveilles"])
        if ch:
            await ch.send(f"+ **{pseudo}** ajouté par <@{message.author.id}>")

    elif content.startswith("!untrack "):
        parts = content[9:].strip().split(" ")
        if len(parts) < 2:
            await channel_commandes.send("Usage : `!untrack <pseudo> <serveur>`")
            return
        pseudo, nom_serveur = parts[0], parts[1].lower()
        key = pseudo.lower()
        if key in trackers:
            trackers[key] = [e for e in trackers[key] if not (e[0] == message.author.id and e[1] == nom_serveur)]
        sauvegarder()
        await channel_commandes.send(f"Alerte désactivée pour **{pseudo}** sur **{nom_serveur}**.")

    elif content == "!trackers":
        actifs = [(k, e[1]) for k, v in trackers.items() for e in v if e[0] == message.author.id]
        if actifs:
            liste = "\n".join(f"• **{p}** sur {s}" for p, s in actifs)
            await channel_commandes.send(f"Tes alertes actives :\n{liste}")
        else:
            await channel_commandes.send("Tu n'as aucune alerte active.")

    elif content.startswith("!rapport "):
        nom_serveur = content[9:].strip().lower()
        if nom_serveur not in SERVEURS:
            await channel_commandes.send(f"Serveur inconnu. Disponibles : {', '.join(SERVEURS.keys())}")
            return
        entry = (message.author.id, nom_serveur)
        if entry not in hourly_subscribers:
            hourly_subscribers.append(entry)
            sauvegarder()
            await channel_commandes.send(f"Rapport horaire activé pour **{nom_serveur}**.")
        else:
            await channel_commandes.send("Tu es déjà abonné.")

    elif content.startswith("!stoprapport "):
        nom_serveur = content[13:].strip().lower()
        entry = (message.author.id, nom_serveur)
        if entry in hourly_subscribers:
            hourly_subscribers.remove(entry)
            sauvegarder()
            await channel_commandes.send(f"Rapport désactivé pour **{nom_serveur}**.")
        else:
            await channel_commandes.send("Tu n'étais pas abonné.")

    elif content.startswith("!stats "):
        nom_serveur = content[7:].strip().lower()
        if nom_serveur not in SERVEURS:
            await channel_commandes.send(f"Serveur inconnu. Disponibles : {', '.join(SERVEURS.keys())}")
            return
        await envoyer_stats_quotidiennes(nom_serveur)
        await channel_commandes.send(f"Stats envoyées pour **{nom_serveur}** !")

    elif content.startswith("!graphique "):
        nom_serveur = content[11:].strip().lower()
        if nom_serveur not in SERVEURS:
            await channel_commandes.send(f"Serveur inconnu. Disponibles : {', '.join(SERVEURS.keys())}")
            return
        await envoyer_graphiques(nom_serveur)
        await channel_commandes.send(f"Graphiques envoyés pour **{nom_serveur}** !")

client.run(TOKEN, log_handler=None)
