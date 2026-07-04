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
import aiohttp
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
        "host": "blaise-pascal.nitro.games",
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
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0a0b0f; --panel: #14161d; --panel2: #191c25; --border: #262a36;
    --text: #eef0f4; --muted: #7d8494; --accent: #7c5cff; --accent2: #22d3ee;
    --online: #22c55e; --offline: #4b5162;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh;
    background:
      radial-gradient(1200px 600px at 10% -10%, rgba(124,92,255,0.18), transparent),
      radial-gradient(900px 500px at 100% 0%, rgba(34,211,238,0.12), transparent),
      var(--bg);
    color: var(--text);
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    padding: 40px 20px 60px;
  }
  .wrap { max-width: 1080px; margin: 0 auto; }
  .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 32px; flex-wrap: wrap; gap: 12px; }
  .title { display: flex; align-items: center; gap: 12px; }
  .title h1 {
    font-size: 26px; margin: 0; font-weight: 800; letter-spacing: -0.02em;
    background: linear-gradient(90deg, #fff, #b9a9ff);
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }
  .logo { font-size: 30px; filter: drop-shadow(0 0 12px rgba(124,92,255,0.6)); }
  .live-pill {
    display: inline-flex; align-items: center; gap: 8px;
    background: var(--panel2); border: 1px solid var(--border);
    padding: 7px 14px; border-radius: 999px; font-size: 12px; color: var(--muted);
  }
  .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--online); position: relative; }
  .pulse::after {
    content: ""; position: absolute; inset: 0; border-radius: 50%;
    background: var(--online); animation: pulse 1.6s ease-out infinite;
  }
  @keyframes pulse { 0% { transform: scale(1); opacity: 0.7; } 100% { transform: scale(2.8); opacity: 0; } }

  .server-block { margin-bottom: 36px; }
  .server-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
  .server-head h2 { font-size: 19px; margin: 0; font-weight: 700; }
  .server-head .host { color: var(--muted); font-size: 13px; font-family: monospace; }

  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 16px; }
  @media (max-width: 760px) { .grid { grid-template-columns: 1fr; } }

  .stat-card {
    background: linear-gradient(160deg, var(--panel2), var(--panel));
    border: 1px solid var(--border); border-radius: 16px; padding: 20px;
    position: relative; overflow: hidden;
  }
  .stat-card .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; font-weight: 700; margin-bottom: 8px; }
  .stat-card .value { font-size: 32px; font-weight: 800; letter-spacing: -0.02em; }
  .stat-card .value.online { color: var(--online); }
  .stat-card .glow {
    position: absolute; width: 140px; height: 140px; border-radius: 50%; filter: blur(50px);
    background: var(--accent); opacity: .18; top: -50px; right: -50px;
  }

  .panel {
    background: var(--panel); border: 1px solid var(--border); border-radius: 16px;
    padding: 22px 24px; margin-bottom: 16px;
  }
  .panel h3 { margin: 0 0 16px; font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; font-weight: 700; }

  .players-row { display: flex; flex-wrap: wrap; gap: 10px; }
  .player-chip {
    display: flex; align-items: center; gap: 8px;
    background: var(--panel2); border: 1px solid var(--border);
    padding: 6px 14px 6px 6px; border-radius: 999px; font-size: 13px; font-weight: 600;
    cursor: pointer; transition: transform .15s, border-color .15s;
  }
  .player-chip:hover { transform: translateY(-2px); border-color: var(--accent); }
  .player-chip img { width: 24px; height: 24px; border-radius: 6px; image-rendering: pixelated; }
  .player-chip .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--online); margin-left: 2px; }

  .modal-overlay {
    display: none; position: fixed; inset: 0; background: rgba(5,6,10,0.7);
    backdrop-filter: blur(4px); z-index: 50; align-items: center; justify-content: center; padding: 20px;
  }
  .modal-overlay.open { display: flex; }
  .modal-card {
    background: linear-gradient(160deg, var(--panel2), var(--panel));
    border: 1px solid var(--border); border-radius: 20px; padding: 28px;
    max-width: 360px; width: 100%; position: relative; text-align: center;
  }
  .modal-close {
    position: absolute; top: 14px; right: 14px; width: 28px; height: 28px;
    border-radius: 8px; border: 1px solid var(--border); background: var(--panel2);
    color: var(--muted); cursor: pointer; font-size: 16px; line-height: 1;
  }
  .modal-close:hover { color: var(--text); }
  .modal-card .skin-render { width: 130px; image-rendering: pixelated; filter: drop-shadow(0 8px 20px rgba(0,0,0,0.5)); margin: 6px 0 12px; }
  .modal-card .name { font-size: 20px; font-weight: 800; margin-bottom: 2px; }
  .modal-card .uuid { color: var(--muted); font-size: 11px; font-family: monospace; margin-bottom: 18px; word-break: break-all; }
  .modal-status { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 700; padding: 5px 12px; border-radius: 999px; margin-bottom: 18px; }
  .modal-status.on { background: rgba(34,197,94,0.15); color: var(--online); }
  .modal-status.off { background: rgba(75,81,98,0.25); color: var(--muted); }
  .modal-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; text-align: left; }
  .modal-stat { background: var(--panel2); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; }
  .modal-stat .k { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 4px; }
  .modal-stat .v { font-size: 16px; font-weight: 700; }
  .modal-loading { color: var(--muted); font-size: 13px; padding: 30px 0; }
  .empty { color: var(--muted); font-style: italic; font-size: 13px; }

  canvas { max-height: 260px; }

  .updated { color: var(--muted); font-size: 12px; text-align: center; margin-top: 28px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <div class="title">
      <span class="logo">🎮</span>
      <h1>Player Tracker</h1>
    </div>
    <div class="live-pill"><span class="pulse"></span> Live</div>
  </div>
  <div id="content"></div>
  <div class="updated" id="updated"></div>
</div>

<div class="modal-overlay" id="modal-overlay" onclick="if(event.target===this) closeModal()">
  <div class="modal-card" id="modal-card">
    <button class="modal-close" onclick="closeModal()">✕</button>
    <div class="modal-loading">Chargement...</div>
  </div>
</div>
<script>
const charts = {};

function fmtDuree(sec) {
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return h + "h" + String(m).padStart(2, "0");
  if (m > 0) return m + "m";
  return sec + "s";
}

function avatarUrl(name) {
  return `https://mc-heads.net/avatar/${encodeURIComponent(name)}/48`;
}

function ensureServerDOM(nom) {
  if (document.getElementById(`server-${nom}`)) return;
  const block = document.createElement("div");
  block.className = "server-block";
  block.id = `server-${nom}`;
  block.innerHTML = `
    <div class="server-head">
      <h2>${nom}</h2>
      <span class="host"></span>
    </div>
    <div class="grid">
      <div class="stat-card"><div class="glow"></div><div class="label">Joueurs en ligne</div><div class="value online" id="v-online-${nom}">0</div></div>
      <div class="stat-card"><div class="glow"></div><div class="label">Total connexions</div><div class="value" id="v-connexions-${nom}">0</div></div>
      <div class="stat-card"><div class="glow"></div><div class="label">Joueur le + actif</div><div class="value" id="v-top-${nom}" style="font-size:20px">-</div></div>
    </div>
    <div class="panel">
      <h3>Joueurs connectés</h3>
      <div class="players-row" id="players-${nom}"></div>
    </div>
    <div class="panel">
      <h3>Temps de jeu total (top 10)</h3>
      <canvas id="chart-playtime-${nom}"></canvas>
    </div>
    <div class="panel">
      <h3>Activité par heure de la journée</h3>
      <canvas id="chart-hourly-${nom}"></canvas>
    </div>
  `;
  document.getElementById("content").appendChild(block);
}

function chartDefaults() {
  return {
    scales: {
      x: { ticks: { color: "#7d8494", font: { size: 11 } }, grid: { color: "#20232d" } },
      y: { ticks: { color: "#7d8494", font: { size: 11 } }, grid: { color: "#20232d" }, beginAtZero: true }
    },
    plugins: { legend: { display: false } },
    maintainAspectRatio: false,
    responsive: true
  };
}

function renderPlaytimeChart(nom, data) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]).slice(0, 10);
  const ctx = document.getElementById(`chart-playtime-${nom}`);
  const labels = entries.map(e => e[0]);
  const values = entries.map(e => Math.round(e[1] / 60));
  const key = `playtime-${nom}`;

  if (charts[key]) {
    charts[key].data.labels = labels;
    charts[key].data.datasets[0].data = values;
    charts[key].update();
    return;
  }
  const gradient = ctx.getContext("2d").createLinearGradient(0, 0, 0, 260);
  gradient.addColorStop(0, "#7c5cff");
  gradient.addColorStop(1, "#22d3ee");
  charts[key] = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ data: values, backgroundColor: gradient, borderRadius: 8, maxBarThickness: 34 }] },
    options: {
      ...chartDefaults(),
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => fmtDuree(c.raw * 60) } } },
      onClick: (evt, elements) => {
        if (elements.length > 0) openModal(labels[elements[0].index]);
      },
      onHover: (evt, elements) => { evt.native.target.style.cursor = elements.length ? "pointer" : "default"; }
    }
  });
}

