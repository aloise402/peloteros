import requests, time, re, os, json
from datetime import datetime

MODE = "ONLINE"

CFG = {
    "DEBUG": dict(
        PRINT_DETAILS=False,
        PRINT_CAPTURE_SUMMARY=True,
        PRINT_CAPTURE_LIST=False,
        DUMP_ENABLED=True,
        STOP_AFTER_N=None,
        DAY_WINDOW_MODE="calendar",
    ),
    "ONLINE": dict(
        PRINT_DETAILS=False,
        PRINT_CAPTURE_SUMMARY=False,
        PRINT_CAPTURE_LIST=False,
        DUMP_ENABLED=False,
        STOP_AFTER_N=None,
        DAY_WINDOW_MODE="sports",
    ),
}

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
SINCE = datetime(2025, 9, 24)
PAGES = (1, 2, 3)
TIMEOUT = 20
RETRIES = 2

PRINT_DETAILS = False
STOP_AFTER_N = None
DUMP_ENABLED = True
DUMP_DIR = "out"
PRINT_CAPTURE_SUMMARY = True
PRINT_CAPTURE_LIST = False

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
    "Twins": (11, 23),
    "Diamondbacks": (14, 9),
    "Dodgers": (23, 9),
    "Rangers": (10, 24),
    "Red Sox": (8, 21),
    "Royals": (16, 11),
    "Tigers": (16, 9),
    "Braves": (22, 8),
    "Brewers": (8, 11),
    "Cubs": (9, 7),
    "Astros": (7, 6),
    "Padres": (5, 12),
    "Orioles": (6, 15),
    "Yankees": (13, 9),
    "White Sox": (2, 17),
    "Nationals": (5, 3),
    "Marlins": (6, 4),
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

def compute_team_record_for_user(username_exact: str, team_name: str):
    pages_raw = []
    usernames_to_fetch = [username_exact] + FETCH_ALIASES.get(username_exact, [])
    for uname in usernames_to_fetch:
        for p in PAGES:
            page_items = fetch_page(uname, p)
            pages_raw += page_items
            if PRINT_CAPTURE_LIST:
                for g in page_items:
                    print(f"    [cap] {uname} p{p} id={g.get('id')}  {g.get('away_full_name','')} @ {g.get('home_full_name','')}  {g.get('display_date','')}")
    pages_dedup = dedup_by_id(pages_raw)
    considered = []
    for g in pages_dedup:
        if (g.get("game_mode") or "").strip().upper() != MODE:
            continue
        d = parse_date(g.get("display_date",""))
        if not d or d < SINCE:
            continue
        home = (g.get("home_full_name") or "").strip()
        away = (g.get("away_full_name") or "").strip()
        if norm_team(team_name) not in (norm_team(home), norm_team(away)):
            continue
        home_name_raw = g.get("home_name","")
        away_name_raw = g.get("away_name","")
        h_norm = normalize_user_for_compare(home_name_raw)
        a_norm = normalize_user_for_compare(away_name_raw)
        h_mem = h_norm in LEAGUE_USERS_NORM
        a_mem = a_norm in LEAGUE_USERS_NORM
        if not ( (h_mem and a_mem) or (is_cpu(home_name_raw) and a_mem) or (is_cpu(away_name_raw) and h_mem) ):
            continue
        considered.append(g)
    if PRINT_CAPTURE_SUMMARY:
        print(f"    [capturas] {team_name} ({username_exact}): raw={len(pages_raw)}  dedup={len(pages_dedup)}  considerados={len(considered)}")
    if DUMP_ENABLED:
        base = _safe_name(username_exact)
        _dump_json(f"{base}_raw.json", pages_raw)
        _dump_json(f"{base}_dedup.json", pages_dedup)
        _dump_json(f"{base}_considered.json", considered)
    wins = losses = 0
    detail_lines = []
    for g in considered:
        home = (g.get("home_full_name") or "").strip()
        away = (g.get("away_full_name") or "").strip()
        hr = (g.get("home_display_result") or "").strip().upper()
        ar = (g.get("away_display_result") or "").strip().upper()
        dt = g.get("display_date","")
        if hr == "W":
            win, lose = home, away
        elif ar == "W":
            win, lose = away, home
        else:
            continue
        if norm_team(win) == norm_team(team_name):
            wins += 1
        elif norm_team(lose) == norm_team(team_name):
            losses += 1
        if PRINT_DETAILS:
            detail_lines.append(f"{dt}  {away} @ {home} -> ganó {win}")
    adj_w, adj_l = TEAM_RECORD_ADJUSTMENTS.get(team_name, (0, 0))
    wins_adj, losses_adj = wins + adj_w, losses + adj_l
    scheduled = 34
    played = max(wins_adj + losses_adj, 0)
    remaining = max(scheduled - played, 0)
    points_base = 2 * wins_adj + 1 * losses_adj
    pts_extra, pts_reason = TEAM_POINT_ADJUSTMENTS.get(team_name, (0, ""))
    points_final = points_base + pts_extra
    return {
        "user": username_exact,
        "team": team_name,
        "scheduled": scheduled,
        "played": played,
        "wins": wins_adj,
        "losses": losses_adj,
        "remaining": remaining,
        "k": max(0, 12 - played),
        "points": points_final,
        "points_base": points_base,
        "points_extra": pts_extra,
        "points_reason": pts_reason,
        "detail": detail_lines,
    }

