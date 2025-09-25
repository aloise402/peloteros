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
    Salida (orden cronológico de captura): lista de dicts:
      {home_team, away_team, home_score, away_score, ended_at_local}
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

# ========= Utilidades de series =========
def _pair_key(a, b):
    return tuple(sorted([a, b]))

def _series_summary(a, b, games, best_of):
    """
    Cuenta victorias por pareja (a vs b) con lista 'games' (dicts).
    best_of = 1/5/7 => wins_needed=1/3/4
    Devuelve: dict(status, series_score, wins_a, wins_b, total, winner)
    """
    wins_needed = {1: 1, 5: 3, 7: 4}[best_of]
    wins_a = wins_b = 0
    for g in games:
        if _pair_key(g["home_team"], g["away_team"]) != _pair_key(a, b):
            continue
        if g["home_score"] > g["away_score"]:
            w = g["home_team"]
        elif g["away_score"] > g["home_score"]:
            w = g["away_team"]
        else:
            continue
        if w == a:
            wins_a += 1
        elif w == b:
            wins_b += 1
    total = wins_a + wins_b
    if total == 0:
        status = "PENDIENTE"
        winner = None
    elif wins_a >= wins_needed:
        status = "JUGADO"
        winner = a
    elif wins_b >= wins_needed:
        status = "JUGADO"
        winner = b
    else:
        status = "EN CURSO"
        winner = None
    return {
        "status": status,
        "series_score": f"{wins_a}-{wins_b}",
        "wins_a": wins_a,
        "wins_b": wins_b,
        "total": total,
        "winner": winner,
        "wins_needed": wins_needed
    }

# ========= Wild Card (7vs8, 9vs10, WC3) =========
def _build_wildcard_bracket(standings_rows, postseason_games):
    """
    Seeds 7..10 desde standings_rows:
      WC1: 7 vs 8 (Bo1)
      WC2: 9 vs 10 (Bo1)
      WC3: perdedor WC1 vs ganador WC2 (Bo1)
    """
    def _row_key(r):
        return (-r.get("points", 0), -r.get("wins", 0), r.get("losses", 0))
    rows = sorted(standings_rows, key=_row_key)
    if len(rows) < 10:
        return [
            {"id": "WC1", "home": "-", "away": "-", "status": "PENDIENTE", "score": "", "winner": None, "loser": None, "best_of": 1},
            {"id": "WC2", "home": "-", "away": "-", "status": "PENDIENTE", "score": "", "winner": None, "loser": None, "best_of": 1},
            {"id": "WC3", "home": "Perdedor WC1", "away": "Ganador WC2", "status": "PENDIENTE", "score": "", "winner": None, "loser": None, "best_of": 1},
        ]

    seed7 = rows[6]["team"]; seed8 = rows[7]["team"]; seed9 = rows[8]["team"]; seed10 = rows[9]["team"]

    wc1 = {"id": "WC1", "home": seed7, "away": seed8, "status": "PENDIENTE", "score": "", "winner": None, "loser": None, "best_of": 1}
    wc2 = {"id": "WC2", "home": seed9, "away": seed10, "status": "PENDIENTE", "score": "", "winner": None, "loser": None, "best_of": 1}
    wc3 = {"id": "WC3", "home": "Perdedor WC1", "away": "Ganador WC2", "status": "PENDIENTE", "score": "", "winner": None, "loser": None, "best_of": 1}

    def _last_score_for(a, b):
        # Para Bo1: si existe ≥1 juego tomamos el más reciente y formamos score A-perspectiva
        last = None
        for g in postseason_games:
            if _pair_key(g["home_team"], g["away_team"]) == _pair_key(a, b):
                last = g
        if last:
            if last["home_team"] == a:
                return f"{last['home_score']}-{last['away_score']}"
            else:
                return f"{last['away_score']}-{last['home_score']}"
        return ""

    # WC1
    s1 = _series_summary(seed7, seed8, postseason_games, best_of=1)
    wc1["status"] = s1["status"]
    wc1["score"] = _last_score_for(seed7, seed8)
    if s1["winner"]:
        wc1["winner"] = s1["winner"]
        wc1["loser"] = seed8 if s1["winner"] == seed7 else seed7

    # WC2
    s2 = _series_summary(seed9, seed10, postseason_games, best_of=1)
    wc2["status"] = s2["status"]
    wc2["score"] = _last_score_for(seed9, seed10)
    if s2["winner"]:
        wc2["winner"] = s2["winner"]
        wc2["loser"] = seed10 if s2["winner"] == seed9 else seed9

    # WC3
    if wc1["loser"] and wc2["winner"]:
        a, b = wc1["loser"], wc2["winner"]
        wc3["home"], wc3["away"] = a, b
        s3 = _series_summary(a, b, postseason_games, best_of=1)
        wc3["status"] = s3["status"]
        wc3["score"] = _last_score_for(a, b)
        if s3["winner"]:
            wc3["winner"] = s3["winner"]
            wc3["loser"] = b if s3["winner"] == a else a

    return [wc1, wc2, wc3]

