# standings_cascade_points.py
# Tabla de posiciones (2 páginas por jugador) con columnas:
# Pos | Equipo | Jugador | Prog(13) | JJ | W | L | Por jugar | Pts
# Reglas: LEAGUE + fecha, filtro (ambos miembros) o (CPU + miembro), dedup por id, ajustes algebraicos.
# Orden: por puntos (desc). Empates: por W (desc), luego L (asc).

import requests, time, re, os, json
from datetime import datetime
from zoneinfo import ZoneInfo   # <<< agregado

# ===== Config general =====

# ===== MODO DE EJECUCIÓN (switch) =====
# Valores posibles: "DEBUG" o "ONLINE"
MODE = "ONLINE"  # ← déjalo en DEBUG para que se comporte igual que ahora

CFG = {
    "DEBUG": dict(
        PRINT_DETAILS=False,
        PRINT_CAPTURE_SUMMARY=True,
        PRINT_CAPTURE_LIST=False,
        DUMP_ENABLED=True,
        STOP_AFTER_N=None,
        DAY_WINDOW_MODE="calendar",   # "hoy" = día calendario
    ),
    "ONLINE": dict(
        PRINT_DETAILS=False,
        PRINT_CAPTURE_SUMMARY=False,
        PRINT_CAPTURE_LIST=False,
        DUMP_ENABLED=False,
        STOP_AFTER_N=None,
        DAY_WINDOW_MODE="sports",     # "hoy" = 06:00–05:59
    ),
}

# === Aplicar la config del modo seleccionado ===
conf = CFG.get(MODE, CFG["DEBUG"])
PRINT_DETAILS = conf["PRINT_DETAILS"]

try:
    PRINT_CAPTURE_SUMMARY
except NameError:
    PRINT_CAPTURE_SUMMARY = conf["PRINT_CAPTURE_SUMMARY"]
else:
    PRINT_CAPTURE_SUMMARY = conf["PRINT_CAPTURE_SUMMARY"]

try:
    PRINT_CAPTURE_LIST
except NameError:
    PRINT_CAPTURE_LIST = conf["PRINT_CAPTURE_LIST"]
else:
    PRINT_CAPTURE_LIST = conf["PRINT_CAPTURE_LIST"]

try:
    DUMP_ENABLED
except NameError:
    DUMP_ENABLED = conf["DUMP_ENABLED"]
else:
    DUMP_ENABLED = conf["DUMP_ENABLED"]

try:
    STOP_AFTER_N
except NameError:
    STOP_AFTER_N = conf["STOP_AFTER_N"]
else:
    STOP_AFTER_N = conf["STOP_AFTER_N"]

DAY_WINDOW_MODE = conf["DAY_WINDOW_MODE"]

API = "https://mlb25.theshow.com/apis/game_history.json"
PLATFORM = "psn"
MODE = "LEAGUE"
SINCE = datetime(2025, 9, 19)
PAGES = (1, 2)
TIMEOUT = 20
RETRIES = 2

# Mostrar detalle por equipo
PRINT_DETAILS = False
STOP_AFTER_N = None

# === Capturas / dumps ===
DUMP_ENABLED = True
DUMP_DIR = "out"
PRINT_CAPTURE_SUMMARY = True
PRINT_CAPTURE_LIST = False

# ===== Liga =====
LEAGUE_ORDER = [
    ("mlbsonoman", "Orioles"),
    ("AV777", "Red Sox"),
    ("L_Sanz7", "Yankees"),
    ("ElChamaquin", "Tigers"),
    ("Dcontreritas", "Royals"),
    ("Bufon3-0", "Twins"),
    ("Amorphis8076", "White Sox"),
    ("lednew__", "Rangers"),
    ("itschinoo02", "Astros"),
    ("JoseAco21", "Braves"),
    ("lnsocial", "Marlins"),
    ("MR TRAMPA PR", "Nationals"),
    ("Papotico013213", "Cubs"),
    ("SARMIENTOFO-SHO", "Brewers"),
    ("Joshe_izarra", "Pirates"),
    ("Francoxico", "Diamondbacks"),
    ("Mayolito7", "Dodgers"),
    ("Juanbrachog", "Padres"),
]

FETCH_ALIASES = {
    "AV777": ["StrikerVJ"],
    "MR TRAMPA PR": ["BENDITOPA"],
    "Papotico013213": ["El asesino03874"],
    "lnsocial": ["lnsociaI", "Insocial", "InsociaI"],
    "X2KDUDE": ["Xx2kdudexX8466"],
    "Francoxico": ["Xxbandiffft", "XxBandido15xX"],
}

TEAM_RECORD_ADJUSTMENTS = {
    "Pirates": (27, 4),
    "Twins": (11, 22),
    "Diamondbacks": (16, 6),
    "Dodgers": (24, 8),
    "Rangers": (9, 22),
    "Red Sox": (9, 22),
    "Royals": (15, 10),
    "Tigers": (14, 10),
    "Braves": (12, 6),
    "Brewers": (9, 10),
    "Cubs": (8, 6),
    "Astros": (7, 4),
    "Padres": (5, 12),
    "Orioles": (6, 14),
    "Yankees": (8, 6),
    "White Sox": (2, 16),
    "Nationals": (5, 3),
    "Guardians": (2, 5),
    "Mets": (3, 9),
    "Marlins": (5, 4),
    "Athletics": (1, 0),
    "Cardinals": (0, 2),
}

TEAM_POINT_ADJUSTMENTS = {}

LEAGUE_USERS = {u for (u, _t) in LEAGUE_ORDER}
for base, alts in FETCH_ALIASES.items():
    LEAGUE_USERS.add(base)
    LEAGUE_USERS.update(alts)
