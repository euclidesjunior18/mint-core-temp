#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mint Core Temp - Monitor de Temperatura da CPU para Linux Mint
Inspirado no Core Temp, integrado à bandeja do sistema (perto do relógio).
"""

import sys
import os

# Força renderização de imagem estável no GDK para evitar bug de tela preta no XFCE / Mesa (Radeon)
os.environ.setdefault("GDK_RENDERING", "image")
import time
import json
import math
import signal
import tempfile
import argparse
from collections import deque

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
try:
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except ValueError:
    try:
        gi.require_version('AppIndicator3', '0.1')
        from gi.repository import AppIndicator3 as AppIndicator
    except ValueError:
        AppIndicator = None

try:
    gi.require_version('Notify', '0.7')
    from gi.repository import Notify
    HAS_NOTIFY = True
except Exception:
    HAS_NOTIFY = False

from gi.repository import Gtk, Gdk, GdkPixbuf, GLib
import cairo
import psutil

# Diretórios base
APP_ID = "mint-core-temp"
APP_NAME = "Mint Core Temp"
CONFIG_DIR = os.path.expanduser("~/.config/mint-core-temp")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, f"{APP_ID}.desktop")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(SCRIPT_DIR, "icon.png")

# Configurações padrão
DEFAULT_CONFIG = {
    "sensor_id": "auto",
    "offset_temp": 0.0,
    "update_interval": 1.5,
    "tray_style": "both",  # 'both', 'icon_only', 'text_only'
    "alert_enabled": True,
    "alert_threshold": 80.0,
    "close_to_tray": True,
    "start_minimized": False,
    "autostart": False
}


def load_config():
    """Carrega as configurações salvas ou retorna os padrões."""
    config = DEFAULT_CONFIG.copy()
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                config.update(saved)
        except Exception as e:
            print(f"Aviso ao carregar config: {e}")
    return config


def save_config(config):
    """Salva as configurações em arquivo JSON."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao salvar config: {e}")


def set_autostart(enable):
    """Ativa ou desativa a inicialização automática com o sistema."""
    os.makedirs(AUTOSTART_DIR, exist_ok=True)
    if enable:
        desktop_content = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Comment=Monitor de Temperatura da CPU na Bandeja do Sistema
