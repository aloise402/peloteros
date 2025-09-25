import json, os, sys, time
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import standings_cascade_points_desc as standings
except Exception:
    import standings_cascade_points as standings

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "standings_cache.json")
SCL = ZoneInfo("America/Santiago")

# === Reglas de exclusión existentes (respetadas) ===
EXCLUDE_STRINGS = {
    "Yankees 0 - 0 Mets - 08-09-2025 - 9:40 pm (hora Chile)",
}
EXCLUDE_RULES = [
    {
        "home_team": "Yankees",
        "away_team": "Mets",
        "home_score": 0,
        "away_score": 0,
        "ended_at_local_contains": "08-09-2025 - 9:40"
    }
]

def _should_exclude_game(g):
    if isinstance(g, str):
        return g.strip() in EXCLUDE_STRINGS
    if isinstance(g, dict):
        for rule in EXCLUDE_RULES:
            ok = True
            for k, v in rule.items():
                if k == "ended_at_local_contains":
                    if v not in (g.get("ended_at_local") or ""):
                        ok = False
                        break
                else:
                    if g.get(k) != v:
                        ok = False
                        break
            if ok:
                return True
    return False

# ========= POSTEMPORADA (desde standings.SINCE) =========
def _collect_postseason_games():
    """
    Devuelve TODOS los juegos desde standings.SINCE, filtrando por liga/miembros.
    Salida: lista de dicts: {home_team, away_team, home_score, away_score, ended_at_local}
    """
    tz_scl = SCL
    tz_utc = ZoneInfo("UTC")
    valid_teams = {team for (_user, team) in standings.LEAGUE_ORDER}

    # Acumular páginas de usuarios + aliases
    all_pages = []
    for username_exact, _team in standings.LEAGUE_ORDER:
        usernames_to_fetch = [username_exact] + standings.FETCH_ALIASES.get(username_exact, [])
        for uname in usernames_to_fetch:
            for p in standings.PAGES:
                all_pages += standings.fetch_page(uname, p)

    out = []
    seen_ids = set()
    for g in standings.dedup_by_id(all_pages):
        try:
            if (g.get("game_mode") or "").strip().upper() != standings.MODE:
                continue

            d = standings.parse_date(g.get("display_date", ""))
            if not d or d < standings.SINCE:
                continue
            if d.tzinfo is None:
                d = d.replace(tzinfo=tz_utc)
            d_local = d.astimezone(tz_scl)

            home = (g.get("home_full_name") or "").strip()
            away = (g.get("away_full_name") or "").strip()
            if home not in valid_teams or away not in valid_teams:
                continue

            # Miembros vs miembros (o CPU + miembro), igual a tu lógica
            home_name_raw = g.get("home_name", "")
            away_name_raw = g.get("away_name", "")
            h_norm = standings.normalize_user_for_compare(home_name_raw)
            a_norm = standings.normalize_user_for_compare(away_name_raw)
            h_mem = h_norm in standings.LEAGUE_USERS_NORM
            a_mem = a_norm in standings.LEAGUE_USERS_NORM
            if not ((h_mem and a_mem) or (standings.is_cpu(home_name_raw) and a_mem) or (standings.is_cpu(away_name_raw) and h_mem)):
                continue

            gid = str(g.get("id") or "")
            if gid and gid in seen_ids:
                continue
            if gid:
                seen_ids.add(gid)

            hr = int(g.get("home_runs") or 0)
            ar = int(g.get("away_runs") or 0)

            try:
                ended = d_local.strftime("%d-%m-%Y - %-I:%M %p").lower()
            except Exception:
                ended = d_local.strftime("%d-%m-%Y - %#I:%M %p").lower()

            out.append({
                "home_team": home,
                "away_team": away,
                "home_score": hr,
                "away_score": ar,
                "ended_at_local": f"{ended} (hora Chile)"
            })
        except Exception:
            continue

    return out