function renderHourlyChart(nom, data) {
  const labels = Object.keys(data).sort((a, b) => a - b).map(h => h + "h");
  const values = Object.keys(data).sort((a, b) => a - b).map(h => data[h]);
  const key = `hourly-${nom}`;
  const ctx = document.getElementById(`chart-hourly-${nom}`);

  if (charts[key]) {
    charts[key].data.datasets[0].data = values;
    charts[key].update();
    return;
  }
  const gradient = ctx.getContext("2d").createLinearGradient(0, 0, 0, 260);
  gradient.addColorStop(0, "rgba(124,92,255,0.5)");
  gradient.addColorStop(1, "rgba(124,92,255,0.02)");
  charts[key] = new Chart(ctx, {
    type: "line",
    data: { labels, datasets: [{ data: values, borderColor: "#7c5cff", backgroundColor: gradient, fill: true, tension: 0.35, pointRadius: 0, borderWidth: 2 }] },
    options: chartDefaults()
  });
}

async function refresh() {
  try {
    const res = await fetch("/api/stats");
    const data = await res.json();

    for (const [nom, s] of Object.entries(data)) {
      ensureServerDOM(nom);
      document.querySelector(`#server-${nom} .host`).textContent = s.host;

      document.getElementById(`v-online-${nom}`).textContent = s.online_count;

      const totalConnexions = Object.values(s.connexions_par_joueur).reduce((a, b) => a + b, 0);
      document.getElementById(`v-connexions-${nom}`).textContent = totalConnexions;

      const top = Object.entries(s.temps_total_par_joueur).sort((a, b) => b[1] - a[1])[0];
      document.getElementById(`v-top-${nom}`).textContent = top ? top[0] : "-";

      const playersDiv = document.getElementById(`players-${nom}`);
      playersDiv.innerHTML = s.online_players.length > 0
        ? s.online_players.map(p => `<div class="player-chip" onclick="openModal('${p.replace(/'/g, "\\'")}')"><img src="${avatarUrl(p)}" onerror="this.style.display='none'"><span>${p}</span><span class="dot"></span></div>`).join("")
        : `<div class="empty">Personne en ligne pour le moment</div>`;

      renderPlaytimeChart(nom, s.temps_total_par_joueur);
      renderHourlyChart(nom, s.connexions_par_heure);
    }

    document.getElementById("updated").textContent = "Mis à jour à " + new Date().toLocaleTimeString("fr-FR");
  } catch (e) {
    document.getElementById("content").innerHTML = `<div class="panel empty">Erreur de chargement des données</div>`;
  }
}

