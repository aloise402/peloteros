# update_cache.py
# Genera el cache usando compute_rows() y games_played_today_scl() del módulo standings_*
import json, os, sys, time
from datetime import datetime
from zoneinfo import ZoneInfo

# --- Import robusto del módulo principal ---
try:
    import standings_cascade_points_desc as standings
except Exception:
    import standings_cascade_points as standings  # fallback si el nombre no tiene _desc

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "standings_cache.json")
SCL = ZoneInfo("America/Santiago")

# --- Lista de exclusiones manuales ---
# Caso 1: excluir por string exacto (cuando games_today es lista de strings)
EXCLUDE_STRINGS = {
    "Yankees 0 - 0 Mets - 08-09-2025 - 9:40 pm (hora Chile)",
}

# Caso 2: excluir por reglas (cuando games_today es lista de objetos)
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
    # Si es string: comparación exacta contra EXCLUDE_STRINGS
    if isinstance(g, str):
        return g.strip() in EXCLUDE_STRINGS

    # Si es objeto: coteja campos si existen
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
        # Validaciones mínimas para que el error sea claro si faltara algo
        if not hasattr(standings, "compute_rows"):
            raise AttributeError("El módulo no define compute_rows()")
        if not hasattr(standings, "games_played_today_scl"):
            raise AttributeError("El módulo no define games_played_today_scl()")

        # 1) Tabla
        rows = standings.compute_rows()

        # 2) Juegos de HOY (hora Chile)
        games_today = standings.games_played_today_scl()

        # 3) Aplicar exclusiones manuales
        games_today = [g for g in games_today if not _should_exclude_game(g)]

        # 4) Escribir cache (sólo lo que necesita la web)
        payload = {
            "standings": rows,
            "games_today": games_today,
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
    # Modo 1: una sola pasada (útil en Render antes de levantar la web)
    if "--once" in sys.argv or os.getenv("RUN_ONCE") == "1":
        _run_once_then_exit()

    # Modo 2: bucle (local/worker)
    UPDATE_INTERVAL_SECONDS = int(os.getenv("UPDATE_INTERVAL_SECONDS", "300"))  # 5 min
    while True:
        update_data_cache()
        print(f"Esperando {UPDATE_INTERVAL_SECONDS} segundos para la próxima actualización...")
        try:
            time.sleep(UPDATE_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("Detenido por el usuario.")
            break

