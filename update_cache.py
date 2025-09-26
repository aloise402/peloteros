# update_cache.py
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

# ========================= EXCLUSIONES (se mantienen) =========================
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

# ========================= CAPTURA POSTEMPORADA =========================
def _collect_postseason_games():
    """
    Devuelve TODOS los juegos desde standings.SINCE (postemporada),
    filtrando por equipos válidos de la liga y por duelo (miembro vs miembro,
    o CPU vs miembro) de acuerdo a la misma lógica de tu módulo standings.
    Salida: lista de dicts (no necesariamente ordenada cronológicamente):
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

            # Miembros vs miembros (o CPU + miembro)
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

# ========================= UTILIDADES SERIES =========================
def _pair_key(a, b):
    return tuple(sorted([a, b]))

def _series_summary(a, b, games, best_of):
    """
    Cuenta victorias en la pareja (a vs b).
    best_of = 1/5/7 => wins_needed = 1/3/4
    Retorna: dict(status, series_score 'x-y', wins_a, wins_b, total, winner, wins_needed)
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
        status = "PENDIENTE"; winner = None
    elif wins_a >= wins_needed:
        status = "JUGADO"; winner = a
    elif wins_b >= wins_needed:
        status = "JUGADO"; winner = b
    else:
        status = "EN CURSO"; winner = None
    return {
        "status": status,
        "series_score": f"{wins_a}-{wins_b}",
        "wins_a": wins_a,
        "wins_b": wins_b,
        "total": total,
        "winner": winner,
        "wins_needed": wins_needed
    }

