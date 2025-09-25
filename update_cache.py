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
def update_data_cache():
    ts = datetime.now(SCL).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{ts}] Iniciando actualización del cache...")
    try:
        if not hasattr(standings, "compute_rows"):
            raise AttributeError("El módulo no define compute_rows()")
        if not hasattr(standings, "games_played_today_scl"):
            raise AttributeError("El módulo no define games_played_today_scl()")
        rows = standings.compute_rows()
        games_today = standings.games_played_today_scl()
        games_today = [g for g in games_today if not _should_exclude_game(g)]
        # NUEVO: tomar postemporada y wildcard si existen
        get_ps = getattr(standings, "get_postseason_games", None)
        get_wc = getattr(standings, "get_wildcard_games", None)
        postseason_games = get_ps() if callable(get_ps) else []
        wildcard_games = get_wc() if callable(get_wc) else []
        payload = {
            "standings": rows,
            "games_today": games_today,
            "postseason_games": postseason_games,  # ← NUEVO
            "wildcard_games": wildcard_games,      # ← NUEVO
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