# ========= Bracket Wild Card (7vs8, 9vs10, WC3) =========
def _build_wildcard_bracket(standings_rows, postseason_games):
    """
    Seeds 7..10 desde standings_rows:
      WC1: 7 vs 8
      WC2: 9 vs 10
      WC3: perdedor WC1 vs ganador WC2
    Marca status/score/winner si ya se jugaron.
    """
    def _row_key(r):
        return (-r.get("points", 0), -r.get("wins", 0), r.get("losses", 0))
    rows = sorted(standings_rows, key=_row_key)

    if len(rows) < 10:
        return [
            {"id": "WC1", "home": "-", "away": "-", "status": "PENDIENTE", "score": "", "winner": None, "loser": None},
            {"id": "WC2", "home": "-", "away": "-", "status": "PENDIENTE", "score": "", "winner": None, "loser": None},
            {"id": "WC3", "home": "Perdedor WC1", "away": "Ganador WC2", "status": "PENDIENTE", "score": "", "winner": None, "loser": None},
        ]

    seed7 = rows[6]["team"]
    seed8 = rows[7]["team"]
    seed9 = rows[8]["team"]
    seed10 = rows[9]["team"]

    wc1 = {"id": "WC1", "home": seed7, "away": seed8, "status": "PENDIENTE", "score": "", "winner": None, "loser": None}
    wc2 = {"id": "WC2", "home": seed9, "away": seed10, "status": "PENDIENTE", "score": "", "winner": None, "loser": None}
    wc3 = {"id": "WC3", "home": "Perdedor WC1", "away": "Ganador WC2", "status": "PENDIENTE", "score": "", "winner": None, "loser": None}

    def _is_match(g, a, b):
        return {g["home_team"], g["away_team"]} == {a, b}

    def _winner_loser(g):
        if g["home_score"] > g["away_score"]:
            return g["home_team"], g["away_team"]
        elif g["away_score"] > g["home_score"]:
            return g["away_team"], g["home_team"]
        return None, None

    # WC1
    g_wc1 = next((g for g in postseason_games if _is_match(g, seed7, seed8)), None)
    if g_wc1:
        wc1["status"] = "JUGADO"
        wc1["score"]  = f"{g_wc1['home_score']}-{g_wc1['away_score']}" if g_wc1["home_team"] == seed7 else f"{g_wc1['away_score']}-{g_wc1['home_score']}"
        w, l = _winner_loser(g_wc1)
        wc1["winner"], wc1["loser"] = w, l

    # WC2
    g_wc2 = next((g for g in postseason_games if _is_match(g, seed9, seed10)), None)
    if g_wc2:
        wc2["status"] = "JUGADO"
        wc2["score"]  = f"{g_wc2['home_score']}-{g_wc2['away_score']}" if g_wc2["home_team"] == seed9 else f"{g_wc2['away_score']}-{g_wc2['home_score']}"
        w, l = _winner_loser(g_wc2)
        wc2["winner"], wc2["loser"] = w, l

    # WC3 = perdedor WC1 vs ganador WC2
    if wc1["loser"] and wc2["winner"]:
        a, b = wc1["loser"], wc2["winner"]
        g_wc3 = next((g for g in postseason_games if _is_match(g, a, b)), None)
        if g_wc3:
            wc3.update({
                "home": g_wc3["home_team"],
                "away": g_wc3["away_team"],
                "status": "JUGADO",
                "score": f"{g_wc3['home_score']}-{g_wc3['away_score']}",
            })
            w, l = _winner_loser(g_wc3)
            wc3["winner"], wc3["loser"] = w, l
        else:
            wc3["home"], wc3["away"] = a, b

    return [wc1, wc2, wc3]