# ========================= WILD CARD (detección flexible) =========================
def _build_wildcard_bracket(standings_rows, postseason_games):
    """
    Detección flexible:
      - Tomamos equipos 7..10 de standings.
      - Primer cruce único observado entre esos 4 => WC1 (Bo1)
      - Segundo cruce único observado => WC2 (Bo1)
      - WC3 = perdedor(WC1) vs ganador(WC2) (Bo1)
    Si no hay cruces aún, mostramos placeholders con seeds (7vs8) y (9vs10).
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

    s7, s8, s9, s10 = rows[6]["team"], rows[7]["team"], rows[8]["team"], rows[9]["team"]
    four = {s7, s8, s9, s10}

    # Placeholders "clásicos"
    wc1 = {"id": "WC1", "home": s7, "away": s8,  "status": "PENDIENTE", "score": "", "winner": None, "loser": None, "best_of": 1}
    wc2 = {"id": "WC2", "home": s9, "away": s10, "status": "PENDIENTE", "score": "", "winner": None, "loser": None, "best_of": 1}
    wc3 = {"id": "WC3", "home": "Perdedor WC1", "away": "Ganador WC2", "status": "PENDIENTE", "score": "", "winner": None, "loser": None, "best_of": 1}

    def _pair(g): return tuple(sorted([g["home_team"], g["away_team"]]))
    # pares únicos entre 7..10 en el ORDEN de aparición; además guardamos el ÚLTIMO resultado de cada par
    pairs, last_by_pair = [], {}
    for g in postseason_games:
        if g["home_team"] in four and g["away_team"] in four:
            pk = _pair(g)
            last_by_pair[pk] = g
            if pk not in pairs:
                pairs.append(pk)

    def _fill_wc_slot(slot, last):
        slot["home"], slot["away"] = last["home_team"], last["away_team"]
        slot["score"] = f'{last["home_score"]}-{last["away_score"]}'
        slot["status"] = "JUGADO"
        if last["home_score"] > last["away_score"]:
            slot["winner"], slot["loser"] = last["home_team"], last["away_team"]
        else:
            slot["winner"], slot["loser"] = last["away_team"], last["home_team"]

    if len(pairs) >= 1:
        _fill_wc_slot(wc1, last_by_pair[pairs[0]])
    if len(pairs) >= 2:
        _fill_wc_slot(wc2, last_by_pair[pairs[1]])

    # WC3 = perdedor(WC1) vs ganador(WC2)
    if wc1["loser"] and wc2["winner"]:
        a, b = wc1["loser"], wc2["winner"]
        last = None
        for g in postseason_games:
            if {g["home_team"], g["away_team"]} == {a, b}:
                last = g
        if last:
            _fill_wc_slot(wc3, last)
        else:
            wc3["home"], wc3["away"] = a, b

    return [wc1, wc2, wc3]

# ========================= BRACKET 8 (Bo5 / Bo5 / Bo7) =========================
def _build_bracket8(standings_rows, wildcard_bracket, postseason_games):
    """
    Bracket 8 siguiendo MLB:
      - Seed 7 = ganador real del cruce (7 vs 8) [Bo1]
      - Seed 8 = ganador real de (perdedor 7–8 vs ganador 9–10) [Bo1]
      - Cuartos y Semis: Bo5 (gana 3)
      - Final: Bo7 (gana 4)
    No depende del orden en que se hayan jugado los WC.
    """
    def _row_key(r):
        return (-r.get("points", 0), -r.get("wins", 0), r.get("losses", 0))
    rows = sorted(standings_rows, key=_row_key)
    if len(rows) < 6:
        return None

    s1, s2, s3, s4, s5, s6 = [rows[i]["team"] for i in range(6)]
    s7, s8, s9, s10 = rows[6]["team"], rows[7]["team"], rows[8]["team"], rows[9]["team"]

    def _series_card(id_, a, b, best_of):
        placeholder = ("Ganador" in a) or ("Ganador" in b)
        m = {"id": id_, "home": a, "away": b, "best_of": best_of}
        if placeholder:
            m.update({"status": "PENDIENTE", "series_score": "0-0", "winner": None})
            return m
        s = _series_summary(a, b, postseason_games, best_of=best_of)
        m.update({"status": s["status"], "series_score": s["series_score"], "winner": s["winner"]})
        return m

    # Resolver Bo1 estrictos que definen 7 y 8
    s78 = _series_summary(s7, s8, postseason_games, best_of=1)
    winner_78 = s78["winner"]
    loser_78  = s8 if winner_78 == s7 else (s7 if winner_78 == s8 else None)

    s910 = _series_summary(s9, s10, postseason_games, best_of=1)
    winner_910 = s910["winner"]

    seed7_final = winner_78 or "Ganador 7–8"
    seed8_final = "Ganador WC3"
    if loser_78 and winner_910:
        s_wc3 = _series_summary(loser_78, winner_910, postseason_games, best_of=1)
        if s_wc3["winner"]:
            seed8_final = s_wc3["winner"]

    # Cuartos (Bo5)
    qf1 = _series_card("QF1", s1, seed8_final, 5)
    qf2 = _series_card("QF2", s2, seed7_final, 5)
    qf3 = _series_card("QF3", s3, s6,          5)
    qf4 = _series_card("QF4", s4, s5,          5)

    # Semis (Bo5)
    semi1_a = qf1["winner"] or ("Ganador " + qf1["id"])
    semi1_b = qf2["winner"] or ("Ganador " + qf2["id"])
    semi2_a = qf3["winner"] or ("Ganador " + qf3["id"])
    semi2_b = qf4["winner"] or ("Ganador " + qf4["id"])

    sf1 = _series_card("SF1", semi1_a, semi1_b, 5)
    sf2 = _series_card("SF2", semi2_a, semi2_b, 5)

    # Final (Bo7)
    final_a = sf1["winner"] or ("Ganador " + sf1["id"])
    final_b = sf2["winner"] or ("Ganador " + sf2["id"])
    f1 = _series_card("F1", final_a, final_b, 7)

    bracket8 = {
        "quarters": [qf1, qf2, qf3, qf4],
        "semis":    [sf1, sf2],
        "final":     f1,
        "champion": f1["winner"] if f1.get("winner") else None
    }
    return bracket8

# ========================= LOOP DE ACTUALIZACIÓN =========================
def update_data_cache():
    ts = datetime.now(SCL).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{ts}] Iniciando actualización del cache...")
    try:
        if not hasattr(standings, "compute_rows"):
            raise AttributeError("El módulo no define compute_rows()")
        if not hasattr(standings, "games_played_today_scl"):
            raise AttributeError("El módulo no define games_played_today_scl()")

        # Standings actuales
        rows = standings.compute_rows()

        # Juegos de HOY (SCL) con exclusiones
        games_today = standings.games_played_today_scl()
        games_today = [g for g in games_today if not _should_exclude_game(g)]

        # Postemporada completa desde SINCE
        postseason_games = _collect_postseason_games()

        # Wild Card (Bo1) — detección flexible
        wildcard_bracket = _build_wildcard_bracket(rows, postseason_games)

        # Bracket 8: QF/SF (Bo5) y Final (Bo7)
        bracket8 = _build_bracket8(rows, wildcard_bracket, postseason_games)

        payload = {
            "standings": rows,
            "games_today": games_today,
            "postseason_games": postseason_games,   # lista de dicts
            "wildcard_bracket": wildcard_bracket,   # [WC1, WC2, WC3]
            "bracket8": bracket8,                   # quarters/semis/final (+ champion)
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