Exec=python3 "{os.path.abspath(__file__)}" --minimized
Icon={ICON_PATH}
Terminal=false
Categories=System;Monitor;Utility;
StartupNotify=false
X-GNOME-Autostart-enabled=true
"""
        try:
            with open(AUTOSTART_FILE, "w", encoding="utf-8") as f:
                f.write(desktop_content)
        except Exception as e:
            print(f"Erro ao configurar autostart: {e}")
    else:
        if os.path.isfile(AUTOSTART_FILE):
            try:
                os.remove(AUTOSTART_FILE)
            except Exception as e:
                print(f"Erro ao remover autostart: {e}")


def get_cpu_model():
    """Obtém o nome amigável do modelo de CPU."""
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if "model name" in line:
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return "Processador Desconhecido"


def get_available_sensors():
    """Descobre e lista todos os sensores de temperatura disponíveis no sistema."""
    sensors = {}
    try:
        temps = psutil.sensors_temperatures()
        for chip_name, entries in temps.items():
            for idx, entry in enumerate(entries):
                label = entry.label.strip() if entry.label else f"temp{idx + 1}"
                sensor_id = f"{chip_name}::{label}"
                desc = f"{chip_name} ({label})"
                sensors[sensor_id] = {
                    "chip": chip_name,
                    "label": label,
                    "desc": desc,
                    "current": entry.current,
                    "high": entry.high,
                    "critical": entry.critical
                }
    except Exception as e:
        print(f"Erro ao listar sensores psutil: {e}")

    # Fallback para /sys/class/thermal se nada for detectado
    if not sensors:
        thermal_dir = "/sys/class/thermal"
        if os.path.isdir(thermal_dir):
            for zone in os.listdir(thermal_dir):
                if zone.startswith("thermal_zone"):
                    try:
                        type_file = os.path.join(thermal_dir, zone, "type")
                        temp_file = os.path.join(thermal_dir, zone, "temp")
                        if os.path.isfile(type_file) and os.path.isfile(temp_file):
                            with open(type_file, "r") as tf:
                                ztype = tf.read().strip()
                            with open(temp_file, "r") as zf:
                                raw_temp = float(zf.read().strip()) / 1000.0
                            sid = f"thermal::{zone}"
                            sensors[sid] = {
                                "chip": "thermal",
                                "label": zone,
                                "desc": f"{ztype} ({zone})",
                                "current": raw_temp,
                                "high": 75.0,
                                "critical": 90.0
                            }
                    except Exception:
                        pass
    return sensors


def find_default_cpu_sensor(sensors):
    """Encontra o sensor de CPU mais apropriado automaticamente."""
    if not sensors:
        return None

    # Ordem de prioridade para CPU
    priorities = [
        "coretemp", "k10temp", "zenpower", "cpu_thermal",
        "tctl", "tdie", "package id 0", "core 0"
    ]

    for p in priorities:
        for sid, info in sensors.items():
            if p in sid.lower() or p in info["desc"].lower():
                return sid

    for sid in sensors.keys():
        if "cpu" in sid.lower():
            return sid

    # Fallback para o primeiro
    return next(iter(sensors.keys()))


def get_temperature_color(temp):
    """Retorna cor hexadecimal e componentes RGB de acordo com a temperatura."""
    if temp < 55.0:
        # Verde normal
        return "#2ecc71", (0.18, 0.80, 0.44)
    elif temp < 72.0:
        # Laranja / Ambar moderado
        return "#f39c12", (0.95, 0.61, 0.07)
    else:
        # Vermelho crítico
        return "#e74c3c", (0.91, 0.30, 0.24)


class DynamicIconGenerator:
    """Gera dinamicamente ícones para a bandeja com o número da temperatura em alta resolução."""

    def __init__(self):
        self.temp_dir = tempfile.gettempdir()
        self.file_a = os.path.join(self.temp_dir, f"{APP_ID}_icon_a.png")
        self.file_b = os.path.join(self.temp_dir, f"{APP_ID}_icon_b.png")
        self.current_file = self.file_a

    def generate(self, temp):
        """Gera imagem PNG 48x48 com o valor numérico e borda colorida."""
        color_hex, (r, g, b) = get_temperature_color(temp)
        size = 48
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        ctx = cairo.Context(surface)

        # Fundo arredondado escuro translúcido
        rad = 8
        ctx.arc(rad, rad, rad, math.pi, 1.5 * math.pi)
        ctx.arc(size - rad, rad, rad, 1.5 * math.pi, 2 * math.pi)
        ctx.arc(size - rad, size - rad, rad, 0, 0.5 * math.pi)
        ctx.arc(rad, size - rad, rad, 0.5 * math.pi, math.pi)
        ctx.close_path()
        ctx.set_source_rgba(0.08, 0.10, 0.14, 0.92)
        ctx.fill()

        # Borda colorida conforme o nível térmico
        ctx.arc(rad, rad, rad, math.pi, 1.5 * math.pi)
        ctx.arc(size - rad, rad, rad, 1.5 * math.pi, 2 * math.pi)
        ctx.arc(size - rad, size - rad, rad, 0, 0.5 * math.pi)
        ctx.arc(rad, size - rad, rad, 0.5 * math.pi, math.pi)
        ctx.close_path()
        ctx.set_source_rgb(r, g, b)
        ctx.set_line_width(3.2)
        ctx.stroke()

        # Texto com a temperatura
        val_str = str(int(round(temp)))
        ctx.select_font_face("DejaVu Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(24 if len(val_str) <= 2 else 18)
        ctx.set_source_rgb(1.0, 1.0, 1.0)
        extents = ctx.text_extents(val_str)

        # Centralizar número
        x = (size - extents.width) / 2 - extents.x_bearing
        y = (size - extents.height) / 2 - extents.y_bearing - 2
        ctx.move_to(x, y)
        ctx.show_text(val_str)

        # Barra indicadora colorida na base
        ctx.set_source_rgb(r, g, b)
        ctx.rectangle(8, size - 7, size - 16, 2.5)
        ctx.fill()

        # Alterna arquivos para forçar atualização do cache do indicador do desktop
        target_file = self.file_b if self.current_file == self.file_a else self.file_a
        surface.write_to_png(target_file)
        self.current_file = target_file
        return target_file


class TempGraphWidget(Gtk.DrawingArea):
    """Widget de gráfico histórico em tempo real."""

    def __init__(self, history_points=60):
        super().__init__()
        self.history = deque(maxlen=history_points)
        self.set_size_request(320, 85)
        self.connect("draw", self.on_draw)

    def add_point(self, temp):
        self.history.append(temp)
        self.queue_draw()

    def clear(self):
        self.history.clear()
        self.queue_draw()

    def on_draw(self, widget, ctx):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()

        # Fundo do gráfico sólido
        ctx.set_source_rgb(0.13, 0.15, 0.19)
        ctx.paint()

        # Linhas de grade sutis
        ctx.set_source_rgba(1.0, 1.0, 1.0, 0.08)
        ctx.set_line_width(1.0)
        for y_pct in [0.25, 0.50, 0.75]:
            y = height * y_pct
            ctx.move_to(0, y)
            ctx.line_to(width, y)
            ctx.stroke()

        if len(self.history) < 2:
            ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            ctx.set_font_size(11)
            ctx.set_source_rgba(1.0, 1.0, 1.0, 0.4)
            ctx.move_to(width / 2 - 45, height / 2 + 4)
            ctx.show_text("Aguardando dados...")
            return False

        min_scale = 20.0
        max_scale = 95.0
        hist_list = list(self.history)
        n = len(hist_list)
        step_x = width / max(self.history.maxlen - 1, 1)
        start_x = width - ((n - 1) * step_x)

        def temp_to_y(t):
            clamped = max(min_scale, min(max_scale, t))
            ratio = (clamped - min_scale) / (max_scale - min_scale)
            return height - (ratio * (height - 12)) - 6

        # Área preenchida sob a curva
        points = []
        for i, val in enumerate(hist_list):
            px = start_x + (i * step_x)
            py = temp_to_y(val)
            points.append((px, py))

        # Gradiente preenchido
        last_temp = hist_list[-1]
        _, (r, g, b) = get_temperature_color(last_temp)

        ctx.move_to(points[0][0], height)
        for px, py in points:
            ctx.line_to(px, py)
        ctx.line_to(points[-1][0], height)
        ctx.close_path()

        grad = cairo.LinearGradient(0, 0, 0, height)
        grad.add_color_stop_rgba(0.0, r, g, b, 0.35)
        grad.add_color_stop_rgba(1.0, r, g, b, 0.02)
        ctx.set_source(grad)
        ctx.fill()

        # Linha da curva
        ctx.move_to(points[0][0], points[0][1])
        for px, py in points[1:]:
            ctx.line_to(px, py)
        ctx.set_source_rgb(r, g, b)
        ctx.set_line_width(2.2)
        ctx.stroke()

        # Ponto atual pulsante no final
        last_x, last_y = points[-1]
        ctx.arc(last_x, last_y, 4, 0, 2 * math.pi)
        ctx.set_source_rgb(1.0, 1.0, 1.0)
        ctx.fill()
        ctx.arc(last_x, last_y, 4, 0, 2 * math.pi)
        ctx.set_source_rgb(r, g, b)
        ctx.set_line_width(1.5)
        ctx.stroke()

        # Linha de alerta 80°C
        alert_y = temp_to_y(80.0)
        ctx.set_source_rgba(0.9, 0.2, 0.2, 0.4)
        ctx.set_dash([4.0, 4.0])
        ctx.move_to(0, alert_y)
        ctx.line_to(width, alert_y)
        ctx.stroke()
        ctx.set_dash([])

        return False


class CoreTempApp:
    """Aplicação Principal do Mint Core Temp."""

    def __init__(self, start_minimized=False):
        self.config = load_config()
        self.start_minimized = start_minimized or self.config.get("start_minimized", False)
        self.icon_generator = DynamicIconGenerator()

        # Estatísticas de temperatura
        self.min_temp = None
        self.max_temp = None
        self.temp_samples = []
        self.last_alert_time = 0

        # Inicializa notificações do sistema se disponível
        if HAS_NOTIFY:
            try:
                Notify.init(APP_ID)
            except Exception:
                pass

        # Cria interface gráfica e indicador de bandeja
        self._setup_css()
        self._build_window()
        self._build_tray_indicator()

        # Inicia atualização periódica
        self.timer_id = GLib.timeout_add(
            int(self.config["update_interval"] * 1000),
            self.on_timer_tick
        )

        # Primeira medição imediata
        self.on_timer_tick()

        if self.start_minimized:
            self.window.hide()
        else:
            self.window.show_all()

    def _setup_css(self):
        """Aplica estilo moderno em CSS GTK para a janela."""
        css_data = """
        window, dialog {
            background-color: #23272e;
            color: #abb2bf;
        }
        .top-bar {
            background-color: #1e2227;
            border-bottom: 1px solid #181a1f;
            padding: 8px 12px;
        }
        .card-box {
            background-color: #282c34;
            border: 1px solid #3b4048;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 6px;
        }
        .temp-display {
            font-size: 40px;
            font-weight: 900;
            font-family: 'Monospace', 'DejaVu Sans', sans-serif;
        }
        .temp-badge {
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: bold;
            color: #ffffff;
        }
        .badge-cool {
            background-color: #2ecc71;
        }
        .badge-warm {
            background-color: #f39c12;
        }
        .badge-hot {
            background-color: #e74c3c;
        }
        .stat-label {
            font-size: 11px;
            opacity: 0.7;
        }
        .stat-val {
            font-size: 16px;
            font-weight: bold;
        }
        .cpu-title {
            font-size: 14px;
            font-weight: bold;
        }
        .core-bar progress, .core-bar trough {
            min-height: 8px;
            border-radius: 4px;
        }
        """
        css_provider = Gtk.CssProvider()
        try:
            css_provider.load_from_data(css_data.encode("utf-8"))
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        except Exception as e:
            print(f"Aviso CSS: {e}")

    def _build_window(self):
        """Constrói a janela principal do monitor."""
        self.window = Gtk.Window(title=APP_NAME)
        self.window.set_default_size(440, 620)
        self.window.set_position(Gtk.WindowPosition.CENTER)

        if os.path.isfile(ICON_PATH):
            self.window.set_icon_from_file(ICON_PATH)

        # Conectar eventos de fechamento, minimização e mapeamento
        self.window.connect("delete-event", self.on_window_delete)
        self.window.connect("window-state-event", self.on_window_state_event)
        self.window.connect("map-event", self.on_window_map)

        self.main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Barra superior com título e botão de minimizar para a bandeja
        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top_bar.get_style_context().add_class("top-bar")

        lbl_top = Gtk.Label(label=f"<b>{APP_NAME}</b>  -  Monitor de Processador")
        lbl_top.set_use_markup(True)
        lbl_top.set_halign(Gtk.Align.START)
        top_bar.pack_start(lbl_top, True, True, 0)

        btn_tray = Gtk.Button(label="Ocultar na Bandeja")
        btn_tray.set_tooltip_text("Minimizar para a Bandeja do Sistema")
        btn_tray.connect("clicked", lambda b: self.window.hide())
        top_bar.pack_end(btn_tray, False, False, 0)

        self.main_vbox.pack_start(top_bar, False, False, 0)

        # Notebook com abas
        notebook = Gtk.Notebook()
        notebook.set_border_width(8)

        # Aba 1: Monitor Principal
        tab_monitor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        tab_monitor.set_border_width(8)

        # 1. Informações da CPU
        cpu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        cpu_box.get_style_context().add_class("card-box")

        self.lbl_cpu_model = Gtk.Label(label=get_cpu_model())
        self.lbl_cpu_model.set_line_wrap(True)
        self.lbl_cpu_model.set_halign(Gtk.Align.START)
        self.lbl_cpu_model.get_style_context().add_class("cpu-title")
        cpu_box.pack_start(self.lbl_cpu_model, False, False, 0)

        cores_phys = psutil.cpu_count(logical=False) or 1
        cores_log = psutil.cpu_count(logical=True) or 1
        self.lbl_cpu_details = Gtk.Label(
            label=f"Núcleos: {cores_phys} físicos / {cores_log} lógicos  |  Frequência: -- MHz"
        )
        self.lbl_cpu_details.set_halign(Gtk.Align.START)
        self.lbl_cpu_details.get_style_context().add_class("stat-label")
        cpu_box.pack_start(self.lbl_cpu_details, False, False, 0)
        tab_monitor.pack_start(cpu_box, False, False, 0)

        # 2. Cartão de Temperatura Principal (Destaque)
        temp_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        temp_card.get_style_context().add_class("card-box")

        row_main_temp = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row_main_temp.set_halign(Gtk.Align.CENTER)

        self.lbl_temp_now = Gtk.Label(label="-- °C")
        self.lbl_temp_now.get_style_context().add_class("temp-display")
        row_main_temp.pack_start(self.lbl_temp_now, False, False, 0)

        self.lbl_status_badge = Gtk.Label(label="NORMAL")
        self.lbl_status_badge.get_style_context().add_class("temp-badge")
        self.lbl_status_badge.get_style_context().add_class("badge-cool")
        self.lbl_status_badge.set_valign(Gtk.Align.CENTER)
        row_main_temp.pack_start(self.lbl_status_badge, False, False, 0)
        temp_card.pack_start(row_main_temp, False, False, 0)

        # Linha com Min, Max, Média e Reset
        row_stats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row_stats.set_halign(Gtk.Align.CENTER)

        def make_stat_box(title, val_lbl):
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            t = Gtk.Label(label=title)
            t.get_style_context().add_class("stat-label")
            b.pack_start(t, False, False, 0)
            val_lbl.get_style_context().add_class("stat-val")
            b.pack_start(val_lbl, False, False, 0)
            return b

        self.lbl_stat_min = Gtk.Label(label="-- °C")
        self.lbl_stat_max = Gtk.Label(label="-- °C")
        self.lbl_stat_avg = Gtk.Label(label="-- °C")

        row_stats.pack_start(make_stat_box("MÍNIMA", self.lbl_stat_min), True, True, 0)
        row_stats.pack_start(make_stat_box("MÉDIA", self.lbl_stat_avg), True, True, 0)
        row_stats.pack_start(make_stat_box("MÁXIMA", self.lbl_stat_max), True, True, 0)

        btn_reset = Gtk.Button(label="Resetar")
        btn_reset.set_tooltip_text("Zerar estatísticas de mínima e máxima")
        btn_reset.connect("clicked", self.on_reset_stats)
        btn_reset.set_valign(Gtk.Align.CENTER)
        row_stats.pack_start(btn_reset, False, False, 0)

        temp_card.pack_start(row_stats, False, False, 0)

        # Mini Gráfico de Temperatura
        self.graph = TempGraphWidget(history_points=60)
        temp_card.pack_start(self.graph, False, False, 4)

        tab_monitor.pack_start(temp_card, False, False, 0)

        # 3. Uso da CPU e Cores
        cores_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        cores_box.get_style_context().add_class("card-box")

        header_usage = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl_usage_title = Gtk.Label(label="Carga da CPU")
        lbl_usage_title.get_style_context().add_class("cpu-title")
        header_usage.pack_start(lbl_usage_title, False, False, 0)
        self.lbl_overall_usage = Gtk.Label(label="0%")
        self.lbl_overall_usage.set_halign(Gtk.Align.END)
        header_usage.pack_end(self.lbl_overall_usage, False, False, 0)
        cores_box.pack_start(header_usage, False, False, 0)

        self.overall_bar = Gtk.ProgressBar()
        self.overall_bar.get_style_context().add_class("core-bar")
        cores_box.pack_start(self.overall_bar, False, False, 0)

        # Cores individuais em scroll
        scroll_cores = Gtk.ScrolledWindow()
        scroll_cores.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll_cores.set_min_content_height(80)
        scroll_cores.set_max_content_height(140)

        self.box_individual_cores = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.core_bars = []
        self.core_labels = []

        for c_idx in range(cores_log):
            c_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            c_lbl_name = Gtk.Label(label=f"Core #{c_idx}")
            c_lbl_name.set_size_request(60, -1)
            c_lbl_name.set_halign(Gtk.Align.START)
            c_lbl_name.get_style_context().add_class("stat-label")
            c_row.pack_start(c_lbl_name, False, False, 0)

            c_bar = Gtk.ProgressBar()
            c_bar.get_style_context().add_class("core-bar")
            c_bar.set_hexpand(True)
            c_row.pack_start(c_bar, True, True, 0)

            c_lbl_pct = Gtk.Label(label="0%")
            c_lbl_pct.set_size_request(45, -1)
            c_lbl_pct.set_halign(Gtk.Align.END)
            c_lbl_pct.get_style_context().add_class("stat-label")
            c_row.pack_start(c_lbl_pct, False, False, 0)

            self.core_bars.append(c_bar)
            self.core_labels.append(c_lbl_pct)
            self.box_individual_cores.pack_start(c_row, False, False, 0)

        scroll_cores.add(self.box_individual_cores)
        cores_box.pack_start(scroll_cores, True, True, 0)

        tab_monitor.pack_start(cores_box, True, True, 0)

        # Aba 2: Configurações
        tab_settings = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        tab_settings.set_border_width(12)

        # Sensor
        s_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        s_box.get_style_context().add_class("card-box")
        lbl_s_title = Gtk.Label(label="Sensor de Temperatura")
        lbl_s_title.set_halign(Gtk.Align.START)
        lbl_s_title.get_style_context().add_class("cpu-title")
        s_box.pack_start(lbl_s_title, False, False, 0)

        self.combo_sensor = Gtk.ComboBoxText()
        self.combo_sensor.append("auto", "Detecção Automática (Processador)")
        self.available_sensors = get_available_sensors()
        for sid, sinfo in self.available_sensors.items():
            self.combo_sensor.append(sid, f"{sinfo['desc']} [{sid}]")

        current_sid = self.config.get("sensor_id", "auto")
        if current_sid in self.available_sensors or current_sid == "auto":
            self.combo_sensor.set_active_id(current_sid)
        else:
            self.combo_sensor.set_active_id("auto")

        self.combo_sensor.connect("changed", self.on_sensor_changed)
        s_box.pack_start(self.combo_sensor, False, False, 4)

        # Calibração / Offset
        row_offset = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl_offset = Gtk.Label(label="Ajuste de Calibração (Offset °C):")
        lbl_offset.set_halign(Gtk.Align.START)
        row_offset.pack_start(lbl_offset, True, True, 0)

        adj_offset = Gtk.Adjustment(
            value=self.config.get("offset_temp", 0.0),
            lower=-30.0,
            upper=30.0,
            step_increment=1.0,
            page_increment=5.0
        )
        self.spin_offset = Gtk.SpinButton(adjustment=adj_offset, digits=1)
        self.spin_offset.connect("value-changed", self.on_offset_changed)
        row_offset.pack_start(self.spin_offset, False, False, 0)
        s_box.pack_start(row_offset, False, False, 2)

        tab_settings.pack_start(s_box, False, False, 0)

        # Bandeja e Atualização
        b_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        b_box.get_style_context().add_class("card-box")

        lbl_b_title = Gtk.Label(label="Bandeja do Sistema e Notificações")
        lbl_b_title.set_halign(Gtk.Align.START)
        lbl_b_title.get_style_context().add_class("cpu-title")
        b_box.pack_start(lbl_b_title, False, False, 0)

        # Intervalo
        row_interval = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl_interval = Gtk.Label(label="Intervalo de Atualização:")
        lbl_interval.set_halign(Gtk.Align.START)
        row_interval.pack_start(lbl_interval, True, True, 0)

        self.combo_interval = Gtk.ComboBoxText()
        self.combo_interval.append("1.0", "1 segundo")
        self.combo_interval.append("1.5", "1,5 segundos (recomendado)")
        self.combo_interval.append("2.0", "2 segundos")
        self.combo_interval.append("3.0", "3 segundos")
        self.combo_interval.append("5.0", "5 segundos")
        self.combo_interval.set_active_id(str(self.config.get("update_interval", 1.5)))
        self.combo_interval.connect("changed", self.on_interval_changed)
        row_interval.pack_start(self.combo_interval, False, False, 0)
        b_box.pack_start(row_interval, False, False, 0)

        # Exibição na bandeja
        row_style = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl_style = Gtk.Label(label="Estilo na Bandeja:")
        lbl_style.set_halign(Gtk.Align.START)
        row_style.pack_start(lbl_style, True, True, 0)

        self.combo_style = Gtk.ComboBoxText()
        self.combo_style.append("both", "Ícone com Número + Texto (ex: 45°C)")
        self.combo_style.append("icon_only", "Apenas Ícone com Número")
        self.combo_style.append("text_only", "Apenas Texto")
        self.combo_style.set_active_id(self.config.get("tray_style", "both"))
        self.combo_style.connect("changed", self.on_style_changed)
        row_style.pack_start(self.combo_style, False, False, 0)
        b_box.pack_start(row_style, False, False, 0)

        # Alerta de temperatura
        row_alert = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.chk_alert = Gtk.CheckButton(label="Notificar se a temperatura ultrapassar:")
        self.chk_alert.set_active(self.config.get("alert_enabled", True))
        self.chk_alert.connect("toggled", self.on_alert_toggled)
        row_alert.pack_start(self.chk_alert, True, True, 0)

        adj_alert = Gtk.Adjustment(
            value=self.config.get("alert_threshold", 80.0),
            lower=50.0,
            upper=110.0,
            step_increment=1.0,
            page_increment=5.0
        )
        self.spin_alert = Gtk.SpinButton(adjustment=adj_alert, digits=0)
        self.spin_alert.connect("value-changed", self.on_alert_threshold_changed)
        row_alert.pack_start(self.spin_alert, False, False, 0)
        b_box.pack_start(row_alert, False, False, 0)

        tab_settings.pack_start(b_box, False, False, 0)

        # Comportamento
        c_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c_box.get_style_context().add_class("card-box")

        lbl_c_title = Gtk.Label(label="Comportamento da Aplicação")
        lbl_c_title.set_halign(Gtk.Align.START)
        lbl_c_title.get_style_context().add_class("cpu-title")
        c_box.pack_start(lbl_c_title, False, False, 0)

        self.chk_close_tray = Gtk.CheckButton(label="Minimizar para a bandeja ao clicar no fechar (X)")
        self.chk_close_tray.set_active(self.config.get("close_to_tray", True))
        self.chk_close_tray.connect("toggled", self.on_close_tray_toggled)
        c_box.pack_start(self.chk_close_tray, False, False, 0)

        self.chk_start_min = Gtk.CheckButton(label="Iniciar minimizado na bandeja")
        self.chk_start_min.set_active(self.config.get("start_minimized", False))
        self.chk_start_min.connect("toggled", self.on_start_min_toggled)
        c_box.pack_start(self.chk_start_min, False, False, 0)

        self.chk_autostart = Gtk.CheckButton(label="Iniciar automaticamente com o Linux Mint")
        is_auto = os.path.isfile(AUTOSTART_FILE) or self.config.get("autostart", False)
        self.chk_autostart.set_active(is_auto)
        self.chk_autostart.connect("toggled", self.on_autostart_toggled)
        c_box.pack_start(self.chk_autostart, False, False, 0)

        tab_settings.pack_start(c_box, False, False, 0)

        # Adicionar abas
        notebook.append_page(tab_monitor, Gtk.Label(label="Monitor"))
        notebook.append_page(tab_settings, Gtk.Label(label="Configurações"))

        self.main_vbox.pack_start(notebook, True, True, 0)
        self.window.add(self.main_vbox)

    def _build_tray_indicator(self):
        """Inicializa o AyatanaAppIndicator no painel do Linux Mint."""
        if AppIndicator is None:
            print("Aviso: AppIndicator não está disponível.")
            self.indicator = None
            return

        init_icon = ICON_PATH if os.path.isfile(ICON_PATH) else "temperature-symbolic"
        self.indicator = AppIndicator.Indicator.new(
            APP_ID,
            init_icon,
            AppIndicator.IndicatorCategory.HARDWARE
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_label("-- °C", "999°C")
        self.indicator.set_title("CPU: -- °C  |  Uso: --%")

        # Menu da bandeja
        menu = Gtk.Menu()

        self.menu_item_open = Gtk.MenuItem(label="Abrir Mint Core Temp")
        self.menu_item_open.connect("activate", lambda w: self.show_window())
        menu.append(self.menu_item_open)

        self.menu_item_hide = Gtk.MenuItem(label="Minimizar para a Bandeja")
        self.menu_item_hide.connect("activate", lambda w: self.window.hide())
        menu.append(self.menu_item_hide)

        menu.append(Gtk.SeparatorMenuItem())

        self.menu_item_sensor_info = Gtk.MenuItem(label="Sensor: --")
        self.menu_item_sensor_info.set_sensitive(False)
        menu.append(self.menu_item_sensor_info)

        self.menu_item_load_info = Gtk.MenuItem(label="Uso da CPU: --")
        self.menu_item_load_info.set_sensitive(False)
        menu.append(self.menu_item_load_info)

        menu.append(Gtk.SeparatorMenuItem())

        self.menu_autostart = Gtk.CheckMenuItem(label="Iniciar com o sistema")
        self.menu_autostart.set_active(self.chk_autostart.get_active())
        self.menu_autostart.connect("toggled", self.on_menu_autostart_toggled)
        menu.append(self.menu_autostart)

        menu.append(Gtk.SeparatorMenuItem())

        item_quit = Gtk.MenuItem(label="Sair")
        item_quit.connect("activate", lambda w: self.quit_app())
        menu.append(item_quit)

        menu.show_all()
        self.indicator.set_menu(menu)

    def show_window(self):
        """Exibe e foca a janela principal garantindo restauração correta."""
        self.window.deiconify()
        self.window.show_all()
        self.window.present()
        self.window.queue_draw()

    def on_window_state_event(self, widget, event):
        """Quando o usuário clica no botão de minimizar da barra de título."""
        if event.changed_mask & Gdk.WindowState.ICONIFIED:
            if event.new_window_state & Gdk.WindowState.ICONIFIED:
                if self.config.get("close_to_tray", True):
                    GLib.idle_add(self.window.hide)
        return False

    def on_window_map(self, widget, event):
        """Garante redesenho imediato de todas as áreas ao reabrir."""
        self.window.queue_draw()
        return False

    def on_window_delete(self, widget, event):
        """Controla o evento do botão Fechar (X)."""
        if self.config.get("close_to_tray", True):
            self.window.hide()
            return True
        else:
            self.quit_app()
            return False

    def on_reset_stats(self, btn):
        """Reseta contadores de mínima, máxima e média."""
        self.min_temp = None
        self.max_temp = None
        self.temp_samples.clear()
        self.graph.clear()
        self.on_timer_tick()

    def on_sensor_changed(self, combo):
        sid = combo.get_active_id()
        if sid:
            self.config["sensor_id"] = sid
            save_config(self.config)
            self.on_reset_stats(None)

    def on_offset_changed(self, spin):
        self.config["offset_temp"] = spin.get_value()
        save_config(self.config)
        self.on_timer_tick()

    def on_interval_changed(self, combo):
        val = float(combo.get_active_id() or 1.5)
        self.config["update_interval"] = val
        save_config(self.config)
        if self.timer_id:
            GLib.source_remove(self.timer_id)
        self.timer_id = GLib.timeout_add(int(val * 1000), self.on_timer_tick)

    def on_style_changed(self, combo):
        self.config["tray_style"] = combo.get_active_id() or "both"
        save_config(self.config)
        self.on_timer_tick()

    def on_alert_toggled(self, chk):
        self.config["alert_enabled"] = chk.get_active()
        save_config(self.config)

    def on_alert_threshold_changed(self, spin):
        self.config["alert_threshold"] = spin.get_value()
        save_config(self.config)

    def on_close_tray_toggled(self, chk):
        self.config["close_to_tray"] = chk.get_active()
        save_config(self.config)

    def on_start_min_toggled(self, chk):
        self.config["start_minimized"] = chk.get_active()
        save_config(self.config)

    def on_autostart_toggled(self, chk):
        state = chk.get_active()
        self.config["autostart"] = state
        save_config(self.config)
        set_autostart(state)
        if hasattr(self, "menu_autostart"):
            self.menu_autostart.handler_block_by_func(self.on_menu_autostart_toggled)
            self.menu_autostart.set_active(state)
            self.menu_autostart.handler_unblock_by_func(self.on_menu_autostart_toggled)

    def on_menu_autostart_toggled(self, menu_item):
        state = menu_item.get_active()
        self.chk_autostart.set_active(state)

    def read_current_temperature(self):
        """Lê a temperatura atual do sensor selecionado."""
        sensors = get_available_sensors()
        self.available_sensors = sensors

        sid = self.config.get("sensor_id", "auto")
        if sid == "auto" or sid not in sensors:
            actual_sid = find_default_cpu_sensor(sensors)
        else:
            actual_sid = sid

        if not actual_sid or actual_sid not in sensors:
            return None, "Sem sensor"

        raw_temp = sensors[actual_sid]["current"]
        offset = self.config.get("offset_temp", 0.0)
        final_temp = raw_temp + offset
        desc = sensors[actual_sid]["desc"]
        return final_temp, desc

    def trigger_alert(self, temp, limit):
        """Envia notificação nativa quando a temperatura excede o limite."""
        now = time.time()
        # Evita flood de notificações (mínimo 60s entre avisos)
        if now - self.last_alert_time < 60:
            return
        self.last_alert_time = now

        if HAS_NOTIFY:
            try:
                notif = Notify.Notification.new(
                    f"⚠️ Alerta Térmico: {temp:.1f}°C",
                    f"A temperatura da CPU excedeu o limite configurado de {limit:.0f}°C!",
                    "dialog-warning"
                )
                notif.set_urgency(Notify.Urgency.CRITICAL)
                notif.show()
            except Exception as e:
                print(f"Erro ao enviar notificação: {e}")

    def on_timer_tick(self):
        """Executado periodicamente para atualizar todas as medições."""
        temp, sensor_desc = self.read_current_temperature()
        if temp is None:
            return True

        # Atualiza estatísticas
        if self.min_temp is None or temp < self.min_temp:
            self.min_temp = temp
        if self.max_temp is None or temp > self.max_temp:
            self.max_temp = temp

        self.temp_samples.append(temp)
        if len(self.temp_samples) > 200:
            self.temp_samples = self.temp_samples[-200:]
        avg_temp = sum(self.temp_samples) / len(self.temp_samples)

        # Atualiza elementos visuais da janela principal
        color_hex, _ = get_temperature_color(temp)
        self.lbl_temp_now.set_markup(f"<span foreground='{color_hex}'>{temp:.1f} °C</span>")
        self.lbl_stat_min.set_text(f"{self.min_temp:.1f} °C")
        self.lbl_stat_max.set_text(f"{self.max_temp:.1f} °C")
        self.lbl_stat_avg.set_text(f"{avg_temp:.1f} °C")

        # Badge de status
        ctx_b = self.lbl_status_badge.get_style_context()
        ctx_b.remove_class("badge-cool")
        ctx_b.remove_class("badge-warm")
        ctx_b.remove_class("badge-hot")

        if temp < 55.0:
            self.lbl_status_badge.set_text("NORMAL")
            ctx_b.add_class("badge-cool")
        elif temp < 72.0:
            self.lbl_status_badge.set_text("AQUECENDO")
            ctx_b.add_class("badge-warm")
        else:
            self.lbl_status_badge.set_text("ALERTA ALTO")
            ctx_b.add_class("badge-hot")

        # Gráfico
        self.graph.add_point(temp)

        # Frequência e Uso da CPU
        freq = psutil.cpu_freq()
        if freq:
            f_cur = freq.current
            cores_phys = psutil.cpu_count(logical=False) or 1
            cores_log = psutil.cpu_count(logical=True) or 1
            self.lbl_cpu_details.set_text(
                f"Núcleos: {cores_phys} físicos / {cores_log} lógicos  |  Clock: {f_cur:.0f} MHz"
            )

        # Cargas dos núcleos
        core_percents = psutil.cpu_percent(interval=None, percpu=True)
        overall_pct = sum(core_percents) / len(core_percents) if core_percents else 0.0

        self.lbl_overall_usage.set_text(f"{overall_pct:.1f}%")
        self.overall_bar.set_fraction(max(0.0, min(1.0, overall_pct / 100.0)))

        for idx, pct in enumerate(core_percents):
            if idx < len(self.core_bars):
                frac = max(0.0, min(1.0, pct / 100.0))
                self.core_bars[idx].set_fraction(frac)
                self.core_labels[idx].set_text(f"{pct:.0f}%")

        # Atualiza a bandeja do sistema
        if self.indicator is not None:
            style = self.config.get("tray_style", "both")

            # Texto do Hint / Tooltip exibido ao passar o mouse sobre o ícone
            hint_text = f"CPU: {temp:.1f}°C  |  Uso: {overall_pct:.1f}%"
            self.indicator.set_title(hint_text)

            # Rótulo de texto no painel
            label_text = f"{int(round(temp))}°C"
            if style == "icon_only":
                self.indicator.set_label("", "")
            else:
                self.indicator.set_label(f" {label_text} ", " 999°C ")

            # Ícone dinâmico com o número e dica de ferramenta
            if style != "text_only":
                icon_file = self.icon_generator.generate(temp)
                self.indicator.set_icon_full(icon_file, hint_text)
            else:
                if os.path.isfile(ICON_PATH):
                    self.indicator.set_icon_full(ICON_PATH, hint_text)

            # Atualiza itens de informação no menu da bandeja
            if hasattr(self, "menu_item_sensor_info"):
                self.menu_item_sensor_info.set_label(f"Sensor: {sensor_desc} ({temp:.1f}°C)")
            if hasattr(self, "menu_item_load_info"):
                self.menu_item_load_info.set_label(f"Uso da CPU: {overall_pct:.1f}%")

        # Verifica alerta de temperatura limite
        limit = self.config.get("alert_threshold", 80.0)
        if self.config.get("alert_enabled", True) and temp >= limit:
            self.trigger_alert(temp, limit)

        return True

    def quit_app(self):
        """Finaliza a aplicação com segurança."""
        if self.timer_id:
            GLib.source_remove(self.timer_id)
        if HAS_NOTIFY:
            try:
                Notify.uninit()
            except Exception:
                pass
        if Gtk.main_level() > 0:
            Gtk.main_quit()


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} - Monitor de Temperatura da CPU")
    parser.add_argument(
        "--minimized", "-m",
        action="store_true",
        help="Iniciar diretamente na bandeja do sistema sem abrir a janela"
    )
    args = parser.parse_args()

    # Tratamento para encerrar suavemente com Ctrl+C no terminal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, lambda s, f: Gtk.main_quit())

    app = CoreTempApp(start_minimized=args.minimized)
    Gtk.main()


if __name__ == "__main__":
    main()
