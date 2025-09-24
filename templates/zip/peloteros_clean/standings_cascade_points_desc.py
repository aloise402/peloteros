from datetime import datetime
from zoneinfo import ZoneInfo

# NOTA: Este archivo incluye solo las funciones claves que update_cache.py necesita.

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
        # ✅ devolvemos todos los juegos acumulados (no filtramos solo por hoy)
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
