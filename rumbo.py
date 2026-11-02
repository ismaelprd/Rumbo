"""
Rumbo - tu racha, tu control.   (v3: retos con Gemini + cofres épicos)

App discreta para dejar un hábito: contador de racha, registro de recaídas,
botón «Tengo ganas» (reto anti-ganas generado con Gemini), radar de riesgo y plan personal.

Flet 0.28.3  ·  SQLite local o Turso
Variable de entorno para los retos: GEMINI_API_KEY (sin ella se usan retos de reserva)
    pip install flet==0.28.3 flet-desktop==0.28.3
    python main.py            (probar en PC)
    flet build apk            (generar APK)
"""
import asyncio
import hashlib
import json
import os
import random
import sqlite3
import re
import threading
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import flet as ft

try:  # solo hace falta en Render (Turso); en el APK / PC se usa SQLite local
    import libsql
except ImportError:
    libsql = None

APP_NAME = "Rumbo"

# ----------------------------------------------------------------------------
# Paleta (azul marino + degradados azules, tarjetas con relieve suave)
# ----------------------------------------------------------------------------
BG = "#1B2230"
CARD = "#232C3E"
CARD_IN = "#171E2B"
TXT = "#E9EEF9"
MUT = "#8F9BB3"
B1 = "#58A6FF"
B2 = "#2F6BFF"
OK = "#4ADE9A"
WARN = "#FBBF24"
DANGER = "#FF6B81"
SH_DARK = "#10151F"
SH_LIGHT = "#2D384D"
GLOW = "#552F6BFF"
CORAL = "#FF6B81"

GRAD = ft.LinearGradient(begin=ft.alignment.top_left, end=ft.alignment.bottom_right, colors=[B1, B2])
GRAD_DANGER = ft.LinearGradient(begin=ft.alignment.top_left, end=ft.alignment.bottom_right,
                                colors=["#FF8FA3", "#E5484D"])

DATA_DIR = os.getenv("FLET_APP_STORAGE_DATA") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data"
)
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "rumbo.db")

# Si defines estas dos variables de entorno (Render), los datos viven en Turso.
# Si no, se usa un archivo SQLite local (APK o PC), como antes.
TURSO_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

MILESTONES = [
    (1, "Primer día"), (3, "Tres días"), (7, "Una semana"), (14, "Dos semanas"),
    (30, "Un mes"), (60, "Dos meses"), (90, "Tres meses"),
    (180, "Medio año"), (365, "Un año"),
]
TRIGGERS = [
    "Aburrimiento", "Estrés", "Soledad", "Cansancio", "Estar en la cama",
    "Redes sociales", "Ansiedad", "Estar solo en casa", "Otro",
]
MESSAGES = [
    "Cada hora cuenta. Estás construyendo algo.",
    "Las ganas suben, llegan a un pico y bajan. Tú no tienes que hacer nada.",
    "Hoy decides quién quieres ser mañana.",
    "No tiene que ser fácil, solo tiene que seguir contando.",
    "Un impulso dura minutos; tu racha son días.",
    "Si hoy es difícil, es porque estás cambiando algo importante.",
]
CHEST_EVERY = 10  # un cofre cada 10 días de la RACHA ACTUAL

# Rarezas de los cofres: cuanto más lejos llegas en una racha, mejores son.
RARITIES = ["Común", "Rara", "Épica", "Legendaria"]
RARITY_COLOR = {"Común": "#A9B4CC", "Rara": B1, "Épica": "#C084FC", "Legendaria": "#FFC53D"}
RARITY_GRAD = {"Común": ("#9AA7C2", "#5B6780"), "Rara": ("#58A6FF", "#2F6BFF"),
               "Épica": ("#D8A6FF", "#7C3AED"), "Legendaria": ("#FFE08A", "#F59E0B")}

MISSIONS = {
    "Común": [
        "Sal a caminar 30 minutos sin el móvil",
        "Escribe 3 cosas que han mejorado desde que empezaste",
        "Haz 20 minutos de ejercicio",
        "Ordena un rincón de tu casa o de tu habitación",
        "Escribe a alguien que aprecias y propón un plan",
        "Dedica 30 minutos a aprender algo que te interese",
    ],
    "Rara": [
        "Cocina algo que te guste de verdad, desde cero",
        "Haz 40 minutos de ejercicio y estira 10 minutos después",
        "Pasa una tarde fuera de casa haciendo un plan distinto",
        "Llama de voz a alguien con quien llevas tiempo sin hablar",
        "Ordena a fondo una habitación entera",
        "Aprende algo nuevo durante 1 hora y explícaselo a alguien",
    ],
    "Épica": [
        "Haz una ruta a pie o en bici de más de una hora, sin auriculares",
        "Pasa 2 horas sin móvil haciendo algo creativo o manual",
        "Escribe una carta a tu yo de dentro de un año: cómo estás y qué quieres",
        "Haz algo que te dé un poco de miedo o vergüenza (clase de prueba, hablar con alguien nuevo...)",
        "Prepara una comida y compártela con alguien",
    ],
    "Legendaria": [
        "Planifica y haz una salida de medio día a un sitio en el que nunca hayas estado",
        "Dedica una mañana entera a un proyecto personal que llevas tiempo aplazando",
        "Haz un reto físico personal: tu mejor marca en algo (km, flexiones, plancha...)",
        "Escribe una página entera: qué ha cambiado en ti y qué vas a hacer con ello",
    ],
}
REWARDS = {
    "Común": [
        "Date un capricho: tu comida favorita",
        "Un café o un postre en tu sitio favorito",
        "Una hora de serie o juego sin culpa",
        "Una ducha larga con tu música a todo volumen",
        "Compra algo pequeño que llevas tiempo queriendo (hasta 10 €)",
        "Un helado enorme, sin medir",
    ],
    "Rara": [
        "Una tarde libre para ti: peli, serie o juego sin culpa",
        "Pide la cena de tu sitio favorito, y la eliges tú",
        "Una noche larga de sueño, sin alarma",
        "Un plan con amigos, y lo eliges tú",
        "Compra algo que llevas tiempo queriendo (hasta 25 €)",
        "Un masaje o una sesión de relax, en casa o en un centro",
    ],
    "Épica": [
        "Cena en el restaurante que más ganas tengas",
        "Un día entero sin obligaciones evitables: solo lo que te apetezca",
        "Cómprate ese juego, ropa o gadget que tanto miras (hasta 50 €)",
        "Entradas para un concierto, cine, evento o partido que te guste",
        "Una escapada de un día a un sitio nuevo",
    ],
    "Legendaria": [
        "Un finde de escapada: tú eliges destino",
        "Ese capricho grande que llevas meses mirando (hasta 100 €)",
        "Una experiencia para recordar: karts, escape room, parapente, spa...",
        "Un día entero en el que decides TODO tú, de la mañana a la noche",
        "Un viaje o plan soñado: ponle fecha hoy mismo",
    ],
}
BONUS = {
    "Épica": ["Bonus épico: elige también el plan del domingo",
              "Bonus épico: hoy no friegas ni cocinas",
              "Bonus épico: una hora extra de lo que más te guste"],
    "Legendaria": ["Bonus legendario: un capricho extra que puedes canjear cuando quieras",
                   "Bonus legendario: pídele a alguien que te prepare una comida",
                   "Bonus legendario: un día entero de «hoy mando yo»"],
}
BADGES = {
    "Común": ["Chispa", "Brújula", "Ancla", "Semilla", "Primer paso"],
    "Rara": ["Faro", "Halcón", "Lobo solitario", "Roble", "Centinela"],
    "Épica": ["Titán", "Fénix", "Dragón de escarcha", "Coloso", "Tormenta"],
    "Legendaria": ["Leyenda viva", "Amo del Rumbo", "Inquebrantable", "Sol naciente", "Rey de la montaña"],
}


def roll_rarity(n):
    """n = número de cofre dentro de la racha. Cada cofre seguido mejora las probabilidades;
    el 5.º, 15.º... es como mínimo Épico y el 10.º, 20.º... es siempre Legendario."""
    if n % 10 == 0:
        return "Legendaria"
    if n % 5 == 0:
        return random.choices(["Épica", "Legendaria"], [75, 25])[0]
    k = min(n - 1, 8)
    return random.choices(RARITIES, [max(10, 50 - 5 * k), 30, 15 + 2 * k, 5 + 2 * k])[0]