LEAGUE_USERS.update({"AiramReynoso_", "Yosoyreynoso_"})
LEAGUE_USERS_NORM = {u.lower() for u in LEAGUE_USERS}

BXX_RE = re.compile(r"\^(b\d+)\^", flags=re.IGNORECASE)

def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s or "")

def _dump_json(filename: str, data):
    if not DUMP_ENABLED:
        return
    os.makedirs(DUMP_DIR, exist_ok=True)
    path = os.path.join(DUMP_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path

def normalize_user_for_compare(raw: str) -> str:
    if not raw: return ""
    return BXX_RE.sub("", raw).strip().lower()

def is_cpu(raw: str) -> bool:
    return normalize_user_for_compare(raw) == "cpu"

def parse_date(s: str):
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except:
            pass
    return None

def fetch_page(username: str, page: int):
    params = {"username": username, "platform": PLATFORM, "page": page}
    last = None
    for _ in range(RETRIES):
        try:
            r = requests.get(API, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return (r.json() or {}).get("game_history") or []
        except Exception as e:
            last = e
            time.sleep(0.4)
    print(f"[WARN] {username} p{page} sin datos ({last})")
    return []

def dedup_by_id(gs):
    seen = set(); out = []
    for g in gs:
        gid = str(g.get("id") or "")
        if gid and gid in seen:
            continue
        if gid:
            seen.add(gid)
        out.append(g)
    return out

def norm_team(s: str) -> str:
    return (s or "").strip().lower()

# ... (funciones compute_team_record_for_user sin cambios)

# ==========================
# Juegos jugados HOY (Miami)
# ==========================
def games_played_today_scl():
    tz_miami = ZoneInfo("America/New_York")
    tz_utc = ZoneInfo("UTC")
    today_local = datetime.now(tz_miami).date()

    all_pages = []
    for username_exact, _team in LEAGUE_ORDER:
        for p in PAGES:
            all_pages += fetch_page(username_exact, p)

    seen_ids = set()
    seen_keys = set()
    items = []

    for g in dedup_by_id(all_pages):
        if (g.get("game_mode") or "").strip().upper() != MODE:
            continue

        d = parse_date(g.get("display_date", ""))
        if not d:
            continue

        if d.tzinfo is None:
            d = d.replace(tzinfo=tz_utc)
        d_local = d.astimezone(tz_miami)

        if d_local.date() != today_local:
            continue

        home_name_raw = (g.get("home_name") or "")
        away_name_raw = (g.get("away_name") or "")
        h_norm = normalize_user_for_compare(home_name_raw)
        a_norm = normalize_user_for_compare(away_name_raw)
        if not (h_norm in LEAGUE_USERS_NORM and a_norm in LEAGUE_USERS_NORM):
            continue

        gid = str(g.get("id") or "")
        if gid and gid in seen_ids:
            continue

        home = (g.get("home_full_name") or "").strip()
        away = (g.get("away_full_name") or "").strip()
        hr = str(g.get("home_runs") or "0")
        ar = str(g.get("away_runs") or "0")
        pitcher_info = (g.get("display_pitcher_info") or "").strip()

        canon_key = (home, away, hr, ar, pitcher_info)
        if canon_key in seen_keys:
            continue

        if gid:
            seen_ids.add(gid)
        seen_keys.add(canon_key)

        try:
            fecha_hora = d_local.strftime("%d-%m-%Y - %-I:%M %p").lower()
        except Exception:
            fecha_hora = d_local.strftime("%d-%m-%Y - %#I:%M %p").lower()

        items.append((d_local, f"{home} {hr} - {away} {ar}  - {fecha_hora} (hora Miami EEUU-EST)"))

    items.sort(key=lambda x: x[0])
    return [s for _, s in items]

def main():
    os.makedirs(DUMP_DIR, exist_ok=True)
    miami_tz = ZoneInfo("America/New_York")

    take = len(LEAGUE_ORDER) if STOP_AFTER_N is None else min(STOP_AFTER_N, len(LEAGUE_ORDER))
    rows = []
    print(f"Procesando {take} equipos (páginas {PAGES})...\n")
    for i, (user, team) in enumerate(LEAGUE_ORDER[:take], start=1):
        row = compute_team_record_for_user(user, team)
        rows.append(row)

    rows.sort(key=lambda r: (-r["points"], -r["wins"], r["losses"]))
    _dump_json("standings.json", rows)

    print("\nTabla de posiciones")
    for pos, r in enumerate(rows, start=1):
        print(f"{pos:>3} | {r['team']:<19} | {r['user']:<15} | ... | {r['points']:>3}")

    try:
        games_today = games_played_today_scl()
    except Exception as e:
        games_today = []
        print(f"\n[WARN] games_played_today_scl falló: {e}")

    _dump_json("games_today.json", {
        "generated_at": datetime.now(miami_tz).strftime("%Y-%m-%d %H:%M:%S") + " EEUU-EST",
        "items": games_today
    })

    print("\nJuegos jugados HOY (hora Miami EEUU-EST)")
    if not games_today:
        print(" — No hay registros hoy —")
    else:
        for i, s in enumerate(games_today, 1):
            print(f"{i:>2}- {s}")

    print(f"\nÚltima actualización: {datetime.now(miami_tz):%Y-%m-%d %H:%M:%S} EEUU-EST")
    print(f"JSON generados en: .\\{DUMP_DIR}\\")
    print("  - standings.json")
    print("  - games_today.json")

if __name__ == "__main__":
    main()