function fmtDate(ts) {
  if (!ts) return "Inconnu";
  return new Date(ts * 1000).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
}

async function openModal(name) {
  const overlay = document.getElementById("modal-overlay");
  const card = document.getElementById("modal-card");
  card.innerHTML = `<button class="modal-close" onclick="closeModal()">✕</button><div class="modal-loading">Chargement...</div>`;
  overlay.classList.add("open");

  try {
    const res = await fetch(`/api/player/${encodeURIComponent(name)}`);
    const data = await res.json();
    const st = data.stats;

    card.innerHTML = `
      <button class="modal-close" onclick="closeModal()">✕</button>
      <img class="skin-render" src="https://mc-heads.net/body/${encodeURIComponent(name)}/right" onerror="this.src='https://mc-heads.net/body/MHF_Steve/right'">
      <div class="name">${name}</div>
      <div class="uuid">${data.uuid || "UUID introuvable"}</div>
      ${st
        ? `<div class="modal-status ${st.en_ligne ? 'on' : 'off'}">${st.en_ligne ? '🟢 En ligne maintenant' : '⚫ Hors ligne'}</div>
           <div class="modal-grid">
             <div class="modal-stat"><div class="k">Temps de jeu total</div><div class="v">${fmtDuree(st.temps_total)}</div></div>
             <div class="modal-stat"><div class="k">Connexions</div><div class="v">${st.connexions}</div></div>
             <div class="modal-stat" style="grid-column:span 2"><div class="k">Vu pour la première fois</div><div class="v">${fmtDate(st.premiere_fois_vu)}</div></div>
           </div>`
        : `<div class="empty">Pas encore de données suivies pour ce joueur</div>`
      }
    `;
  } catch (e) {
    card.innerHTML = `<button class="modal-close" onclick="closeModal()">✕</button><div class="empty">Erreur de chargement</div>`;
  }
}