URGE_PLAN = [
    "Levántate y cambia de habitación ahora mismo",
    "Deja el móvil fuera de la cama / del baño",
    "Bebe un vaso de agua y lávate la cara",
    "Haz 20 sentadillas o 15 flexiones",
    "Sal a la calle 10 minutos o escribe a un amigo",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS streaks (id INTEGER PRIMARY KEY AUTOINCREMENT, start_ts TEXT NOT NULL, end_ts TEXT);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kind TEXT NOT NULL, trigger_name TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS checkins (day TEXT PRIMARY KEY, mood INTEGER, stress INTEGER, sleep REAL);
CREATE TABLE IF NOT EXISTS scores (id INTEGER PRIMARY KEY AUTOINCREMENT, game TEXT, score INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS rewards (n INTEGER PRIMARY KEY, mission TEXT, reward TEXT, opened_ts TEXT, done_ts TEXT);
CREATE TABLE IF NOT EXISTS chests (id INTEGER PRIMARY KEY AUTOINCREMENT, streak_id INTEGER NOT NULL, n INTEGER NOT NULL, mission TEXT, reward TEXT, rarity TEXT, badge TEXT, opened_ts TEXT, done_ts TEXT, UNIQUE(streak_id, n));
CREATE TABLE IF NOT EXISTS retos (id INTEGER PRIMARY KEY AUTOINCREMENT, texto TEXT NOT NULL, tipo TEXT, ts TEXT, done_ts TEXT);
"""

FMT = "%Y-%m-%d %H:%M"

# Hora local: en Render el servidor va en UTC, así que se usa la zona de aquí.
# En el móvil / PC se usa la hora del propio dispositivo.
try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo(os.getenv("APP_TZ", "Europe/Madrid")) if (os.getenv("PORT") or os.getenv("APP_TZ")) else None
except Exception:
    _TZ = None


def local_now():
    return datetime.now(_TZ).replace(tzinfo=None) if _TZ else datetime.now()


# ----------------------------------------------------------------------------
# Base de datos
# ----------------------------------------------------------------------------
class DB:
    def __init__(self, path):
        self.lock = threading.RLock()
        if TURSO_URL and TURSO_TOKEN:
            if libsql is None:
                raise RuntimeError("Falta el paquete 'libsql' (añádelo a requirements.txt)")
            self.c = libsql.connect(path, sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
            self.c.sync()
        else:
            self.c = sqlite3.connect(path, check_same_thread=False)
        for stmt in SCHEMA.split(";"):
            if stmt.strip():
                self.c.execute(stmt)
        self.c.commit()
        self._migrate()

    def q(self, sql, args=()):
        with self.lock:
            cur = self.c.execute(sql, args)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def x(self, sql, args=()):
        with self.lock:
            cur = self.c.execute(sql, args)
            self.c.commit()
            return cur

    def get(self, k, default=None):
        r = self.q("SELECT v FROM settings WHERE k=?", (k,))
        return r[0]["v"] if r else default

    def set(self, k, v):
        self.x("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))

    def delete_setting(self, k):
        self.x("DELETE FROM settings WHERE k=?", (k,))

    def current_streak(self):
        r = self.q("SELECT * FROM streaks WHERE end_ts IS NULL ORDER BY id DESC LIMIT 1")
        return r[0] if r else None

    def start_streak(self, dt):
        self.x("INSERT INTO streaks(start_ts) VALUES(?)", (dt.isoformat(),))

    def end_streak(self, dt):
        cur = self.current_streak()
        if cur:
            start = datetime.fromisoformat(cur["start_ts"])
            self.x("UPDATE streaks SET end_ts=? WHERE id=?", (max(dt, start).isoformat(), cur["id"]))

    def set_current_start(self, dt):
        cur = self.current_streak()
        if cur:
            self.x("UPDATE streaks SET start_ts=? WHERE id=?", (dt.isoformat(), cur["id"]))
        else:
            self.start_streak(dt)

    def all_streaks(self):
        return self.q("SELECT * FROM streaks ORDER BY id DESC")

    def record_seconds(self):
        best = 0.0
        now = local_now()
        for r in self.all_streaks():
            s = datetime.fromisoformat(r["start_ts"])
            e = datetime.fromisoformat(r["end_ts"]) if r["end_ts"] else now
            best = max(best, (e - s).total_seconds())
        return best

    def total_clean_days(self):
        now = local_now()
        tot = 0.0
        for r in self.all_streaks():
            s = datetime.fromisoformat(r["start_ts"])
            e = datetime.fromisoformat(r["end_ts"]) if r["end_ts"] else now
            tot += max(0, (e - s).total_seconds())
        return int(tot // 86400)

    def add_event(self, ts, kind, trigger=None, note=None):
        self.x("INSERT INTO events(ts,kind,trigger_name,note) VALUES(?,?,?,?)", (ts.isoformat(), kind, trigger, note))

    def count_events(self, kind):
        return self.q("SELECT COUNT(*) n FROM events WHERE kind=?", (kind,))[0]["n"]

    # --- retos anti-ganas ---
    def add_reto(self, texto, tipo):
        self.x("INSERT INTO retos(texto,tipo,ts) VALUES(?,?,?)", (texto, tipo, local_now().isoformat()))
        return self.q("SELECT id FROM retos ORDER BY id DESC LIMIT 1")[0]["id"]

    def finish_reto(self, rid):
        self.x("UPDATE retos SET done_ts=? WHERE id=?", (local_now().isoformat(), rid))

    def recent_retos(self, n=300):
        return [r["texto"] for r in self.q("SELECT texto FROM retos ORDER BY id DESC LIMIT ?", (n,))]

    def count_retos_done(self):
        return self.q("SELECT COUNT(*) n FROM retos WHERE done_ts IS NOT NULL")[0]["n"]

    # --- cofres: cuelgan de la racha en la que se ganan ---
    def chest_rows(self):
        return self.q("SELECT * FROM chests ORDER BY streak_id, n")

    def open_chest(self, sid, n, mission, reward, rarity, badge):
        ts = local_now().isoformat()
        if self.q("SELECT 1 x FROM chests WHERE streak_id=? AND n=?", (sid, n)):
            self.x("UPDATE chests SET mission=?, reward=?, rarity=?, badge=?, opened_ts=? "
                   "WHERE streak_id=? AND n=? AND opened_ts IS NULL", (mission, reward, rarity, badge, ts, sid, n))
        else:
            self.x("INSERT INTO chests(streak_id,n,mission,reward,rarity,badge,opened_ts) VALUES(?,?,?,?,?,?,?)",
                   (sid, n, mission, reward, rarity, badge, ts))

    def finish_chest(self, sid, n):
        self.x("UPDATE chests SET done_ts=? WHERE streak_id=? AND n=?", (local_now().isoformat(), sid, n))

    def bank_chests(self, sid, start, end):
        """Al recaer, los cofres ya ganados en esa racha se guardan para que no se pierdan."""
        earned = int((end - start).total_seconds() // 86400) // CHEST_EVERY
        for n in range(1, earned + 1):
            self.x("INSERT OR IGNORE INTO chests(streak_id,n) VALUES(?,?)", (sid, n))

    def _migrate(self):
        """Los cofres antiguos (contaban días acumulados) pasan a la tabla nueva como 'racha 0'."""
        if self.get("chests_v2"):
            return
        for r in self.q("SELECT * FROM rewards ORDER BY n"):
            self.x("INSERT OR IGNORE INTO chests(streak_id,n,mission,reward,rarity,badge,opened_ts,done_ts) "
                   "VALUES(0,?,?,?,?,?,?,?)",
                   (r["n"], r["mission"], r["reward"], "Común", "Cofre clásico", r["opened_ts"], r["done_ts"]))
        self.set("chests_v2", "1")

    def notes(self, kind):
        return self.q("SELECT * FROM notes WHERE kind=? ORDER BY id DESC", (kind,))

    def wipe(self):
        for t in ("settings", "streaks", "events", "checkins", "scores", "notes", "rewards", "chests", "retos"):
            self.x(f"DELETE FROM {t}")


_DB = None
_DB_LOCK = threading.Lock()


def get_db():
    """Una sola conexión compartida (antes se abría y sincronizaba con Turso en cada visita)."""
    global _DB
    with _DB_LOCK:
        if _DB is None:
            _DB = DB(DB_PATH)
        return _DB


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def parse_dt(text):
    dt = datetime.strptime(text.strip(), FMT)
    if dt > local_now() + timedelta(minutes=1):
        raise ValueError("future")
    return dt


def split_duration(seconds):
    seconds = int(max(0, seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return d, h, m, s


def human(seconds):
    d, h, m, _ = split_duration(seconds)
    return f"{d}d {h}h {m}m" if d else f"{h}h {m}m"


def hash_pin(pin):
    return hashlib.sha256(("rumbo-" + pin).encode()).hexdigest()


def risk_info(db):
    """Radar de riesgo: horas en que antes hubo ganas/recaídas + estado de hoy + franja nocturna."""
    hist = [0] * 24
    for r in db.q("SELECT ts FROM events"):
        hist[datetime.fromisoformat(r["ts"]).hour] += 1
    total = sum(hist)
    now = local_now()
    score, why = 0, []
    if total >= 3:
        window = sum(hist[(now.hour + i) % 24] for i in range(3))
        pts = min(50, int(window / total * 120))
        score += pts
        if pts >= 20:
            why.append("Ahora entras en una franja donde te han venido ganas otras veces")
    ci = db.q("SELECT * FROM checkins WHERE day=?", (now.strftime("%Y-%m-%d"),))
    if ci:
        c = ci[0]
        pts = (c["stress"] - 1) * 8 + (5 - c["mood"]) * 5
        score += pts
        if pts >= 20:
            why.append("Hoy marcaste estrés alto o ánimo bajo")
    if now.hour >= 22 or now.hour < 5:
        score += 12
        why.append("La noche es la franja más delicada para casi todo el mundo")
    score = min(100, score)
    level = "Bajo" if score < 35 else ("Medio" if score < 65 else "Alto")
    color = OK if score < 35 else (WARN if score < 65 else DANGER)
    return score, level, color, hist, why


# ----------------------------------------------------------------------------
# Retos anti-ganas generados con Gemini (solo librería estándar: sin dependencias nuevas)
# La clave va en la variable de entorno GEMINI_API_KEY. NUNCA la escribas en el código.
# ----------------------------------------------------------------------------
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
_GEMINI_RUTA = 0  # recuerda qué endpoint funcionó la última vez

RETO_TIPOS = [
    ("Cuerpo", "algo físico y sencillo: moverse, beber agua, estirar, lavarse la cara, respirar..."),
    ("Mente", "un reto mental: listar cosas, memorizar, cálculo, adivinanzas, palabras (por ejemplo, citar 10 científicos)"),
    ("Social", "escribir o llamar a alguien con un propósito concreto (por ejemplo, preguntarle a un amigo cómo está)"),
    ("Opinión", "pensar y formarse una opinión argumentada sobre un tema controvertido (no político partidista) y defenderla en voz alta"),
    ("Creatividad", "inventar, dibujar, escribir o imaginar algo en pocos minutos"),
    ("Orden", "ordenar o limpiar algo concreto y pequeño"),
    ("Aprender", "aprender o recordar algo útil o curioso de ciencia, idiomas, historia, geografía..."),
]

RETOS_RESERVA = [
    "Ve a la cocina y bebe dos vasos de agua despacio, mirando por la ventana.",
    "Cita 10 científicos de memoria. Si te atascas, sigue con 10 escritores.",
    "Escríbele a un amigo y pregúntale cómo está. Cuéntale algo bueno de tu día.",
    "Elige un tema polémico y defiende en voz alta, durante 2 minutos, la postura contraria a la tuya.",
    "Nombra 15 países y sus capitales sin mirar nada.",
    "Haz 3 series de 15 sentadillas con 30 segundos de descanso.",
    "Ordena durante 10 minutos el cajón o el estante más desastroso que tengas.",
    "Dibuja con lápiz y papel tu habitación ideal. Tienes 5 minutos.",
    "Escribe 10 cosas por las que estás agradecido hoy.",
    "Lávate la cara con agua fría y haz 2 minutos de estiramientos de cuello y hombros.",
    "Cuenta hacia atrás de 7 en 7 desde 200 sin equivocarte.",
    "Prepárate un té o una infusión y tómatela sentado, sin pantallas.",
    "Piensa en una película que te encante y escribe en 5 líneas por qué recomendarla.",
    "Llama a alguien de tu familia y pregúntale qué tal está.",
    "Escribe el abecedario con un animal para cada letra.",
    "Sal al balcón o a la puerta de casa y cuenta 20 cosas de color verde.",
    "Aprende a decir 5 frases nuevas en un idioma que te guste y repítelas en voz alta.",
    "Haz 1 minuto de plancha, descansa y repite 3 veces.",
]


def _norm_txt(t):
    t = unicodedata.normalize("NFD", str(t).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def _clave(t):
    return {w for w in _norm_txt(t).split() if len(w) > 3}


def _repetido(texto, previos):
    """True si el reto es igual o casi igual (mismas palabras clave) a alguno ya usado."""
    a = _clave(texto)
    if not a:
        return False
    for p in previos:
        b = _clave(p)
        if not b:
            continue
        inter = len(a & b)
        if len(a | b) and (inter / len(a | b) >= 0.5 or (inter >= 3 and inter / min(len(a), len(b)) >= 0.6)):
            return True
    return False


def _gemini_json(prompt):
    global _GEMINI_RUTA
    if not GEMINI_KEY:
        raise RuntimeError("Falta la variable GEMINI_API_KEY")
    cuerpo = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 1.1},
    }).encode("utf-8")
    base = f"models/{GEMINI_MODEL}:generateContent"
    rutas = [
        (f"https://generativelanguage.googleapis.com/v1beta/{base}", {"x-goog-api-key": GEMINI_KEY}),
        (f"https://aiplatform.googleapis.com/v1/publishers/google/{base}?key={GEMINI_KEY}", {}),
    ]
    orden = list(range(len(rutas)))
    orden = orden[_GEMINI_RUTA:] + orden[:_GEMINI_RUTA]
    ultimo = None
    for i in orden:
        url, cab = rutas[i]
        req = urllib.request.Request(url, data=cuerpo, method="POST",
                                     headers={"Content-Type": "application/json", **cab})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                datos = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            ultimo = e
            if e.code in (400, 401, 403, 404):  # clave de otro tipo de endpoint: prueba el siguiente
                continue
            raise
        _GEMINI_RUTA = i
        partes = datos["candidates"][0]["content"]["parts"]
        texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
        m = re.search(r"\{.*\}", texto, re.S)
        return json.loads(m.group(0) if m else texto)
    raise ultimo or RuntimeError("Gemini no respondió")


def generar_reto(db):
    """Devuelve (texto, tipo, origen). Nunca lanza error; si falla la IA usa un reto de reserva.
    Los retos ya mostrados se guardan en la base de datos y no se vuelven a repetir."""
    previos = db.recent_retos(300)
    h = local_now().hour
    momento = ("madrugada" if h < 6 else "mañana" if h < 12 else "tarde" if h < 20
               else "noche" if h < 23 else "madrugada")
    ya = "\n".join("- " + p[:110] for p in previos[:40]) or "(ninguno todavía)"
    for _ in range(3):
        tipo, desc = random.choice(RETO_TIPOS)
        prompt = f"""Eres el asistente de una app de apoyo para dejar un hábito. La persona acaba de pulsar
«Tengo ganas» y necesita DISTRAERSE ahora mismo.
Dale UN reto breve que ocupe su mente o su cuerpo entre 2 y 15 minutos. Sin mencionar el hábito ni nada explícito.

Tipo de reto: {tipo} → {desc}
Ejemplos del estilo (NO los copies): «Ve a la cocina y bébete dos vasos de agua despacio»; «Cita 10 científicos»;
«Escríbele a un amigo y pregúntale cómo está»; «Piensa tu opinión sobre un tema controvertido y defiéndela en voz alta».

Reglas:
- Habla de tú, tono cercano, 1 o 2 frases como máximo. Instrucciones concretas y medibles (cantidad o tiempo).
- Es de {momento}: de noche o madrugada, nada de salir a la calle ni ejercicio intenso. Sin pantallas si es posible.
- Sé creativo y evita lo típico.
- PROHIBIDO repetir o parecerte a estos retos ya usados:
{ya}

Devuelve ÚNICAMENTE un JSON con la clave "reto"."""
        try:
            texto = str(_gemini_json(prompt).get("reto", "")).strip()
        except Exception as e:
            print(f"Gemini no disponible: {e}")
            break
        if 12 <= len(texto) <= 320 and not _repetido(texto, previos):
            return texto, tipo, "ia"
    libres = [r for r in RETOS_RESERVA if not _repetido(r, previos)]
    return random.choice(libres or RETOS_RESERVA), "Reserva", "reserva"


# ----------------------------------------------------------------------------
# Componentes visuales (estilo neumórfico)
# ----------------------------------------------------------------------------
def neu(blur=18, d=6):
    return [
        ft.BoxShadow(blur_radius=blur, color=SH_DARK, offset=ft.Offset(d, d)),
        ft.BoxShadow(blur_radius=blur, color=SH_LIGHT, offset=ft.Offset(-d, -d)),
    ]


def card(content, pad=16, **kw):
    return ft.Container(content=content, padding=pad, border_radius=22, bgcolor=CARD, shadow=neu(), **kw)


def inset(content, pad=12, **kw):
    return ft.Container(content=content, padding=pad, border_radius=16, bgcolor=CARD_IN, **kw)


def title(text, size=20, color=TXT):
    return ft.Text(text, size=size, weight=ft.FontWeight.BOLD, color=color)


def muted(text, size=13, color=MUT):
    return ft.Text(text, size=size, color=color)


def gbtn(text, icon=None, on_click=None, expand=False, height=52, danger=False):
    row = []
    if icon:
        row.append(ft.Icon(icon, color="white", size=20))
    row.append(ft.Text(text, color="white", weight=ft.FontWeight.W_600, size=15))
    return ft.Container(
        content=ft.Row(row, alignment=ft.MainAxisAlignment.CENTER, spacing=8, tight=not expand),
        gradient=GRAD_DANGER if danger else GRAD, border_radius=16, height=height,
        padding=ft.padding.symmetric(horizontal=22), on_click=on_click, ink=True, expand=expand,
        alignment=ft.alignment.center,
        shadow=[ft.BoxShadow(blur_radius=22, color=("#55E5484D" if danger else GLOW), offset=ft.Offset(0, 8))],
    )


def sbtn(text, icon=None, on_click=None, expand=False, color=TXT, height=50):
    row = []
    if icon:
        row.append(ft.Icon(icon, color=color, size=20))
    row.append(ft.Text(text, color=color, weight=ft.FontWeight.W_600, size=14))
    return ft.Container(
        content=ft.Row(row, alignment=ft.MainAxisAlignment.CENTER, spacing=8, tight=not expand),
        bgcolor=CARD, border_radius=16, height=height, padding=ft.padding.symmetric(horizontal=20),
        on_click=on_click, ink=True, expand=expand, alignment=ft.alignment.center, shadow=neu(12, 4),
    )


def tile(icon, on_click=None, selected=False, size=48):
    return ft.Container(
        content=ft.Icon(icon, color="white" if selected else MUT, size=24),
        width=size, height=size, border_radius=16, alignment=ft.alignment.center,
        gradient=GRAD if selected else None, bgcolor=None if selected else CARD,
        shadow=[ft.BoxShadow(blur_radius=18, color=GLOW, offset=ft.Offset(0, 6))] if selected else neu(10, 3),
        on_click=on_click, ink=True,
    )


def tf(label, **kw):
    return ft.TextField(label=label, bgcolor=CARD_IN, border_radius=14, border_color=ft.Colors.TRANSPARENT,
                        focused_border_color=B1, color=TXT, label_style=ft.TextStyle(color=MUT), **kw)


def dd(label, options):
    return ft.Dropdown(label=label, options=[ft.dropdown.Option(o) for o in options], bgcolor=CARD_IN,
                       border_radius=14, border_color=ft.Colors.TRANSPARENT, focused_border_color=B1, color=TXT,
                       label_style=ft.TextStyle(color=MUT))


def dialog(title_text, content, actions):
    return ft.AlertDialog(modal=True, bgcolor=CARD, shape=ft.RoundedRectangleBorder(radius=26),
                          title=ft.Text(title_text, weight=ft.FontWeight.BOLD, color=TXT),
                          content=content, actions=actions)


# ----------------------------------------------------------------------------
# App
# ----------------------------------------------------------------------------
def main(page: ft.Page):
    db = get_db()
    page.title = APP_NAME
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(color_scheme_seed=B2)
    page.bgcolor = BG
    page.padding = 0
    page.window.width = 390
    page.window.height = 800

    state = {"screen": "main", "tab": 0, "task": 0, "locked": bool(db.get("pin_hash"))}
    refs = {}

    def snack(msg):
        page.open(ft.SnackBar(ft.Text(msg, color=TXT), bgcolor=CARD))

    def open_dlg(d):
        page.open(d)

    def close_dlg(d):
        page.close(d)

    def go(screen, tab=None):
        state["screen"] = screen
        state["task"] += 1  # cancela bucles asíncronos de pantallas anteriores
        if tab is not None:
            state["tab"] = tab
        render()

    def padded(col):
        return ft.Container(content=col, padding=ft.padding.symmetric(horizontal=16), expand=True)

    # ---- diálogos ---------------------------------------------------------
    def relapse_dialog(e=None):
        when = tf("Cuándo (AAAA-MM-DD HH:MM)", value=local_now().strftime(FMT))
        trig = dd("¿Qué lo disparó?", TRIGGERS)
        note = tf("Nota (opcional)", multiline=True, min_lines=2, max_lines=4)
        err = ft.Text("", color=DANGER)

        def save(_):
            try:
                dt = parse_dt(when.value)
            except ValueError:
                err.value = "Fecha inválida. Formato: 2026-11-01 21:30 (no puede ser futura)."
                page.update()
                return
            cur = db.current_streak()
            if cur:
                db.bank_chests(cur["id"], datetime.fromisoformat(cur["start_ts"]), dt)
            db.end_streak(dt)
            db.add_event(dt, "relapse", trig.value, note.value)
            db.start_streak(dt)
            close_dlg(dlg)
            snack("Registrado. Una recaída no borra lo aprendido: empieza de nuevo.")
            render()

        dlg = dialog("Registrar recaída",
                     ft.Column([muted("Sin juicios: registrar es lo que te permite entender tus patrones."),
                                when, trig, note, err], tight=True, width=340, spacing=12),
                     [ft.TextButton("Cancelar", on_click=lambda _: close_dlg(dlg)),
                      gbtn("Guardar", on_click=save, height=42)])
        open_dlg(dlg)

    def start_date_dialog(first_time=False):
        when = tf("Inicio de la racha (AAAA-MM-DD HH:MM)", value=local_now().strftime(FMT))
        err = ft.Text("", color=DANGER)

        def save(_):
            try:
                dt = parse_dt(when.value)
            except ValueError:
                err.value = "Fecha inválida. Formato: 2026-11-01 21:30 (no puede ser futura)."
                page.update()
                return
            db.set_current_start(dt)
            close_dlg(dlg)
            render()

        dlg = dialog("¿Cuándo empezó tu racha?",
                     ft.Column([muted("Pon la fecha y hora exactas del último día que lo hiciste."), when, err],
                               tight=True, width=340, spacing=12),
                     [ft.TextButton("Cancelar", on_click=lambda _: close_dlg(dlg)),
                      gbtn("Guardar", on_click=save, height=42)])
        open_dlg(dlg)

    def survived_dialog(e=None):
        trig = dd("¿Qué provocó las ganas?", TRIGGERS)

        def save(_):
            db.add_event(local_now(), "urge", trig.value, None)
            close_dlg(dlg)
            snack("Ganas superadas. Eso es entrenamiento real.")
            go("main", 0)

        dlg = dialog("¡Lo has superado!",
                     ft.Column([muted("Anotarlo alimenta tu radar de riesgo."), trig], tight=True, width=320, spacing=12),
                     [gbtn("Guardar", on_click=save, height=42)])
        open_dlg(dlg)

    # ---- cabeceras --------------------------------------------------------
    def back_bar(heading):
        return ft.Row([
            ft.Container(content=ft.Icon(ft.Icons.ARROW_BACK_IOS_NEW, color="white", size=18), width=44, height=44,
                         border_radius=14, gradient=GRAD, alignment=ft.alignment.center, ink=True,
                         shadow=[ft.BoxShadow(blur_radius=16, color=GLOW, offset=ft.Offset(0, 6))],
                         on_click=lambda e: go("main", 0)),
            title(heading, 22),
        ], spacing=14)

    # ---- pantallas principales -------------------------------------------
    def onboarding_view():
        return padded(ft.Column([
            ft.Container(height=70),
            ft.Container(content=ft.Icon(ft.Icons.EXPLORE, size=64, color="white"), width=120, height=120,
                         border_radius=36, gradient=GRAD, alignment=ft.alignment.center,
                         shadow=[ft.BoxShadow(blur_radius=40, color=GLOW, offset=ft.Offset(0, 14))]),
            ft.Container(height=10),
            title(f"Bienvenido a {APP_NAME}", 28),
            muted("Una app privada para llevar la cuenta de tu racha y ayudarte cuando lleguen las ganas.", 15),
            ft.Container(height=20),
            gbtn("Empezar mi racha", ft.Icons.PLAY_ARROW, on_click=lambda e: start_date_dialog(True), height=56),
            ft.TextButton("Empiezo ahora mismo", on_click=lambda e: (db.start_streak(local_now()), render())),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12, scroll=ft.ScrollMode.AUTO))

    # ---- cofres de 10 días (cuelgan de la RACHA ACTUAL) -------------------------
    def chest_status():
        """Estado del cofre según el tiempo de la racha actual, no los días acumulados de rachas pasadas."""
        cur = db.current_streak()
        rows = db.chest_rows()
        days_f, sid = 0.0, None
        if cur:
            sid = cur["id"]
            days_f = (local_now() - datetime.fromisoformat(cur["start_ts"])).total_seconds() / 86400
        days = int(days_f)
        # 1) cofres pendientes: ganados sin abrir o con misión sin cumplir (incluso de rachas pasadas)
        for r in rows:
            if not r["done_ts"]:
                return {"kind": "active" if r["opened_ts"] else "ready", "n": r["n"],
                        "sid": r["streak_id"], "row": r, "days": days, "days_f": days_f}
        # 2) cofres ya alcanzados en la racha actual que aún no se han abierto
        earned = days // CHEST_EVERY
        have = {r["n"] for r in rows if r["streak_id"] == sid}
        for n in range(1, earned + 1):
            if n not in have:
                return {"kind": "ready", "n": n, "sid": sid, "row": None, "days": days, "days_f": days_f}
        return {"kind": "wait", "n": earned + 1, "sid": sid, "row": None, "days": days, "days_f": days_f}

    def chest_banner(rar, sub=""):
        g1, g2 = RARITY_GRAD[rar]
        stars = ft.Row([ft.Icon(ft.Icons.AUTO_AWESOME, color="white", size=22) for _ in range(RARITIES.index(rar) + 1)],
                       alignment=ft.MainAxisAlignment.CENTER, spacing=2)
        lines = [stars, ft.Text(f"COFRE {rar.upper()}", size=24, weight=ft.FontWeight.BOLD, color="white",
                                text_align=ft.TextAlign.CENTER)]
        if sub:
            lines.append(ft.Text(sub, size=13, color="#F0F4FF", text_align=ft.TextAlign.CENTER))
        return ft.Container(
            content=ft.Column(lines, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4),
            gradient=ft.LinearGradient(begin=ft.alignment.top_left, end=ft.alignment.bottom_right, colors=[g1, g2]),
            border_radius=20, padding=16, alignment=ft.alignment.center,
            shadow=[ft.BoxShadow(blur_radius=34, color="#88" + RARITY_COLOR[rar][1:], offset=ft.Offset(0, 8))])

    def play_chest(title_text, rar, sub, reveal, btn_label):
        """Cofre que tiembla y crece, y estalla revelando su rareza."""
        g1, g2 = RARITY_GRAD[rar]
        box = ft.Container(
            content=ft.Icon(ft.Icons.CARD_GIFTCARD, size=64, color="white"), width=120, height=120,
            border_radius=34, alignment=ft.alignment.center, rotate=0, scale=1.0,
            animate_rotation=ft.Animation(130, "easeInOut"), animate_scale=ft.Animation(130, "easeInOut"),
            gradient=ft.LinearGradient(begin=ft.alignment.top_left, end=ft.alignment.bottom_right, colors=[B1, B2]),
            shadow=[ft.BoxShadow(blur_radius=30, color=GLOW, offset=ft.Offset(0, 8))])
        dlg = dialog(title_text,
                     ft.Column([ft.Row([box], alignment=ft.MainAxisAlignment.CENTER),
                                ft.Row([muted("Abriendo…", 14)], alignment=ft.MainAxisAlignment.CENTER)],
                               tight=True, width=320, spacing=14), [])

        def ok(_):
            close_dlg(dlg)
            render()

        async def anim():
            for i in range(10):
                box.rotate = 0.14 if i % 2 == 0 else -0.14
                box.scale = 1.0 + i * 0.05
                if i >= 6:
                    box.gradient = ft.LinearGradient(begin=ft.alignment.top_left, end=ft.alignment.bottom_right,
                                                     colors=[g1, g2])
                page.update()
                await asyncio.sleep(0.14)
            box.rotate = 0
            box.scale = 1.4
            page.update()
            await asyncio.sleep(0.2)
            dlg.content = ft.Column([chest_banner(rar, sub), *reveal], tight=True, width=320, spacing=12,
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                    scroll=ft.ScrollMode.AUTO)
            dlg.actions = [gbtn(btn_label, on_click=ok, height=42)]
            page.update()

        open_dlg(dlg)
        page.run_task(anim)

    def open_chest(n, sid):
        rar = roll_rarity(n)
        mission = random.choice(MISSIONS[rar])
        mine = (db.get("my_reward") or "").strip()
        if mine:  # tu recompensa personal manda; los cofres épicos y legendarios añaden un bonus
            reward = mine + (f"\n\n{random.choice(BONUS[rar])}" if rar in BONUS else "")
        else:
            reward = random.choice(REWARDS[rar])
        owned = {r["badge"] for r in db.chest_rows() if r["badge"]}
        badge = random.choice([b for b in BADGES[rar] if b not in owned] or BADGES[rar])
        db.open_chest(sid, n, mission, reward, rar, badge)
        play_chest(f"¡Cofre del día {n * CHEST_EVERY}!", rar, f"Insignia: {badge}",
                   [muted("Tu misión:"),
                    ft.Text(mission, size=17, weight=ft.FontWeight.BOLD, color=TXT, text_align=ft.TextAlign.CENTER),
                    muted("Cúmplela y se revela tu recompensa.")], "Aceptar")

    def finish_chest(n, sid):
        r = next(x for x in db.chest_rows() if x["streak_id"] == sid and x["n"] == n)
        db.finish_chest(sid, n)
        rar = r["rarity"] or "Común"
        play_chest("¡Misión cumplida!", rar, f"Insignia conseguida: {r['badge']}" if r["badge"] else "",
                   [muted("Tu recompensa:"),
                    ft.Text(r["reward"] or "", size=18, weight=ft.FontWeight.BOLD, color=RARITY_COLOR[rar],
                            text_align=ft.TextAlign.CENTER),
                    muted("Disfrútala sin culpa. Es tuya.")], "Genial")

    def chest_card():
        st = chest_status()
        kind, n, r = st["kind"], st["n"], st["row"]
        target = n * CHEST_EVERY
        cur = db.current_streak()
        if kind == "ready":
            old = bool(r) and cur is not None and r["streak_id"] != cur["id"]
            return card(ft.Row([
                ft.Icon(ft.Icons.CARD_GIFTCARD, color=WARN, size=30),
                ft.Column([title(f"Cofre del día {target}", 16),
                           muted("Ganado en una racha anterior · listo para abrir" if old
                                 else "Está listo para abrir", 12)], spacing=0, expand=True),
                gbtn("Abrir", on_click=lambda e: open_chest(n, st["sid"]), height=40)], spacing=12))
        if kind == "active":
            rar = r["rarity"] or "Común"
            return card(ft.Column([
                ft.Row([ft.Icon(ft.Icons.AUTO_AWESOME, color=RARITY_COLOR[rar], size=24),
                        title(f"Cofre {rar} · día {target}", 16)], spacing=10),
                muted("Tu misión", 12),
                ft.Text(r["mission"] or "", color=TXT, size=15),
                muted(f"Insignia en juego: {r['badge']}" if r["badge"] else "", 12),
                muted("Recompensa: sorpresa hasta que la cumplas", 12),
                gbtn("Misión cumplida", ft.Icons.CHECK, on_click=lambda e: finish_chest(n, st["sid"]),
                     expand=True, height=46),
            ], spacing=8))
        left = target - st["days"]
        frac = max(0.0, min(1.0, (st["days_f"] - (n - 1) * CHEST_EVERY) / CHEST_EVERY))
        return card(ft.Column([
            ft.Row([ft.Icon(ft.Icons.CARD_GIFTCARD, color=MUT, size=22),
                    ft.Text(f"Próximo cofre en {left} {'día' if left == 1 else 'días'}", color=TXT, expand=True)],
                   spacing=10),
            ft.ProgressBar(value=frac, color=B1, bgcolor=CARD_IN, bar_height=8, border_radius=4),
        ], spacing=10))

    def home_view():
        cur = db.current_streak()
        if not cur:
            return onboarding_view()
        start = datetime.fromisoformat(cur["start_ts"])
        secs = (local_now() - start).total_seconds()
        d, h, m, s = split_duration(secs)
        days_f = secs / 86400
        nxt = next(((n, name) for n, name in MILESTONES if n > days_f), None)
        record = db.record_seconds()
        score, level, color, _, _ = risk_info(db)

        refs["days"] = ft.Text(str(d), size=72, weight=ft.FontWeight.BOLD, color="white")
        refs["hms"] = ft.Text(f"{h:02d}h {m:02d}m {s:02d}s", size=16, color="#DDE8FF")
        refs["ring"] = ft.ProgressRing(value=min(1.0, days_f / nxt[0]) if nxt else 1.0, width=220, height=220,
                                       stroke_width=10, color="white", bgcolor="#33FFFFFF")
        refs["next"] = ft.Text(
            f"Próximo hito: {nxt[1]} · faltan {human(nxt[0] * 86400 - secs)}" if nxt else "¡Has superado todos los hitos!",
            size=13, color="#DDE8FF", text_align=ft.TextAlign.CENTER)
        refs["start"] = start
        refs["d0"] = d

        ring = ft.Stack([
            refs["ring"],
            ft.Container(width=220, height=220, alignment=ft.alignment.center,
                         content=ft.Column([ft.Text("días", size=14, color="#DDE8FF"), refs["days"], refs["hms"]],
                                           horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                           alignment=ft.MainAxisAlignment.CENTER, spacing=0)),
        ])
        chip = ft.Container(
            content=ft.Row([ft.Container(width=8, height=8, border_radius=8, bgcolor=color),
                            ft.Text(f"Riesgo: {level}", size=12, color="white")], spacing=6, tight=True),
            padding=ft.padding.symmetric(horizontal=12, vertical=6), border_radius=20, bgcolor="#33000000")
        hero = ft.Container(
            content=ft.Column([
                ft.Row([ft.Text(APP_NAME, size=22, weight=ft.FontWeight.BOLD, color="white"), chip],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Container(height=6),
                ft.Row([ring], alignment=ft.MainAxisAlignment.CENTER),
                ft.Row([refs["next"]], alignment=ft.MainAxisAlignment.CENTER),
                ft.Container(
                    content=ft.Row([ft.Icon(ft.Icons.EMOJI_EVENTS, size=16, color="white"),
                                    ft.Text(f"Récord: {human(max(record, secs))}", size=13, color="white")],
                                   spacing=6, tight=True),
                    padding=ft.padding.symmetric(horizontal=14, vertical=6), border_radius=20, bgcolor="#33000000"),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
            padding=ft.padding.only(left=20, right=20, top=18, bottom=26),
            border_radius=ft.border_radius.only(bottom_left=40, bottom_right=40),
            gradient=ft.LinearGradient(begin=ft.alignment.top_center, end=ft.alignment.bottom_center,
                                       colors=["#58A6FF", "#2F6BFF", "#25409A"]),
            shadow=[ft.BoxShadow(blur_radius=30, color="#66000000", offset=ft.Offset(0, 12))],
        )
        info = card(ft.Row([
            ft.Icon(ft.Icons.CALENDAR_MONTH, size=20, color=B1),
            ft.Column([muted("Inicio de la racha", 12), ft.Text(start.strftime("%d/%m/%Y · %H:%M"), color=TXT,
                                                                 weight=ft.FontWeight.W_600)], spacing=0),
        ], spacing=12))
        quote = card(ft.Text(random.choice(MESSAGES), italic=True, size=15, color=TXT))
        return ft.Column([
            hero,
            ft.Container(padding=ft.padding.symmetric(horizontal=16), content=ft.Column([
                ft.Container(height=4), info, chest_card(), quote,
                sbtn("Registrar recaída", ft.Icons.REPLAY, on_click=relapse_dialog, expand=True),
                ft.Container(height=100),
            ], spacing=16)),
        ], spacing=0, scroll=ft.ScrollMode.AUTO, expand=True)

    def progress_view():
        cur = db.current_streak()
        secs = (local_now() - datetime.fromisoformat(cur["start_ts"])).total_seconds() if cur else 0
        days_f = secs / 86400
        record = max(db.record_seconds(), secs)

        def stat(label, value, icon):
            return card(ft.Column([ft.Icon(icon, color=B1, size=22),
                                   ft.Text(value, size=22, weight=ft.FontWeight.BOLD, color=TXT),
                                   muted(label, 12)], spacing=2), expand=True)

        stats = ft.Column([
            ft.Row([stat("Racha actual", human(secs), ft.Icons.LOCAL_FIRE_DEPARTMENT),
                    stat("Récord", human(record), ft.Icons.EMOJI_EVENTS)], spacing=14),
            ft.Row([stat("Días limpios totales", str(db.total_clean_days()), ft.Icons.CHECK_CIRCLE),
                    stat("Ganas superadas", str(db.count_events("urge")), ft.Icons.SHIELD)], spacing=14),
            ft.Row([stat("Recaídas", str(db.count_events("relapse")), ft.Icons.REPLAY),
                    stat("Retos superados", str(db.count_retos_done()), ft.Icons.BOLT)], spacing=14),
        ], spacing=14)

        def mrow(n, name):
            done = days_f >= n
            badge = ft.Container(
                content=ft.Icon(ft.Icons.CHECK if done else ft.Icons.LOCK_OUTLINE, size=14,
                                color="white" if done else MUT),
                width=26, height=26, border_radius=13, alignment=ft.alignment.center,
                gradient=GRAD if done else None, bgcolor=None if done else CARD_IN)
            return ft.Row([badge, ft.Text(name, color=TXT if done else MUT, expand=True),
                           muted(f"{n} d", 12)], spacing=12)

        hitos = card(ft.Column([title("Hitos", 17)] + [mrow(n, name) for n, name in MILESTONES], spacing=10))

        ch = [r for r in db.chest_rows() if r["opened_ts"]]

        def chest_line(r):
            rar = r["rarity"] or "Común"
            col = RARITY_COLOR[rar]
            hecho = bool(r["done_ts"])
            return ft.Row([
                ft.Icon(ft.Icons.EMOJI_EVENTS if hecho else ft.Icons.CARD_GIFTCARD, size=20, color=col),
                ft.Column([ft.Text(r["badge"] or "Cofre", color=TXT, weight=ft.FontWeight.W_600),
                           ft.Text(f"{rar} · cofre del día {r['n'] * CHEST_EVERY}", size=11, color=col)],
                          spacing=0, expand=True),
                muted("Cumplida" if hecho else "Pendiente", 12)], spacing=12)

        chests_card = card(ft.Column([title("Tu colección de cofres", 17)] + (
            [chest_line(r) for r in reversed(ch)] or [muted("Tu primer cofre llega a los 10 días de racha.")]),
            spacing=10))

        score, level, color, hist, why = risk_info(db)
        mx = max(hist) or 1
        bars = ft.Row([
            ft.Column([
                ft.Container(width=10, height=4 + 70 * hist[i] / mx, border_radius=4,
                             gradient=ft.LinearGradient(begin=ft.alignment.top_center, end=ft.alignment.bottom_center,
                                                        colors=[B1, B2]) if hist[i] else None,
                             bgcolor=None if hist[i] else CARD_IN),
                ft.Text(str(i) if i % 6 == 0 else "", size=9, color=MUT)],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2,
                alignment=ft.MainAxisAlignment.END, height=100)
            for i in range(24)], spacing=1, alignment=ft.MainAxisAlignment.CENTER)
        radar = card(ft.Column([
            ft.Row([ft.Icon(ft.Icons.RADAR, color=color), title("Radar de riesgo", 17)]),
            ft.Row([ft.Text(level, size=28, weight=ft.FontWeight.BOLD, color=color), muted(f"{score}/100")]),
            ft.ProgressBar(value=score / 100, color=color, bgcolor=CARD_IN, bar_height=8, border_radius=4),
            *[muted("• " + w) for w in why],
            muted("Horas del día en las que te han venido ganas o recaídas:", 12),
            bars,
            muted("Cuantos más eventos registres, más preciso será.", 11),
        ], spacing=10))

        trig_rows = db.q("SELECT trigger_name t, COUNT(*) n FROM events WHERE trigger_name IS NOT NULL "
                         "GROUP BY trigger_name ORDER BY n DESC LIMIT 5")
        trig = card(ft.Column([title("Tus disparadores", 17)] + (
            [ft.Row([ft.Text(r["t"], expand=True, color=TXT), ft.Text(str(r["n"]), color=B1,
                                                                       weight=ft.FontWeight.BOLD)])
             for r in trig_rows] if trig_rows else [muted("Aún no hay datos.")]), spacing=8))

        hist_card = card(ft.Column([title("Historial de rachas", 17)] + [
            ft.Row([
                ft.Text(datetime.fromisoformat(r["start_ts"]).strftime("%d/%m/%y %H:%M"), size=13, color=TXT,
                        expand=True),
                ft.Text(human(((datetime.fromisoformat(r["end_ts"]) if r["end_ts"] else local_now())
                               - datetime.fromisoformat(r["start_ts"])).total_seconds()), size=13, color=B1),
            ]) for r in db.all_streaks()[:8]], spacing=8))

        return padded(ft.Column([
            ft.Container(height=14), title("Tu progreso", 26), stats, radar, trig, hitos, chests_card, hist_card,
            ft.Container(height=100),
        ], spacing=16, scroll=ft.ScrollMode.AUTO))

    def diary_view():
        today = local_now().strftime("%Y-%m-%d")
        ci = db.q("SELECT * FROM checkins WHERE day=?", (today,))

        def slider(**kw):
            return ft.Slider(active_color=B1, inactive_color=CARD_IN, thumb_color=B1, **kw)

        mood = slider(min=1, max=5, divisions=4, value=ci[0]["mood"] if ci else 3, label="{value}")
        stress = slider(min=1, max=5, divisions=4, value=ci[0]["stress"] if ci else 3, label="{value}")
        sleep = slider(min=0, max=12, divisions=24, value=ci[0]["sleep"] if ci else 7, label="{value} h")

        def save_ci(e):
            db.x("INSERT INTO checkins(day,mood,stress,sleep) VALUES(?,?,?,?) ON CONFLICT(day) DO UPDATE SET "
                 "mood=excluded.mood, stress=excluded.stress, sleep=excluded.sleep",
                 (today, int(mood.value), int(stress.value), float(sleep.value)))
            snack("Check-in guardado")
            render()

        checkin = card(ft.Column([
            title("Check-in de hoy", 17),
            muted("Ánimo (1 mal – 5 genial)"), mood,
            muted("Estrés (1 calma – 5 mucho)"), stress,
            muted("Horas dormidas"), sleep,
            gbtn("Guardar", ft.Icons.CHECK, on_click=save_ci, height=46),
        ], spacing=2))

        def notes_card(kind, heading, hint, fields):
            tfs = [tf(l, dense=True) for l in fields]

            def add(e):
                vals = [t.value.strip() for t in tfs if t.value]
                if len(vals) < len(tfs):
                    return
                text = vals[0] if kind == "reason" else f"Si {vals[0]}, entonces {vals[1]}"
                db.x("INSERT INTO notes(kind,text) VALUES(?,?)", (kind, text))
                render()

            def rm(nid):
                db.x("DELETE FROM notes WHERE id=?", (nid,))
                render()

            items = [inset(ft.Row([ft.Text(r["text"], expand=True, size=14, color=TXT),
                                   ft.IconButton(ft.Icons.CLOSE, icon_size=16, icon_color=MUT,
                                                 on_click=lambda e, i=r["id"]: rm(i))]), pad=10)
                     for r in db.notes(kind)]
            return card(ft.Column([title(heading, 17), muted(hint), *items, *tfs,
                                   sbtn("Añadir", ft.Icons.ADD, on_click=add, expand=True, height=44)], spacing=10))

        reasons = notes_card("reason", "Mis razones",
                             "Por qué quiero cambiar. Las verás cuando pulses «Tengo ganas».", ["Mi razón"])
        plans = notes_card("plan", "Plan «si… entonces…»",
                           "Decide ahora qué harás ante cada disparador. Funciona mucho mejor que la fuerza de voluntad en el momento.",
                           ["Si… (ej: estoy solo en la cama de noche)",
                            "Entonces… (ej: salgo al salón y llamo a un amigo)"])
        return padded(ft.Column([ft.Container(height=14), title("Diario", 26), checkin, reasons, plans,
                                 ft.Container(height=100)], spacing=16, scroll=ft.ScrollMode.AUTO))

    def settings_view():
        def set_pin(e):
            pin = tf("Nuevo PIN (4-8 dígitos)", password=True, can_reveal_password=True,
                     keyboard_type=ft.KeyboardType.NUMBER)
            err = ft.Text("", color=DANGER)

            def ok(_):
                if not pin.value or not pin.value.isdigit() or not 4 <= len(pin.value) <= 8:
                    err.value = "Debe tener entre 4 y 8 dígitos."
                    page.update()
                    return
                db.set("pin_hash", hash_pin(pin.value))
                close_dlg(dlg)
                snack("PIN activado")
                render()

            dlg = dialog("Bloqueo con PIN", ft.Column([pin, err], tight=True, width=300, spacing=10),
                         [ft.TextButton("Cancelar", on_click=lambda _: close_dlg(dlg)),
                          gbtn("Activar", on_click=ok, height=42)])
            open_dlg(dlg)

        def clear_pin(e):
            db.delete_setting("pin_hash")
            snack("PIN desactivado")
            render()

        def wipe(e):
            def yes(_):
                db.wipe()
                close_dlg(dlg)
                render()
            dlg = dialog("¿Borrar todos los datos?",
                         ft.Text("Se perderán rachas, registros y récords. No se puede deshacer.", color=MUT),
                         [ft.TextButton("Cancelar", on_click=lambda _: close_dlg(dlg)),
                          gbtn("Borrar todo", on_click=yes, height=42, danger=True)])
            open_dlg(dlg)

        my_reward = tf("Mi recompensa personal (opcional)", value=db.get("my_reward") or "")

        def save_reward(e):
            db.set("my_reward", (my_reward.value or "").strip())
            snack("Recompensa guardada")

        has_pin = bool(db.get("pin_hash"))
        return padded(ft.Column([
            ft.Container(height=14), title("Ajustes", 26),
            card(ft.Column([title("Racha", 17),
                            sbtn("Corregir inicio de la racha", ft.Icons.EDIT_CALENDAR, expand=True,
                                 on_click=lambda e: start_date_dialog())], spacing=12)),
            card(ft.Column([
                title("Recompensas", 17),
                muted("Si escribes una, saldrá en tus cofres (los épicos y legendarios añaden un bonus). Si no, te sorprenderá una de la app según la rareza del cofre."),
                my_reward,
                sbtn("Guardar recompensa", ft.Icons.SAVE, on_click=save_reward, expand=True),
            ], spacing=12)),
            card(ft.Column([
                title("Privacidad", 17),
                muted("La app no usa palabras explícitas y todo se guarda solo en tu móvil."),
                ft.Row([sbtn("Cambiar PIN" if has_pin else "Activar PIN", ft.Icons.LOCK, on_click=set_pin, expand=True),
                        *([sbtn("Quitar", on_click=clear_pin)] if has_pin else [])], spacing=12),
            ], spacing=12)),
            card(ft.Column([title("Datos", 17),
                            sbtn("Borrar todos los datos", ft.Icons.DELETE_FOREVER, expand=True, color=DANGER,
                                 on_click=wipe)], spacing=12)),
            ft.Container(height=100),
        ], spacing=16, scroll=ft.ScrollMode.AUTO))

    # ---- SOS: un reto de Gemini para distraerte --------------------------------
    def sos_view():
        reasons = [r["text"] for r in db.notes("reason")]
        plans = [r["text"] for r in db.notes("plan")]
        tid = state["task"]
        cur = {"id": None, "loading": False}

        spin = ft.Row([ft.ProgressRing(width=22, height=22, stroke_width=3, color=B1),
                       muted("Buscando un reto para ti…", 14)], spacing=12)
        reto_tipo = ft.Text("", size=12, weight=ft.FontWeight.BOLD, color=B1)
        reto_t = ft.Text("", size=21, weight=ft.FontWeight.BOLD, color=TXT)
        reto_src = muted("", 11)
        reto_card = card(ft.Column([
            ft.Row([ft.Icon(ft.Icons.BOLT, color=WARN, size=22), title("Tu reto", 16)], spacing=8),
            spin, reto_tipo, reto_t, reto_src], spacing=10))

        async def cargar():
            await asyncio.sleep(0.05)
            if cur["loading"]:
                return
            cur["loading"] = True
            cur["id"] = None
            spin.visible = True
            reto_t.value = reto_tipo.value = reto_src.value = ""
            page.update()
            try:
                texto, tipo, origen = await asyncio.to_thread(generar_reto, db)
                if state["task"] != tid:  # ya te has ido de la pantalla: no se gasta el reto
                    return
                cur["id"] = await asyncio.to_thread(db.add_reto, texto, tipo)
                reto_t.value = texto
                reto_tipo.value = tipo.upper()
                reto_src.value = "" if origen == "ia" else "Reto de reserva (no se pudo contactar con la IA)"
            except Exception as ex:
                print(f"Error mostrando reto: {ex}")
                reto_t.value = random.choice(URGE_PLAN)
            finally:
                cur["loading"] = False
                if state["task"] == tid:
                    spin.visible = False
                    page.update()

        def otro(e):
            if not cur["loading"]:
                page.run_task(cargar)

        def hecho(e):
            if cur["loading"]:
                return
            if cur["id"]:
                db.finish_reto(cur["id"])
            survived_dialog()

        reason_card = card(ft.Column([
            ft.Text("Recuerda por qué lo haces", weight=ft.FontWeight.BOLD, color=TXT),
            ft.Text(random.choice(reasons) if reasons else "Añade tus razones en la pestaña Diario.",
                    italic=True, color=B1),
        ], spacing=6))
        plan_items = plans or URGE_PLAN
        plan_card = card(ft.Column([ft.Text("Tu plan" if plans else "Haz esto ahora", weight=ft.FontWeight.BOLD,
                                            color=TXT),
                                    *[ft.Text("• " + p, size=14, color=MUT) for p in plan_items[:5]]], spacing=6))
        page.run_task(cargar)
        return padded(ft.Column([
            ft.Container(height=14),
            back_bar("Aquí estoy contigo"),
            muted("Las ganas suben, llegan a un pico y bajan solas. Ocupa la mente con esto mientras pasan.", 14),
            reto_card,
            gbtn("Reto cumplido", ft.Icons.CHECK, on_click=hecho, expand=True, height=54),
            sbtn("Otro reto", ft.Icons.REFRESH, on_click=otro, expand=True),
            reason_card, plan_card,
            ft.TextButton("He recaído", on_click=relapse_dialog),
            ft.Container(height=20),
        ], spacing=14, scroll=ft.ScrollMode.AUTO))

    # ---- bloqueo ----------------------------------------------------------
    def lock_view():
        pin = tf("PIN", password=True, keyboard_type=ft.KeyboardType.NUMBER, width=220,
                 text_align=ft.TextAlign.CENTER, autofocus=True)
        err = ft.Text("", color=DANGER)

        def check(e):
            if hash_pin(pin.value or "") == db.get("pin_hash"):
                state["locked"] = False
                render()
            else:
                err.value = "PIN incorrecto"
                pin.value = ""
                page.update()

        pin.on_submit = check
        return ft.Column([
            ft.Container(height=140),
            ft.Container(content=ft.Icon(ft.Icons.EXPLORE, size=56, color="white"), width=104, height=104,
                         border_radius=32, gradient=GRAD, alignment=ft.alignment.center,
                         shadow=[ft.BoxShadow(blur_radius=36, color=GLOW, offset=ft.Offset(0, 12))]),
            title(APP_NAME, 28), pin, err, gbtn("Entrar", ft.Icons.LOCK_OPEN, on_click=check),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=16, expand=True)

    # ---- navegación inferior ---------------------------------------------
    def nav_bar():
        items = [(ft.Icons.HOME_ROUNDED, 0), (ft.Icons.INSIGHTS, 1), (ft.Icons.EDIT_NOTE, 2),
                 (ft.Icons.SETTINGS_ROUNDED, 3)]
        return ft.Container(
            content=ft.Row([tile(ic, lambda e, i=i: go("main", i), selected=state["tab"] == i) for ic, i in items],
                           alignment=ft.MainAxisAlignment.SPACE_AROUND),
            padding=ft.padding.symmetric(vertical=12, horizontal=8), bgcolor=CARD,
            border_radius=ft.border_radius.only(top_left=30, top_right=30),
            shadow=[ft.BoxShadow(blur_radius=24, color=SH_DARK, offset=ft.Offset(0, -6))])

    def sos_pill():
        return ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.SHIELD, color="white", size=20),
                            ft.Text("Tengo ganas", color="white", weight=ft.FontWeight.BOLD)],
                           spacing=8, tight=True),
            gradient=GRAD, border_radius=30, padding=ft.padding.symmetric(horizontal=20, vertical=14),
            on_click=lambda e: go("sos"), ink=True,
            shadow=[ft.BoxShadow(blur_radius=26, color="#992F6BFF", offset=ft.Offset(0, 10))])

    # ---- render -----------------------------------------------------------
    def render():
        refs.clear()
        page.on_keyboard_event = None
        page.controls.clear()
        page.navigation_bar = None
        page.floating_action_button = None
        page.bgcolor = BG

        if state["locked"]:
            page.add(ft.SafeArea(lock_view(), expand=True))
            page.update()
            return

        scr = state["screen"]
        if scr == "main":
            body = [home_view, progress_view, diary_view, settings_view][state["tab"]]()
            has_streak = db.current_streak() is not None
            layers = [ft.Column([ft.Container(body, expand=True), nav_bar() if has_streak else ft.Container()],
                                spacing=0, expand=True)]
            if has_streak:
                layers.append(ft.Container(sos_pill(), right=18, bottom=96))
            page.add(ft.SafeArea(ft.Stack(layers, expand=True), expand=True))
        else:
            body = {"sos": sos_view}[scr]()
            page.add(ft.SafeArea(ft.Container(body, expand=True), expand=True))
        page.update()

    # ---- reloj en vivo ----------------------------------------------------
    async def ticker():
        while True:
            await asyncio.sleep(1)
            try:
                if state["screen"] == "main" and state["tab"] == 0 and "days" in refs and not state["locked"]:
                    secs = (local_now() - refs["start"]).total_seconds()
                    d, h, m, s = split_duration(secs)
                    if d != refs.get("d0"):  # ha cambiado el día: se refresca también la tarjeta del cofre
                        render()
                        continue
                    refs["days"].value = str(d)
                    refs["hms"].value = f"{h:02d}h {m:02d}m {s:02d}s"
                    days_f = secs / 86400
                    nxt = next(((n, name) for n, name in MILESTONES if n > days_f), None)
                    refs["ring"].value = min(1.0, days_f / nxt[0]) if nxt else 1.0
                    if nxt:
                        refs["next"].value = f"Próximo hito: {nxt[1]} · faltan {human(nxt[0] * 86400 - secs)}"
                    page.update()
            except Exception:
                pass

    render()
    page.run_task(ticker)


if __name__ == "__main__":
    get_db()
    if os.getenv("PORT"):  # en Render: modo web
        ft.app(target=main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0", port=int(os.getenv("PORT")))
    else:  # en tu PC: ventana normal
        ft.app(target=main)