def main():
    os.makedirs(DUMP_DIR, exist_ok=True)
    take = len(LEAGUE_ORDER) if STOP_AFTER_N is None else min(STOP_AFTER_N, len(LEAGUE_ORDER))
    rows = []
    print(f"Procesando {take} equipos (páginas {PAGES})...\n")
    for i, (user, team) in enumerate(LEAGUE_ORDER[:take], start=1):
        print(f"[{i}/{take}] {team} ({user})...")
        row = compute_team_record_for_user(user, team)
        rows.append(row)
        adj_note = f" (ajuste pts {row['points_extra']}: {row['points_reason']})" if row["points_extra"] else ""
        print(f"  => {row['team']}: {row['wins']}-{row['losses']} (Pts {row['points']}){adj_note}\n")
    rows.sort(key=lambda r: (-r["points"], -r["wins"], r["losses"]))
    _dump_json("standings.json", rows)
    print("\nTabla de posiciones")
    print("Pos | Equipo            | Jugador         | Prog |  JJ |  W |  L | P.Jugar | Pts")
    print("----+-------------------+-----------------+------+-----+----+----+---------+----")
    for pos, r in enumerate(rows, start=1):
        print(f"{pos:>3} | {r['team']:<19} | {r['user']:<15} | {r['scheduled']:>4} | {r['played']:>3} | "
              f"{r['wins']:>2} | {r['losses']:>2} | {r['remaining']:>7} | {r['points']:>3}")
    notes = [r for r in rows if r["points_extra"]]
    if notes:
        print("\nNotas de puntos (ajustes manuales):")
        for r in notes:
            signo = "+" if r["points_extra"] > 0 else ""
            print(f" - {r['team']}: {signo}{r['points_extra']} — {r['points_reason']}")
    try:
        games_today = games_played_today_scl()
    except Exception as e:
        games_today = []
        print(f"\n[WARN] games_played_today_scl falló: {e}")
    _dump_json("games_today.json", {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": games_today
    })
    print("\nJuegos jugados HOY (hora Chile)")
    if not games_today:
        print(" — No hay registros hoy —")
    else:
        for i, s in enumerate(games_today, 1):
            print(f"{i:>2}- {s}")
    print(f"\nÚltima actualización: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"JSON generados en: .\\{DUMP_DIR}\\")
    print("  - standings.json")
    print("  - games_today.json")
    print("  - <usuario>_raw.json / _dedup.json / _considered.json")

if __name__ == "__main__":
    main()


def compute_rows():
    func = (
        globals().get("compute_team_record_for_user")
        or globals().get("compute_team_record")
        or globals().get("build_team_row")
        or globals().get("team_row_for_user")
    )
    if not func:
        raise RuntimeError("No encuentro una función para construir filas por equipo.")
    if "LEAGUE_ORDER" not in globals():
        raise RuntimeError("LEAGUE_ORDER no existe en standings_cascade_points_desc.py")
    rows = []
    for user_exact, team_name in LEAGUE_ORDER:
        rows.append(func(user_exact, team_name))
    rows.sort(key=lambda r: (-r.get("points", 0), -r.get("wins", 0), r.get("losses", 0)))
    return rows


def games_played_today_scl():
    tz_scl = ZoneInfo("America/Santiago")
    tz_utc = ZoneInfo("UTC")
    all_pages = []
    for username_exact, _team in LEAGUE_ORDER:
        for p in PAGES:
            all_pages += fetch_page(username_exact, p)
    seen_ids = set()
    seen_keys = set()
    items = []
    valid_teams = {team for (_user, team) in LEAGUE_ORDER}
    for g in dedup_by_id(all_pages):
        if (g.get("game_mode") or "").strip().upper() != MODE:
            continue
        d = parse_date(g.get("display_date", ""))
        if not d:
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=tz_utc)
        d_local = d.astimezone(tz_scl)
        # ✅ ya no filtramos por fecha: devolvemos todos los juegos acumulados
        home = (g.get("home_full_name") or "").strip()
        away = (g.get("away_full_name") or "").strip()
        if home not in valid_teams or away not in valid_teams:
            continue
        gid = str(g.get("id") or "")
        if gid and gid in seen_ids:
            continue
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
        items.append((d_local, f"{home} {hr} - {away} {ar}  - {fecha_hora} (hora Chile)"))
    items.sort(key=lambda x: x[0])
    return [s for _, s in items]