function closeModal() {
  document.getElementById("modal-overlay").classList.remove("open");
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
            "connexions_par_heure": {str(h): s["connexions_par_heure"].get(h, 0) for h in range(24)},
        }
    return web.json_response(data)

async def handle_api_player(request):
    name = request.match_info["name"]

    # Cherche les stats internes du bot pour ce joueur, sur tous les serveurs surveillés
    joueur_stats = None
    for nom, s in states.items():
        # comparaison insensible à la casse (les pseudos Minecraft ne sont pas case-sensitive à l'affichage)
        match = next((p for p in s["temps_total_par_joueur"] if p.lower() == name.lower()), None) \
            or next((p for p in s["connexions_par_joueur"] if p.lower() == name.lower()), None) \
            or next((p for p in s["previously_online"] if p.lower() == name.lower()), None)
        if match:
            temps = s["temps_total_par_joueur"].get(match, 0)
            if match in s["session_start"]:
                temps += time.time() - s["session_start"][match]
            joueur_stats = {
                "serveur": nom,
                "en_ligne": match in s["previously_online"],
                "temps_total": round(temps, 1),
                "connexions": s["connexions_par_joueur"].get(match, 0),
                "premiere_fois_vu": s["first_seen"].get(match),
            }
            break

    # UUID + infos de compte via PlayerDB (API publique tierce, pas de scraping,
    # remplace juste api.mojang.com qui a des règles de cache plus strictes)
    uuid = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://playerdb.co/api/player/minecraft/{name}",
                headers={"User-Agent": "player-tracker-discord-bot"},
                timeout=aiohttp.ClientTimeout(total=4),
            ) as resp:
                if resp.status == 200:
                    payload = await resp.json()
                    if payload.get("code") == "player.found":
                        uuid = payload["data"]["player"]["id"]
    except Exception as e:
        log.warning("Lookup PlayerDB échoué pour %s -> %s", name, e)

    return web.json_response({
        "name": name,
        "uuid": uuid,
        "stats": joueur_stats,
    })

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_api_stats)
    app.router.add_get("/api/player/{name}", handle_api_player)
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
        "first_seen": {},
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
                    "first_seen": dict(s["first_seen"]),
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
                for k, v in s.get("first_seen", {}).items():
                    states[nom]["first_seen"][k] = v
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
                if player not in s["first_seen"]:
                    s["first_seen"][player] = time.time()
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
