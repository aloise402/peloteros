# standings_cascade_points_desc.py
# Tabla de posiciones con columna K y juegos jugados hoy (Chile)

import requests, time, re, os, json
from datetime import datetime
from zoneinfo import ZoneInfo

# ===== Configuración =====
MIN_JJ = 12                  # mínimo de JJ para participación legal (K)
STANDINGS_OFFLINE = False    # False = standings desde API (en vivo)
GAMES_TODAY_ONLINE = True    # True = juegos de hoy desde API (en vivo)

API = "https://mlb25.theshow.com/apis/game_history.json"
PLATFORM = "psn"
LEAGUE_MODE = "LEAGUE"
SINCE = datetime(2025, 9, 17)

# 👇 Escaneo de 20 páginas por jugador
PAGES = tuple(range(1, 2))  # (1..20)
TIMEOUT = 20
RETRIES = 2

DUMP_DIR = "out"

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
    "Francoxico": ["Xxbandiffft", "XxBandido15xX"],
}

# ===== Ajustes manuales =====
TEAM_RECORD_ADJUSTMENTS = {
    "Pirates": (26, 4),
    "Twins": (11, 22),
    "Diamondbacks": (16, 6),
    "Dodgers": (20, 8),
    "Rangers": (8, 22),
    "Red Sox": (9, 21),
    "Royals": (15, 10),
    "Tigers": (14, 10),
    "Braves": (12, 6),
    "Brewers": (9, 10),
    "Cubs": (8, 5),
    "Astros": (7, 4),
    "Padres": (5, 10),
    "Orioles": (5, 13),
    "Yankees": (8, 6),
    "White Sox": (2, 16),
    "Nationals": (5, 3),
    "Marlins": (5, 4),


}
TEAM_POINT_ADJUSTMENTS = {
    # ejemplo: "Yankees": (3, "Bono disciplina"),
}

LEAGUE_USERS = {u for (u, _t) in LEAGUE_ORDER}
for base, alts in FETCH_ALIASES.items():
    LEAGUE_USERS.add(base)
    LEAGUE_USERS.update(alts)
LEAGUE_USERS.update({"AiramReynoso_", "Yosoyreynoso_"})
LEAGUE_USERS_NORM = {u.lower() for u in LEAGUE_USERS}

BXX_RE = re.compile(r"\^(b\d+)\^", flags=re.IGNORECASE)