# ========= Bracket de 8 (1–8) tras resolver WC =========
def _build_bracket8(standings_rows, wildcard_bracket, postseason_games):
    """
    QF: 1–8, 2–7, 3–6, 4–5 (seed 7 = ganador WC1, seed 8 = ganador WC3).
    Marca PENDIENTE/JUGADO/EN CURSO en base a juegos ya disputados y muestra último score si existe.
    """
    def _row_key(r):
        return (-r.get("points", 0), -r.get("wins", 0), r.get("losses", 0))
    rows = sorted(standings_rows, key=_row_key)

    # Seeds base
    if len(rows) < 6:
        return None
    seed1, seed2, seed3, seed4, seed5, seed6 = [rows[i]["team"] for i in range(6)]

    # Seeds 7 y 8 desde WC
    wc_index = {g["id"]: g for g in (wildcard_bracket or [])}
    seed7_final = (wc_index.get("WC1") or {}).get("winner") or "Ganador WC1"
    seed8_final = (wc_index.get("WC3") or {}).get("winner") or "Ganador WC3"

    def _find_games(a, b):
        return [g for g in postseason_games if {g["home_team"], g["away_team"]} == {a, b}]

    def _status_for_pair(a, b):
        games = _find_games(a, b)
        if not games:
            return "PENDIENTE", ""
        # último juego
        last = games[-1]
        if last["home_team"] == a:
            score = f'{last["home_score"]}-{last["away_score"]}'
        else:
            score = f'{last["away_score"]}-{last["home_score"]}'
        # si hay ≥1 juego, marcamos JUGADO (si asumes series 1 juego) o EN CURSO (si BO3/BO5)
        # Aquí dejamos EN CURSO por defecto, cambia a JUGADO si quieres 1 partido.
        return "EN CURSO", score

    qf = [
        {"id": "QF1", "home": seed1, "away": seed8_final},
        {"id": "QF2", "home": seed2, "away": seed7_final},
        {"id": "QF3", "home": seed3, "away": seed6},
        {"id": "QF4", "home": seed4, "away": seed5},
    ]
    for m in qf:
        s, sc = _status_for_pair(m["home"], m["away"])
        m["status"] = s
        m["score"] = sc

    bracket8 = {
        "quarters": qf,
        "semis": [
            {"id": "SF1", "from": ["QF1","QF2"], "status": "PENDIENTE"},
            {"id": "SF2", "from": ["QF3","QF4"], "status": "PENDIENTE"},
        ],
        "final": {"id": "F1", "from": ["SF1","SF2"], "status": "PENDIENTE"}
    }
    return bracket8

def update_data_cache():
    ts = datetime.now(SCL).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{ts}] Iniciando actualización del cache...")
    try:
        if not hasattr(standings, "compute_rows"):
            raise AttributeError("El módulo no define compute_rows()")
        if not hasattr(standings, "games_played_today_scl"):
            raise AttributeError("El módulo no define games_played_today_scl()")

        # Standings
        rows = standings.compute_rows()

        # Juegos de hoy (SCL) → se mantienen tus exclusiones
        games_today = standings.games_played_today_scl()
        games_today = [g for g in games_today if not _should_exclude_game(g)]

        # Postemporada completa desde SINCE
        postseason_games = _collect_postseason_games()

        # Bracket Wild Card (L→R)
        wildcard_bracket = _build_wildcard_bracket(rows, postseason_games)

        # Bracket 8 equipos (1–8)
        bracket8 = _build_bracket8(rows, wildcard_bracket, postseason_games)

        payload = {
            "standings": rows,
            "games_today": games_today,
            "postseason_games": postseason_games,   # lista de dicts
            "wildcard_bracket": wildcard_bracket,   # lista [WC1, WC2, WC3]
            "bracket8": bracket8,                   # dict con quarters/semis/final
            "last_updated": ts
        }

        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        print("Actualización completada exitosamente.")
        return True
    except Exception as e:
        print(f"ERROR durante la actualización del cache: {e}")
        return False

def _run_once_then_exit():
    ok = update_data_cache()
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    if "--once" in sys.argv or os.getenv("RUN_ONCE") == "1":
        _run_once_then_exit()
    UPDATE_INTERVAL_SECONDS = int(os.getenv("UPDATE_INTERVAL_SECONDS", "300"))
    while True:
        update_data_cache()
        print(f"Esperando {UPDATE_INTERVAL_SECONDS} segundos para la próxima actualización...")
        try:
            time.sleep(UPDATE_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("Detenido por el usuario.")
            break