# ========= Bracket de 8 (1–8) con Bo5/Bo5/Bo7 =========
def _build_bracket8(standings_rows, wildcard_bracket, postseason_games):
    """
    QF (Bo5): 1–8, 2–7, 3–6, 4–5
    SF (Bo5): ganador QF1 vs ganador QF2, ganador QF3 vs ganador QF4
    F  (Bo7): ganador SF1 vs ganador SF2
    """
    def _row_key(r):
        return (-r.get("points", 0), -r.get("wins", 0), r.get("losses", 0))
    rows = sorted(standings_rows, key=_row_key)

    if len(rows) < 6:
        return None

    seed1, seed2, seed3, seed4, seed5, seed6 = [rows[i]["team"] for i in range(6)]
    wc_index = {g["id"]: g for g in (wildcard_bracket or [])}
    seed7_final = (wc_index.get("WC1") or {}).get("winner") or "Ganador WC1"
    seed8_final = (wc_index.get("WC3") or {}).get("winner") or "Ganador WC3"

    def _series_card(id_, a, b, best_of):
        # Si alguno es placeholder, no podemos computar serie
        placeholder = ("Ganador" in a) or ("Ganador" in b)
        m = {"id": id_, "home": a, "away": b, "best_of": best_of}
        if placeholder:
            m.update({"status": "PENDIENTE", "series_score": "0-0", "winner": None})
            return m
        s = _series_summary(a, b, postseason_games, best_of=best_of)
        m.update({"status": s["status"], "series_score": s["series_score"], "winner": s["winner"]})
        return m

    # Cuartos (Bo5)
    qf1 = _series_card("QF1", seed1, seed8_final, 5)
    qf2 = _series_card("QF2", seed2, seed7_final, 5)
    qf3 = _series_card("QF3", seed3, seed6,       5)
    qf4 = _series_card("QF4", seed4, seed5,       5)

    # Semis (Bo5) — solo si hay ganadores de QFs
    semi1_a = qf1["winner"] or ("Ganador " + qf1["id"])
    semi1_b = qf2["winner"] or ("Ganador " + qf2["id"])
    semi2_a = qf3["winner"] or ("Ganador " + qf3["id"])
    semi2_b = qf4["winner"] or ("Ganador " + qf4["id"])

    sf1 = _series_card("SF1", semi1_a, semi1_b, 5)
    sf2 = _series_card("SF2", semi2_a, semi2_b, 5)

    # Final (Bo7) — solo si hay ganadores de SFs
    final_a = sf1["winner"] or ("Ganador " + sf1["id"])
    final_b = sf2["winner"] or ("Ganador " + sf2["id"])
    f1 = _series_card("F1", final_a, final_b, 7)

    bracket8 = {
        "quarters": [qf1, qf2, qf3, qf4],
        "semis":    [sf1, sf2],
        "final":     f1
    }
    # Campeón opcional
    bracket8["champion"] = f1["winner"] if f1.get("winner") else None
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

        # Wild Card (Bo1)
        wildcard_bracket = _build_wildcard_bracket(rows, postseason_games)

        # Bracket 8 (QF/SF Bo5, Final Bo7)
        bracket8 = _build_bracket8(rows, wildcard_bracket, postseason_games)

        payload = {
            "standings": rows,
            "games_today": games_today,
            "postseason_games": postseason_games,   # lista de dicts
            "wildcard_bracket": wildcard_bracket,   # lista [WC1, WC2, WC3]
            "bracket8": bracket8,                   # dict con quarters/semis/final (+ champion)
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