# ===== Utils =====
def _dump_json(filename: str, data):
    os.makedirs(DUMP_DIR, exist_ok=True)
    with open(os.path.join(DUMP_DIR, filename), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _parse_date(s: str):
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except:
            pass
    return None

def _fetch_page(username: str, page: int):
    params = {"username": username, "platform": PLATFORM, "page": page}
    last = None
    for _ in range(RETRIES):
        try:
            r = requests.get(API, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return (r.json() or {}).get("game_history") or []
        except Exception as e:
            last = e
            time.sleep(0.3)
    print(f"[WARN] {username} p{page} sin datos ({last})")
    return []

def _dedup_by_id(gs):
    seen = set(); out = []
    for g in gs:
        gid = str(g.get("id") or "")
        if gid and gid in seen:
            continue
        if gid: seen.add(gid)
        out.append(g)
    return out

def _norm_team(s: str) -> str:
    return (s or "").strip().lower()

def normalize_user_for_compare(raw: str) -> str:
    if not raw: return ""
    return BXX_RE.sub("", raw).strip().lower()

# ===== Standings =====
def compute_team_record_for_user(username_exact: str, team_name: str):
    if STANDINGS_OFFLINE:
        scheduled = 42
        played = wins = losses = 0
        remaining = 42
        points = 0
        k_value = max(0, MIN_JJ - played)
        return {
            "user": username_exact,
            "team": team_name,
            "scheduled": scheduled,
            "played": played,
            "wins": wins,
            "losses": losses,
            "remaining": remaining,
            "points": points,
            "points_base": points,
            "points_extra": 0,
            "points_reason": "",
            "K": k_value,
        }

    # 1) Traer datos de la API
    pages_raw = []
    usernames_to_fetch = [username_exact] + FETCH_ALIASES.get(username_exact, [])
    for uname in usernames_to_fetch:
        for p in PAGES:
            pages_raw += _fetch_page(uname, p)
    pages = _dedup_by_id(pages_raw)

    # 2) Filtrar juegos de la liga
    considered = []
    for g in pages:
        if (g.get("game_mode") or "").strip().upper() != LEAGUE_MODE:
            continue
        d = _parse_date(g.get("display_date",""))
        if not d or d < SINCE: 
            continue
        home = (g.get("home_full_name") or "").strip()
        away = (g.get("away_full_name") or "").strip()
        if _norm_team(team_name) not in (_norm_team(home), _norm_team(away)):
            continue
        considered.append(g)

    # 3) Contar W/L
    wins = losses = 0
    for g in considered:
        hr = (g.get("home_display_result") or "").strip().upper()
        ar = (g.get("away_display_result") or "").strip().upper()
        if hr == "W":
            winner = (g.get("home_full_name") or "").strip().lower()
        elif ar == "W":
            winner = (g.get("away_full_name") or "").strip().lower()
        else:
            continue
        if winner == _norm_team(team_name): wins += 1
        else: losses += 1

    # 4) Aplicar ajustes manuales de W/L
    adj_w, adj_l = TEAM_RECORD_ADJUSTMENTS.get(team_name, (0, 0))
    wins_adj = wins + adj_w
    losses_adj = losses + adj_l

    # 5) Calcular puntos
    scheduled = 34
    played = wins_adj + losses_adj
    remaining = max(scheduled - played, 0)

    points_base = 2*wins_adj + losses_adj
    pts_extra, pts_reason = TEAM_POINT_ADJUSTMENTS.get(team_name, (0, ""))
    points_final = points_base + pts_extra

    # 6) Calcular K
    k_value = max(0, MIN_JJ - played)

    return {
        "user": username_exact,
        "team": team_name,
        "scheduled": scheduled,
        "played": played,
        "wins": wins_adj,
        "losses": losses_adj,
        "remaining": remaining,
        "points": points_final,
        "points_base": points_base,
        "points_extra": pts_extra,
        "points_reason": pts_reason,
        "K": k_value,
    }

def compute_rows():
    rows = []
    for idx, (user_exact, team_name) in enumerate(LEAGUE_ORDER, start=1):
        row = compute_team_record_for_user(user_exact, team_name)
        rows.append(row)
        # 👇 Progreso en consola
        print(f"[{idx:02}] {row['team']:<15} ({row['user']:<15}) "
              f"JJ={row['played']:>2} W={row['wins']:>2} L={row['losses']:>2} "
              f"Pts={row['points']:>2} K={row['K']}")
    rows.sort(key=lambda r: (-r.get("points", 0), -r.get("wins", 0), r.get("losses", 0)))
    return rows

# ===== Juegos de hoy =====
def games_played_today_scl():
    if not GAMES_TODAY_ONLINE:
        return []
    tz_scl = ZoneInfo("America/Santiago")
    tz_utc = ZoneInfo("UTC")
    today_local = datetime.now(tz_scl).date()

    users = [u for (u, _t) in LEAGUE_ORDER]
    all_pages = []
    for uname in users:
        for p in PAGES:
            all_pages += _fetch_page(uname, p)

    items = []
    for g in _dedup_by_id(all_pages):
        if (g.get("game_mode") or "").strip().upper() != LEAGUE_MODE:
            continue
        d = _parse_date(g.get("display_date", ""))
        if not d:
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=tz_utc)
        d_local = d.astimezone(tz_scl)
        if d_local.date() != today_local:
            continue

        # Solo miembros de la liga
        h_norm = normalize_user_for_compare(g.get("home_name",""))
        a_norm = normalize_user_for_compare(g.get("away_name",""))
        if not (h_norm in LEAGUE_USERS_NORM and a_norm in LEAGUE_USERS_NORM):
            continue

        home = (g.get("home_full_name") or "").strip()
        away = (g.get("away_full_name") or "").strip()
        hr = str(g.get("home_runs") or "0")
        ar = str(g.get("away_runs") or "0")

        try:
            fecha = d_local.strftime("%d-%m-%Y")
            hora = d_local.strftime("%-I:%M %p").lower()
        except Exception:
            fecha = d_local.strftime("%d-%m-%Y")
            hora = d_local.strftime("%#I:%M %p").lower()

        s = f"{home} {hr} - {away} {ar}  - {fecha} - {hora} (hora Chile)"
        items.append(s)

    items.sort()
    return items

# ===== Main de prueba local =====
def main():
    os.makedirs(DUMP_DIR, exist_ok=True)
    rows = compute_rows()
    _dump_json("standings.json", rows)
    games = games_played_today_scl()
    _dump_json("games_today.json", {"items": games, "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

    print("\nLeyenda: K = 13 - JJ (si el resultado es negativo, se muestra 0)")

if __name__ == "__main__":
    main()
