"""
Rumbo - tu racha, tu control.   (v2: interfaz neumórfica + runner infinito)

App discreta para dejar un hábito: contador de racha, registro de recaídas,
botón SOS (runner arcade, respiración, ola de ganas), radar de riesgo y plan personal.

Flet 0.28.3  ·  SQLite local  ·  sin conexión a internet
    pip install flet==0.28.3 flet-desktop==0.28.3
    python main.py            (probar en PC)
    flet build apk            (generar APK)
"""
import asyncio
import hashlib
import math
import os
import random
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import flet as ft
import flet.canvas as fcv

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
CHEST_EVERY = 10  # un cofre cada 10 días limpios acumulados
MISSIONS = [
    "Sal a caminar 30 minutos sin el móvil",
    "Escribe 3 cosas que han mejorado desde que empezaste",
    "Haz 20 minutos de ejercicio",
    "Ordena un rincón de tu casa o de tu habitación",
    "Escribe a alguien que aprecias y propón un plan",
    "Cocina algo que te guste de verdad",
    "Dedica 30 minutos a aprender algo que te interese",
    "Pasa una tarde fuera de casa haciendo un plan distinto",
]
REWARDS = [
    "Date un capricho: tu comida favorita",
    "Una tarde libre para ti: peli, serie o juego sin culpa",
    "Compra algo pequeño que llevas tiempo queriendo",
    "Un café o un postre en tu sitio favorito",
    "Una noche larga de sueño, sin alarma",
    "Un plan con amigos, y lo eliges tú",
]
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
"""

FMT = "%Y-%m-%d %H:%M"


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
        now = datetime.now()
        for r in self.all_streaks():
            s = datetime.fromisoformat(r["start_ts"])
            e = datetime.fromisoformat(r["end_ts"]) if r["end_ts"] else now
            best = max(best, (e - s).total_seconds())
        return best

    def total_clean_days(self):
        now = datetime.now()
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

    def best_score(self, game):
        r = self.q("SELECT MAX(score) m FROM scores WHERE game=?", (game,))
        return r[0]["m"] or 0

    def add_score(self, game, score):
        self.x("INSERT INTO scores(game,score,ts) VALUES(?,?,?)", (game, score, datetime.now().isoformat()))

    def chests(self):
        return {r["n"]: r for r in self.q("SELECT * FROM rewards")}

    def open_chest(self, n, mission, reward):
        self.x("INSERT OR IGNORE INTO rewards(n,mission,reward,opened_ts) VALUES(?,?,?,?)",
               (n, mission, reward, datetime.now().isoformat()))

    def finish_chest(self, n):
        self.x("UPDATE rewards SET done_ts=? WHERE n=?", (datetime.now().isoformat(), n))

    def notes(self, kind):
        return self.q("SELECT * FROM notes WHERE kind=? ORDER BY id DESC", (kind,))

    def wipe(self):
        for t in ("settings", "streaks", "events", "checkins", "scores", "notes", "rewards"):
            self.x(f"DELETE FROM {t}")


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def parse_dt(text):
    dt = datetime.strptime(text.strip(), FMT)
    if dt > datetime.now() + timedelta(minutes=1):
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
    now = datetime.now()
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
    db = DB(DB_PATH)
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
        when = tf("Cuándo (AAAA-MM-DD HH:MM)", value=datetime.now().strftime(FMT))
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
        when = tf("Inicio de la racha (AAAA-MM-DD HH:MM)", value=datetime.now().strftime(FMT))
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
            db.add_event(datetime.now(), "urge", trig.value, None)
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
            ft.TextButton("Empiezo ahora mismo", on_click=lambda e: (db.start_streak(datetime.now()), render())),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12, scroll=ft.ScrollMode.AUTO))

    # ---- cofres de 10 días -------------------------------------------------
    def chest_status():
        total = db.total_clean_days()
        earned = total // CHEST_EVERY
        rows = db.chests()
        for n in range(1, earned + 1):
            r = rows.get(n)
            if r is None:
                return "ready", n, None, total
            if not r["done_ts"]:
                return "active", n, r, total
        return "wait", earned + 1, None, total

    def open_chest(n):
        mission = random.choice(MISSIONS)
        mine = (db.get("my_reward") or "").strip()
        db.open_chest(n, mission, mine or random.choice(REWARDS))

        def ok(_):
            close_dlg(dlg)
            render()

        dlg = dialog(f"¡Cofre del día {n * CHEST_EVERY}!",
                     ft.Column([muted("Te lo has ganado. Tu misión:"),
                                ft.Text(mission, size=17, weight=ft.FontWeight.BOLD, color=TXT),
                                muted("Cúmplela y se revela tu recompensa.")], tight=True, width=320, spacing=10),
                     [gbtn("Aceptar", on_click=ok, height=42)])
        open_dlg(dlg)

    def finish_chest(n):
        r = db.chests()[n]
        db.finish_chest(n)

        def ok(_):
            close_dlg(dlg)
            render()

        dlg = dialog("¡Misión cumplida!",
                     ft.Column([muted("Tu recompensa:"),
                                ft.Text(r["reward"], size=17, weight=ft.FontWeight.BOLD, color=OK),
                                muted("Disfrútala sin culpa. Es tuya.")], tight=True, width=320, spacing=10),
                     [gbtn("Genial", on_click=ok, height=42)])
        open_dlg(dlg)

    def chest_card():
        kind, n, r, total = chest_status()
        target = n * CHEST_EVERY
        if kind == "ready":
            return card(ft.Row([
                ft.Icon(ft.Icons.CARD_GIFTCARD, color=WARN, size=30),
                ft.Column([title(f"Cofre del día {target}", 16), muted("Está listo para abrir", 12)],
                          spacing=0, expand=True),
                gbtn("Abrir", on_click=lambda e: open_chest(n), height=40)], spacing=12))
        if kind == "active":
            return card(ft.Column([
                ft.Row([ft.Icon(ft.Icons.CARD_GIFTCARD, color=WARN, size=24), title(f"Cofre del día {target}", 16)],
                       spacing=10),
                muted("Tu misión", 12),
                ft.Text(r["mission"], color=TXT, size=15),
                muted("Recompensa: sorpresa hasta que la cumplas", 12),
                gbtn("Misión cumplida", ft.Icons.CHECK, on_click=lambda e: finish_chest(n), expand=True, height=46),
            ], spacing=8))
        left = target - total
        return card(ft.Column([
            ft.Row([ft.Icon(ft.Icons.CARD_GIFTCARD, color=MUT, size=22),
                    ft.Text(f"Próximo cofre en {left} {'día' if left == 1 else 'días'}", color=TXT, expand=True)],
                   spacing=10),
            ft.ProgressBar(value=1 - left / CHEST_EVERY, color=B1, bgcolor=CARD_IN, bar_height=8, border_radius=4),
        ], spacing=10))

    def home_view():
        cur = db.current_streak()
        if not cur:
            return onboarding_view()
        start = datetime.fromisoformat(cur["start_ts"])
        secs = (datetime.now() - start).total_seconds()
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
        secs = (datetime.now() - datetime.fromisoformat(cur["start_ts"])).total_seconds() if cur else 0
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
                    stat("Récord runner", f"{db.best_score('runner')} m", ft.Icons.DIRECTIONS_RUN)], spacing=14),
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

        ch = db.chests()
        chest_rows = [ft.Row([
            ft.Icon(ft.Icons.CARD_GIFTCARD, size=18, color=OK if ch[n]["done_ts"] else WARN),
            ft.Text(f"Día {n * CHEST_EVERY}", color=TXT, expand=True),
            muted("Cumplida" if ch[n]["done_ts"] else "Pendiente", 12)], spacing=12) for n in sorted(ch)]
        chests_card = card(ft.Column([title("Cofres de 10 días", 17)] + (
            chest_rows or [muted("Tu primer cofre llega a los 10 días limpios.")]), spacing=10))

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
                ft.Text(human(((datetime.fromisoformat(r["end_ts"]) if r["end_ts"] else datetime.now())
                               - datetime.fromisoformat(r["start_ts"])).total_seconds()), size=13, color=B1),
            ]) for r in db.all_streaks()[:8]], spacing=8))

        return padded(ft.Column([
            ft.Container(height=14), title("Tu progreso", 26), stats, radar, trig, hitos, chests_card, hist_card,
            ft.Container(height=100),
        ], spacing=16, scroll=ft.ScrollMode.AUTO))

    def diary_view():
        today = datetime.now().strftime("%Y-%m-%d")
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
                muted("Si escribes una, saldrá en tus cofres. Si no, te sorprenderá una de la app."),
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

    # ---- SOS --------------------------------------------------------------
    def sos_view():
        reasons = [r["text"] for r in db.notes("reason")]
        plans = [r["text"] for r in db.notes("plan")]

        def option(icon, label, sub, target):
            return card(ft.Row([
                ft.Container(content=ft.Icon(icon, color="white", size=26), width=52, height=52, border_radius=16,
                             gradient=GRAD, alignment=ft.alignment.center,
                             shadow=[ft.BoxShadow(blur_radius=14, color=GLOW, offset=ft.Offset(0, 5))]),
                ft.Column([ft.Text(label, weight=ft.FontWeight.BOLD, color=TXT, size=16), muted(sub, 12)],
                          spacing=0, expand=True),
                ft.Icon(ft.Icons.CHEVRON_RIGHT, color=MUT)], spacing=14),
                on_click=lambda e: go(target), ink=True)

        reason_card = card(ft.Column([
            ft.Text("Recuerda por qué lo haces", weight=ft.FontWeight.BOLD, color=TXT),
            ft.Text(random.choice(reasons) if reasons else "Añade tus razones en la pestaña Diario.",
                    italic=True, color=B1),
        ], spacing=6))
        plan_items = plans or URGE_PLAN
        plan_card = card(ft.Column([ft.Text("Tu plan" if plans else "Haz esto ahora", weight=ft.FontWeight.BOLD,
                                            color=TXT),
                                    *[ft.Text("• " + p, size=14, color=MUT) for p in plan_items[:5]]], spacing=6))
        return padded(ft.Column([
            ft.Container(height=14),
            back_bar("Aquí estoy contigo"),
            muted("Las ganas son una ola: suben, llegan a un pico y bajan solas. Elige algo para cruzarla.", 14),
            option(ft.Icons.DIRECTIONS_RUN, "Runner", "Corre, esquiva y supera tu récord de metros", "runner"),
            option(ft.Icons.AIR, "Respirar", "Ciclo guiado 4-7-8", "breath"),
            option(ft.Icons.TIMER, "Surfear la ola", "10 minutos de cuenta atrás", "wave"),
            reason_card, plan_card,
            gbtn("Lo he superado", ft.Icons.CHECK, on_click=survived_dialog, expand=True, height=54),
            ft.TextButton("He recaído", on_click=relapse_dialog),
            ft.Container(height=20),
        ], spacing=14, scroll=ft.ScrollMode.AUTO))

    def breath_view():
        circle = ft.Container(width=120, height=120, border_radius=200, gradient=GRAD,
                              animate=ft.Animation(1000, "easeInOut"), alignment=ft.alignment.center,
                              shadow=[ft.BoxShadow(blur_radius=40, color=GLOW, offset=ft.Offset(0, 0))])
        label = ft.Text("Prepárate…", size=26, weight=ft.FontWeight.BOLD, color=TXT)
        counter = muted("", 16)
        tid = state["task"]

        async def run():
            await asyncio.sleep(1)
            for cycle in range(4):
                for name, secs, size in (("Inhala", 4, 220), ("Mantén", 7, 220), ("Exhala", 8, 100)):
                    if state["task"] != tid:
                        return
                    label.value = name
                    circle.animate = ft.Animation(secs * 1000 if name != "Mantén" else 200, "easeInOut")
                    circle.width = circle.height = size
                    for t in range(secs, 0, -1):
                        if state["task"] != tid:
                            return
                        counter.value = f"{t}   ·   ciclo {cycle + 1}/4"
                        page.update()
                        await asyncio.sleep(1)
            label.value = "¿Cómo te sientes?"
            counter.value = ""
            page.update()

        page.run_task(run)
        return padded(ft.Column([
            ft.Container(height=14), back_bar("Respirar"), ft.Container(height=30),
            ft.Row([ft.Container(circle, width=240, height=240, alignment=ft.alignment.center)],
                   alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([label], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([counter], alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(height=20),
            gbtn("Lo he superado", ft.Icons.CHECK, on_click=survived_dialog, expand=True),
        ], expand=True))

    def wave_view():
        total = 600
        txt = ft.Text("10:00", size=60, weight=ft.FontWeight.BOLD, color=TXT)
        msg = ft.Text("Observa la sensación sin actuar. Pasará.", text_align=ft.TextAlign.CENTER, color=MUT)
        bar = ft.ProgressBar(value=0, color=B1, bgcolor=CARD_IN, bar_height=10, border_radius=5)
        tid = state["task"]
        tips = {60: "Primer minuto superado. Sigue respirando lento.",
                180: "Las ganas suelen estar cerca del pico. Aguanta.",
                360: "Ya deberían empezar a bajar.",
                540: "Casi está. Lo estás logrando."}

        async def run():
            for left in range(total, -1, -1):
                if state["task"] != tid:
                    return
                m, s = divmod(left, 60)
                txt.value = f"{m:02d}:{s:02d}"
                bar.value = 1 - left / total
                if (total - left) in tips:
                    msg.value = tips[total - left]
                page.update()
                await asyncio.sleep(1)
            msg.value = "¡Ola superada! Tú has ganado."
            page.update()

        page.run_task(run)
        return padded(ft.Column([
            ft.Container(height=14), back_bar("Surfear la ola"), ft.Container(height=20),
            card(ft.Column([ft.Row([txt], alignment=ft.MainAxisAlignment.CENTER), bar, ft.Container(msg, padding=10)],
                           spacing=14)),
            gbtn("Lo he superado", ft.Icons.CHECK, on_click=survived_dialog, expand=True),
        ], spacing=20, expand=True))

    # ---- RUNNER -----------------------------------------------------------
    def runner_view():
        W = int(min((page.width or 380) - 32, 440))
        H = 260
        GROUND = H - 46
        PX = int(W * 0.2)
        GRAV, JUMP_V = 2300.0, 790.0
        PPM = 40.0  # píxeles por metro
        tid = state["task"]
        best = db.best_score("runner")
        g = {"mode": "ready", "y": 0.0, "vy": 0.0, "slide": 0.0, "queued": False, "jbuf": 0.0, "dist": 0.0,
             "obs": [], "spawn_in": W * 0.7, "bg": 0.0, "drag": 0.0, "flash": 0.0, "last100": 0, "meters": 0}
        city = [(random.randint(26, 54), random.randint(40, 110)) for _ in range(14)]
        city_w = sum(w + 6 for w, _ in city)

        def fill(color):
            return ft.Paint(color=color, style=ft.PaintingStyle.FILL)

        def stroke(color, width):
            return ft.Paint(color=color, stroke_width=width, style=ft.PaintingStyle.STROKE,
                            stroke_cap=ft.StrokeCap.ROUND)

        P_SKY, P_GROUND = fill("#22345F"), fill("#101624")
        P_LINE, P_DASH = stroke(B1, 2.5), stroke("#2A3550", 3)
        P_OBS, P_OBS_EDGE = fill(CORAL), stroke("#FFB3BF", 3)
        P_BODY, P_HEAD = stroke("#FFFFFF", 4.5), fill("#FFFFFF")

        canvas = fcv.Canvas(shapes=[], width=W, height=H)
        meters_t = ft.Text("0 m", size=40, weight=ft.FontWeight.BOLD, color=TXT)
        level_t = muted("Nivel 1", 14, B1)
        record_t = muted(f"Récord: {best} m", 14)
        flash_t = ft.Text("", size=18, weight=ft.FontWeight.BOLD, color=WARN)
        ov_title = ft.Text("Toca para empezar", size=22, weight=ft.FontWeight.BOLD, color="white",
                           text_align=ft.TextAlign.CENTER)
        ov_sub = ft.Text("Salta los obstáculos del suelo y deslízate bajo las barreras colgantes.", size=13,
                         color="#DDE8FF", text_align=ft.TextAlign.CENTER)
        overlay = ft.Container(
            content=ft.Column([ov_title, ov_sub], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                              alignment=ft.MainAxisAlignment.CENTER, spacing=8),
            width=W, height=H, alignment=ft.alignment.center, bgcolor="#99101624", padding=24)

        # --- obstáculos -----------------------------------------------------
        def make_obstacle(m, speed):
            pool = [("box", 6)]
            if m >= 14: pool.append(("bar", 5))
            if m >= 40: pool.append(("tall", 4))
            if m >= 75: pool.append(("double", 4))
            if m >= 110: pool.append(("combo", 4))
            if m >= 150: pool.append(("lowbar", 4))
            kind = random.choice([k for k, w in pool for _ in range(w)])
            if kind == "box":
                parts = [(0, 28, 0, 36)]
            elif kind == "tall":
                parts = [(0, 30, 0, 58)]
            elif kind == "double":
                parts = [(0, 26, 0, 36), (54, 26, 0, 36)]
            elif kind == "bar":
                parts = [(0, 76, 36, 999)]
            elif kind == "lowbar":
                parts = [(0, 86, 29, 999)]
            else:  # combo: salto y luego deslizamiento
                parts = [(0, 28, 0, 36), (int(speed * 0.95) + 50, 76, 36, 999)]
            return {"x": W + 40.0, "parts": parts, "w": max(p[0] + p[1] for p in parts)}

        # --- dibujo ---------------------------------------------------------
        def pose_shapes():
            sliding = g["slide"] > 0 and g["y"] <= 0
            base = GROUND - g["y"]
            ph = g["dist"] / 14.0
            px = PX
            L = []
            if sliding:
                hip, sh = (px + 6, base - 10), (px - 16, base - 14)
                L.append(fcv.Circle(px - 24, base - 19, 8, P_HEAD))
                L.append(fcv.Line(sh[0], sh[1], hip[0], hip[1], P_BODY))
                L.append(fcv.Line(hip[0], hip[1], px + 32, base - 4, P_BODY))
                L.append(fcv.Line(hip[0], hip[1], px + 30, base - 11, P_BODY))
                L.append(fcv.Line(sh[0], sh[1], px - 34, base - 6, P_BODY))
            elif g["y"] > 0 or g["vy"] > 0:  # en el aire
                hip, sh = (px, base - 26), (px + 3, base - 46)
                L.append(fcv.Circle(px + 5, base - 54, 8, P_HEAD))
                L.append(fcv.Line(sh[0], sh[1], hip[0], hip[1], P_BODY))
                L.append(fcv.Line(hip[0], hip[1], px + 14, base - 14, P_BODY))
                L.append(fcv.Line(hip[0], hip[1], px - 6, base - 8, P_BODY))
                L.append(fcv.Line(sh[0], sh[1], px + 16, base - 62, P_BODY))
                L.append(fcv.Line(sh[0], sh[1], px - 6, base - 58, P_BODY))
            else:  # corriendo
                hip, sh = (px, base - 26), (px + 3, base - 47)
                L.append(fcv.Circle(px + 5, base - 55, 8, P_HEAD))
                L.append(fcv.Line(sh[0], sh[1], hip[0], hip[1], P_BODY))
                for k in (0.0, math.pi):
                    a = ph + k
                    foot = (px + math.sin(a) * 16, base - max(0.0, math.cos(a)) * 9)
                    L.append(fcv.Line(hip[0], hip[1], foot[0], foot[1], P_BODY))
                    hand = (sh[0] + math.sin(a + math.pi) * 13, sh[1] + 14 - abs(math.cos(a)) * 2)
                    L.append(fcv.Line(sh[0], sh[1], hand[0], hand[1], P_BODY))
            return L

        def build_shapes():
            S = []
            # skyline con parallax
            off = (g["bg"] * 0.2) % city_w
            x = -off
            while x < W:
                for w, h in city:
                    if x + w > 0 and x < W:
                        S.append(fcv.Rect(x, GROUND - h, w, h, paint=P_SKY, border_radius=4))
                    x += w + 6
            # suelo
            S.append(fcv.Rect(0, GROUND, W, H - GROUND, paint=P_GROUND))
            S.append(fcv.Line(0, GROUND, W, GROUND, P_LINE))
            dx = -(g["dist"] % 44)
            while dx < W:
                S.append(fcv.Line(dx, GROUND + 16, dx + 20, GROUND + 16, P_DASH))
                dx += 44
            # obstáculos
            for o in g["obs"]:
                for pdx, w, hlo, hhi in o["parts"]:
                    top = GROUND - min(hhi, GROUND)
                    bottom = GROUND - hlo
                    S.append(fcv.Rect(o["x"] + pdx, top, w, bottom - top, paint=P_OBS, border_radius=6))
                    if hhi >= 999:
                        S.append(fcv.Line(o["x"] + pdx + 3, bottom - 1, o["x"] + pdx + w - 3, bottom - 1, P_OBS_EDGE))
                    else:
                        S.append(fcv.Line(o["x"] + pdx + 4, top + 2, o["x"] + pdx + w - 4, top + 2, P_OBS_EDGE))
            S.extend(pose_shapes())
            return S

        def draw(update=True):
            canvas.shapes = build_shapes()
            if update:
                canvas.update()

        # --- lógica ---------------------------------------------------------
        def crashed():
            sliding = g["slide"] > 0 and g["y"] <= 0
            x0, x1 = (PX - 22, PX + 28) if sliding else (PX - 8, PX + 8)
            hb = g["y"]
            ht = hb + (24 if sliding else 60)
            for o in g["obs"]:
                for pdx, w, hlo, hhi in o["parts"]:
                    ox0 = o["x"] + pdx
                    ox1 = ox0 + w
                    if x0 + 3 < ox1 and x1 - 3 > ox0 and hb + 3 < hhi and ht - 3 > hlo:
                        return True
            return False

        def step(dt):
            m = g["dist"] / PPM
            speed = 270 + min(m * 1.5, 450)  # la velocidad sube más despacio
            g["dist"] += speed * dt
            g["bg"] += speed * dt
            g["jbuf"] = max(0.0, g["jbuf"] - dt)
            if g["y"] > 0 or g["vy"] > 0:
                g["y"] += g["vy"] * dt
                g["vy"] -= GRAV * dt
                if g["y"] <= 0:
                    g["y"], g["vy"] = 0.0, 0.0
                    if g["jbuf"] > 0:
                        g["vy"] = JUMP_V
                        g["jbuf"] = 0.0
                    elif g["queued"]:
                        g["slide"] = 0.6
                        g["queued"] = False
            elif g["slide"] > 0:
                g["slide"] -= dt
            for o in g["obs"]:
                o["x"] -= speed * dt
            g["obs"] = [o for o in g["obs"] if o["x"] + o["w"] > -30]
            g["spawn_in"] -= speed * dt
            if g["spawn_in"] <= 0:
                o = make_obstacle(m, speed)
                g["obs"].append(o)
                react = max(0.68, 0.95 - m * 0.0025)  # huecos más cortos = más obstáculos
                g["spawn_in"] = o["w"] + speed * react + random.uniform(0, speed * 0.30)
            # HUD
            meters = int(g["dist"] / PPM)
            if meters != g["meters"]:
                g["meters"] = meters
                meters_t.value = f"{meters} m"
                level_t.value = f"Nivel {meters // 40 + 1}"
                meters_t.update()
                level_t.update()
                if meters // 100 > g["last100"]:
                    g["last100"] = meters // 100
                    g["flash"] = 1.2
                    flash_t.value = f"¡{meters} m!"
                    flash_t.update()
            if g["flash"] > 0:
                g["flash"] -= dt
                if g["flash"] <= 0:
                    flash_t.value = ""
                    flash_t.update()
            return crashed()

        def finish():
            nonlocal best
            g["mode"] = "over"
            m = int(g["dist"] / PPM)
            if m > 0:
                db.add_score("runner", m)
            if m > best:
                best = m
                ov_title.value = f"¡NUEVO RÉCORD! {m} m"
                ov_sub.value = "Has superado tu marca. Toca para intentarlo otra vez."
            else:
                ov_title.value = f"Has llegado a {m} m"
                ov_sub.value = f"Te faltan {best - m + 1} m para superar tu récord ({best} m). Toca para reintentar."
            record_t.value = f"Récord: {best} m"
            overlay.visible = True
            record_t.update()
            overlay.update()

        async def loop():
            last = time.perf_counter()
            while g["mode"] == "run" and state["task"] == tid:
                now = time.perf_counter()
                dt = min(0.05, now - last)
                last = now
                hit = step(dt)
                draw()
                if hit:
                    finish()
                    return
                await asyncio.sleep(0.014)

        def start():
            g.update(mode="run", y=0.0, vy=0.0, slide=0.0, queued=False, jbuf=0.0, dist=0.0, obs=[],
                     spawn_in=W * 0.7, last100=0, flash=0.0, meters=0, bg=0.0)
            meters_t.value = "0 m"
            level_t.value = "Nivel 1"
            flash_t.value = ""
            overlay.visible = False
            page.update()
            page.run_task(loop)

        def act_jump(e=None):
            if g["mode"] != "run":
                start()
                return
            if g["y"] <= 0 and g["vy"] <= 0:
                g["vy"] = JUMP_V
                g["slide"] = 0.0
            else:
                g["jbuf"] = 0.12

        def act_slide(e=None):
            if g["mode"] != "run":
                start()
                return
            if g["y"] <= 0 and g["vy"] <= 0:
                g["slide"] = 0.6
            else:
                g["vy"] = min(g["vy"], -900.0)
                g["queued"] = True

        def on_key(e: ft.KeyboardEvent):
            if e.key in ("Arrow Up", " ", "W"):
                act_jump()
            elif e.key in ("Arrow Down", "S"):
                act_slide()

        def on_drag_start(e):
            g["drag"] = 0.0

        def on_drag_update(e):
            g["drag"] += getattr(e, "delta_y", 0) or 0
            if g["drag"] > 25:
                g["drag"] = -9999
                act_slide()
            elif g["drag"] < -25 and g["drag"] > -9000:
                g["drag"] = -9999
                act_jump()

        page.on_keyboard_event = on_key
        draw(update=False)

        arena = ft.Container(
            content=ft.Stack([canvas, overlay], width=W, height=H),
            width=W, height=H, border_radius=26, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            gradient=ft.LinearGradient(begin=ft.alignment.top_center, end=ft.alignment.bottom_center,
                                       colors=["#141B2B", "#1E3B7A"]),
            shadow=neu(22, 8))
        gesture = ft.GestureDetector(content=arena, on_tap=act_jump, on_vertical_drag_start=on_drag_start,
                                     on_vertical_drag_update=on_drag_update)

        def ctrl(icon, label, handler, danger=False):
            return ft.GestureDetector(
                on_tap_down=handler, expand=True,
                content=ft.Container(
                    content=ft.Row([ft.Icon(icon, color="white", size=26),
                                    ft.Text(label, color="white", weight=ft.FontWeight.BOLD, size=16)],
                                   alignment=ft.MainAxisAlignment.CENTER, spacing=8),
                    height=64, border_radius=20, alignment=ft.alignment.center,
                    gradient=GRAD_DANGER if danger else GRAD,
                    shadow=[ft.BoxShadow(blur_radius=22, color="#55E5484D" if danger else GLOW,
                                         offset=ft.Offset(0, 8))]))

        return padded(ft.Column([
            ft.Container(height=14),
            back_bar("Runner"),
            ft.Row([ft.Column([meters_t, level_t], spacing=0),
                    ft.Column([record_t, flash_t], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END)],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Row([gesture], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([ctrl(ft.Icons.KEYBOARD_ARROW_UP, "SALTAR", act_jump),
                    ctrl(ft.Icons.KEYBOARD_ARROW_DOWN, "DESLIZAR", act_slide, danger=True)], spacing=14),
            muted("Toca o desliza hacia arriba para saltar · desliza hacia abajo para agacharte. "
                  "En PC: ↑ ↓ o espacio.", 12),
            ft.TextButton("Ya me siento mejor", on_click=survived_dialog),
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
            body = {"sos": sos_view, "runner": runner_view, "breath": breath_view, "wave": wave_view}[scr]()
            page.add(ft.SafeArea(ft.Container(body, expand=True), expand=True))
        page.update()

    # ---- reloj en vivo ----------------------------------------------------
    async def ticker():
        while True:
            await asyncio.sleep(1)
            try:
                if state["screen"] == "main" and state["tab"] == 0 and "days" in refs and not state["locked"]:
                    secs = (datetime.now() - refs["start"]).total_seconds()
                    d, h, m, s = split_duration(secs)
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
    if os.getenv("PORT"):  # en Render: modo web
        ft.app(target=main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0", port=int(os.getenv("PORT")))
    else:  # en tu PC: ventana normal
        ft.app(target=main)
