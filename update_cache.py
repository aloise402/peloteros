# update_cache.py
# Genera el cache usando compute_rows() y games_played_today_scl() del módulo standings_*

import json, os, sys, time
from datetime import datetime
from zoneinfo import ZoneInfo

# --- Import robusto del módulo principal ---
try:
    import standings_cascade_points_desc as standings
except Exception:
    import standings_cascade_points as standings  # fallback si no existe _desc

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "standings_cache.json")

# 👉 Ahora usamos la hora del Este (Miami)
ET = ZoneInfo("America/New_York")

# --- Exclusiones/Ediciones manuales para 'games_today' (lista de strings) ---
EXCLUDE_STRINGS = set()  # ejemplo: {"Yankees 0 - 0 Mets - 08-09-2025 - 9:40 pm (hora ET)"}

# Reglas de reemplazo: si 'match_contains' está en el string, se reemplaza por 'replace_with';
# usa replace_with=None si quieres borrar el registro.
EDIT_RULES_STR = [
    # ejemplo:
    # {"match_contains": "Dodgers 3 - 4 Brewers", "replace_with": "***"},
]

def _should_exclude_string(g_str: str) -> bool:
    return g_str.strip() in EXCLUDE_STRINGS

def _apply_edit_rules_string(g_str: str):
    g_norm = " ".join((g_str or "").split()).lower()
    for rule in EDIT_RULES_STR:
        if " ".join(rule["match_contains"].split()).lower() in g_norm:
            return rule.get("replace_with")
    return g_str

def update_data_cache():
    ts = datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{ts}] Iniciando actualización del cache...")

    try:
        if not hasattr(standings, "compute_rows"):
            raise AttributeError("El módulo no define compute_rows()")
        if not hasattr(standings, "games_played_today_scl"):
            raise AttributeError("El módulo no define games_played_today_scl()")

        # 1) Tabla
        rows = standings.compute_rows()

        # 2) Juegos de HOY
        games_today = standings.games_played_today_scl()

        # 3) Aplicar exclusiones y ediciones manuales
        new_games = []
        for g in games_today:
            if isinstance(g, str):
                if _should_exclude_string(g):
                    continue
                edited = _apply_edit_rules_string(g)
                if edited is not None:
                    new_games.append(edited)
            else:
                new_games.append(g)
        games_today = new_games

        # 4) Escribir cache
        payload = {
            "standings": rows,
            "games_today": games_today,
            "last_updated": ts + " (hora ET)"  # 👈 marcamos explícitamente
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
    # Modo 1: una sola pasada
    if "--once" in sys.argv or os.getenv("RUN_ONCE") == "1":
        _run_once_then_exit()

    # Modo 2: bucle
    UPDATE_INTERVAL_SECONDS = int(os.getenv("UPDATE_INTERVAL_SECONDS", "300"))  # 5 min
    while True:
        update_data_cache()
        print(f"Esperando {UPDATE_INTERVAL_SECONDS} segundos para la próxima actualización...")
        try:
            time.sleep(UPDATE_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("Detenido por el usuario.")
            break

