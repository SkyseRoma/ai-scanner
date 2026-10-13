"""
Web UI for Scanner — scan history, AI chat, settings, logs.
"""

import os
import sys
import json
import time
import base64
import threading
import http.server
import socketserver
import argparse
from collections import deque

# ── Configuration ─────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DB_DIR = os.path.join(DATA_DIR, "database")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

# ── Log buffer ────────────────────────────────────────────────────
_log_buffer = deque(maxlen=200)
_log_lock = threading.Lock()
_original_print = print


def log_print(*args, **kwargs):
    """Intercepts print — outputs to console and log buffer."""
    msg = " ".join(str(a) for a in args)
    _original_print(*args, **kwargs)
    with _log_lock:
        _log_buffer.append({"time": time.strftime("%H:%M:%S"), "msg": msg})


# Override print globally
import builtins
builtins.print = log_print


def get_logs(since=0):
    """Get logs starting from position."""
    with _log_lock:
        logs = list(_log_buffer)
    return logs[since:]


def load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


_batt_cache = {"t": 0, "data": None}


def get_battery_status():
    now = time.time()
    if now - _batt_cache["t"] < 2.0 and _batt_cache["data"] is not None:
        return _batt_cache["data"]
    try:
        from modules.ups import UPS
        ups = UPS()
        st = ups.read_status()
        ups.close()
    except Exception as e:
        st = {"available": False, "error": str(e)}
    _batt_cache["t"] = now
    _batt_cache["data"] = st
    return st


def get_wifi_status():
    try:
        from modules import wifi
        return wifi.get_status()
    except Exception as e:
        return {"error": str(e), "devices": [], "wlan_state": "missing"}


def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_scans():
    scans = []
    if not os.path.exists(DB_DIR):
        return scans
    for entry in sorted(os.listdir(DB_DIR), reverse=True):
        scan_dir = os.path.join(DB_DIR, entry)
        if not os.path.isdir(scan_dir):
            continue
        scan = {"id": entry, "time": entry}
        img_path = os.path.join(scan_dir, "shot.jpg")
        txt_path = os.path.join(scan_dir, "answer.txt")
        if os.path.exists(img_path):
            scan["image"] = img_path
        if os.path.exists(txt_path):
            with open(txt_path) as f:
                scan["answer"] = f.read().strip()
        scans.append(scan)
    return scans


def ask_llm(question, image_path=None):
    import requests
    settings = load_settings()
    model = settings.get("model", "qwen3.5:0.8b")
    prompt = settings.get("gpt_prompt", "")
    url = f"http://{settings.get('IP', 'localhost')}:{settings.get('PORT', '11434')}/api/chat"

    messages = [{"role": "system", "content": prompt}]
    user_msg = {"role": "user", "content": question}
    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        user_msg["images"] = [b64]
    messages.append(user_msg)

    try:
        resp = requests.post(url, json={
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"num_predict": 500, "temperature": 0.3},
        }, timeout=300)
        data = resp.json()
        return data.get("message", {}).get("content", "").strip()
    except Exception as e:
        return f"Error: {e}"


# ── HTML ───────────────────────────────────────────────────────────────
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Subnautica Scanner</title>
<style>
:root {
  --bg-deep: #0a1628;
  --bg-panel: #0d1f3c;
  --bg-card: #132a4a;
  --bg-input: #0a1628;
  --accent: #00e5ff;
  --accent2: #00b8d4;
  --accent-dim: #00e5ff33;
  --text: #b8e6f0;
  --text-bright: #e0f7fa;
  --danger: #ff5252;
  --success: #69f0ae;
  --border: #1a3a5c;
  --glow: 0 0 10px #00e5ff44;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { background:var(--bg-deep); color:var(--text); font-family:'Courier New',monospace; min-height:100vh; }
a { color:var(--accent); }

.header { background:var(--bg-panel); border-bottom:1px solid var(--border); padding:12px 20px; display:flex; align-items:center; gap:15px; }
.header h1 { font-size:1.2em; color:var(--accent); text-shadow:var(--glow); }
.header .nav { display:flex; gap:5px; margin-left:auto; }
.nav-btn { background:transparent; border:1px solid var(--border); color:var(--text); padding:8px 16px; font-family:inherit; font-size:.85em; cursor:pointer; border-radius:4px; transition:.2s; }
.nav-btn:hover, .nav-btn.active { background:var(--accent-dim); border-color:var(--accent); color:var(--accent); }

.content { max-width:960px; margin:20px auto; padding:0 15px; }
.section { display:none; }
.section.active { display:block; }

.card { background:var(--bg-card); border:1px solid var(--border); border-radius:8px; padding:16px; margin-bottom:12px; }
.card:hover { border-color:var(--accent2); }
.card-title { color:var(--accent); font-size:1em; margin-bottom:8px; }
.card-img { max-width:100%; border-radius:4px; margin:8px 0; cursor:pointer; }
.card-text { font-size:.9em; line-height:1.5; white-space:pre-wrap; }

.chat-box { height:60vh; overflow-y:auto; padding:10px; background:var(--bg-input); border:1px solid var(--border); border-radius:8px; margin-bottom:10px; }
.msg { margin:8px 0; padding:10px 14px; border-radius:8px; max-width:85%; line-height:1.5; font-size:.9em; }
.msg.user { background:var(--accent-dim); margin-left:auto; border:1px solid var(--accent2); color:var(--text-bright); }
.msg.ai { background:var(--bg-card); border:1px solid var(--border); }
.msg .label { font-size:.75em; color:var(--accent); margin-bottom:4px; }
.chat-input { display:flex; gap:8px; }
.chat-input input { flex:1; background:var(--bg-input); border:1px solid var(--border); color:var(--text-bright); padding:10px 14px; font-family:inherit; font-size:.9em; border-radius:6px; outline:none; }
.chat-input input:focus { border-color:var(--accent); }
.chat-input button { background:var(--accent); color:var(--bg-deep); border:none; padding:10px 20px; font-family:inherit; font-weight:bold; cursor:pointer; border-radius:6px; }
.chat-input button:hover { background:var(--accent2); }
.chat-input button:disabled { opacity:.4; }

.form-group { margin-bottom:16px; }
.form-group label { display:block; color:var(--accent); font-size:.85em; margin-bottom:6px; }
.form-group input, .form-group textarea { width:100%; background:var(--bg-input); border:1px solid var(--border); color:var(--text-bright); padding:10px; font-family:inherit; font-size:.9em; border-radius:6px; outline:none; }
.form-group textarea { min-height:120px; resize:vertical; }
.form-group input:focus, .form-group textarea:focus { border-color:var(--accent); }
.save-btn { background:var(--accent); color:var(--bg-deep); border:none; padding:10px 24px; font-family:inherit; font-weight:bold; cursor:pointer; border-radius:6px; }
.save-btn:hover { background:var(--accent2); }
.toast { position:fixed; bottom:20px; right:20px; background:var(--success); color:var(--bg-deep); padding:10px 20px; border-radius:6px; display:none; font-weight:bold; z-index:999; }

.modal { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,.85); z-index:100; justify-content:center; align-items:center; }
.modal.active { display:flex; }
.modal img { max-width:95%; max-height:95%; border-radius:8px; }
.modal .close { position:absolute; top:20px; right:30px; color:white; font-size:2em; cursor:pointer; }

.scan-ref { display:inline-block; background:var(--accent-dim); border:1px solid var(--accent2); padding:2px 8px; border-radius:4px; font-size:.8em; cursor:pointer; color:var(--accent); }
.scan-ref:hover { background:var(--accent); color:var(--bg-deep); }
.del-btn { background:transparent; border:1px solid var(--danger); color:var(--danger); padding:2px 8px; border-radius:4px; font-size:.8em; cursor:pointer; margin-left:4px; font-family:inherit; }
.del-btn:hover { background:var(--danger); color:var(--bg-deep); }
.play-btn { background:var(--accent-dim); border:1px solid var(--accent2); padding:2px 8px; border-radius:4px; font-size:.8em; cursor:pointer; color:var(--accent); margin-left:4px; font-family:inherit; }
.play-btn:hover { background:var(--accent); color:var(--bg-deep); }
.chat-img { max-width:200px; border-radius:6px; margin:8px 0; border:1px solid var(--border); }

/* Log panel */
.log-panel { background:var(--bg-input); border:1px solid var(--border); border-radius:8px; padding:12px; max-height:300px; overflow-y:auto; font-size:.8em; line-height:1.6; }
.log-panel .log-line { color:var(--text); }
.log-panel .log-line .log-time { color:var(--accent2); margin-right:8px; }
.log-panel .log-line.log-error { color:var(--danger); }
.log-panel .log-line.log-scan { color:var(--success); }
.log-panel .log-line.log-ai { color:var(--accent); }
.log-status { display:flex; align-items:center; gap:8px; margin-bottom:8px; }
.log-status .dot { width:8px; height:8px; border-radius:50%; background:var(--success); animation:pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }

/* Battery */
.batt-badge { display:flex; align-items:center; gap:8px; margin-left:12px; padding:6px 12px; border:1px solid var(--border); border-radius:6px; cursor:pointer; white-space:nowrap; font-size:.85em; }
.batt-badge:hover { border-color:var(--accent); }
.batt-icon { width:22px; height:11px; border:1px solid var(--text); border-radius:2px; position:relative; display:inline-block; box-sizing:border-box; background:var(--bg-input); overflow:hidden; }
.batt-icon::after { content:''; position:absolute; right:-3px; top:2px; width:2px; height:5px; background:var(--text); border-radius:0 1px 1px 0; z-index:1; }
.batt-fill { display:block; height:100%; width:0%; background:var(--success); border-radius:0; min-width:0; }
.batt-fill.low { background:var(--danger); }
.batt-fill.mid { background:#ffd54f; }
.batt-panel { background:var(--bg-card); border:1px solid var(--border); border-radius:8px; padding:14px 16px; margin:12px 0; }
.batt-panel h3 { color:var(--accent); font-size:.95em; margin-bottom:10px; }
.batt-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:10px; }
.batt-grid .item { background:var(--bg-input); border:1px solid var(--border); border-radius:6px; padding:10px; }
.batt-grid .label { font-size:.75em; color:var(--accent2); margin-bottom:4px; }
.batt-grid .value { font-size:1.15em; color:var(--text-bright); }
.batt-panel .status-charging { color:var(--success); }
.batt-panel .status-idle { color:var(--accent2); }
.batt-panel .status-error { color:var(--danger); }

/* WiFi */
.wifi-list { margin:10px 0; }
.wifi-item { display:flex; align-items:center; gap:10px; padding:8px 10px; border:1px solid var(--border); border-radius:6px; margin-bottom:6px; background:var(--bg-input); }
.wifi-item.active { border-color:var(--accent); }
.wifi-item .ssid { flex:1; font-size:.9em; }
.wifi-item .sig { font-size:.8em; color:var(--accent2); min-width:42px; }
.wifi-item button { font-size:.8em; }
.wifi-pass { width:100%; background:var(--bg-input); border:1px solid var(--border); color:var(--text-bright); padding:8px; margin:8px 0; font-family:inherit; border-radius:6px; }
.wifi-actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
</style>
</head>
<body>

<div class="header">
  <h1>SUBNAUTICA SCANNER</h1>
  <div class="batt-badge" id="batt-badge" onclick="toggleBattPanel()" title="Battery">
    <span class="batt-icon"><span class="batt-fill" id="batt-fill" style="width:60%"></span></span>
    <span id="batt-text">—%</span>
  </div>
  <div class="nav">
    <button class="nav-btn active" onclick="showSection('scans')" data-i18n="nav_scans">Сканы</button>
    <button class="nav-btn" onclick="showSection('chat')" data-i18n="nav_chat">Чат</button>
    <button class="nav-btn" onclick="showSection('settings')" data-i18n="nav_settings">Настройки</button>
    <button class="nav-btn" onclick="showSection('logs')" data-i18n="nav_logs">Логи</button>
    <select id="lang-select" onchange="setLang(this.value)" style="background:var(--bg-input);color:var(--text);border:1px solid var(--border);padding:6px;border-radius:4px;font-family:inherit;margin-left:10px;">
      <option value="ru">RU</option>
      <option value="en">EN</option>
      <option value="zh">中文</option>
      <option value="es">ES</option>
    </select>
  </div>
</div>

<div class="content">
<!-- Battery (detailed) -->
<div class="batt-panel" id="batt-panel" style="display:none">
  <h3 data-i18n="batt_title">Батарея UPS</h3>
  <div class="batt-grid" id="batt-grid"></div>
  <div id="batt-status" class="status-idle" style="margin-top:10px;font-size:.85em"></div>
</div>

<!-- Scans -->
<div class="section active" id="sec-scans">
  <h2 style="color:var(--accent);margin-bottom:15px" data-i18n="scans_title">База сканов</h2>
  <div id="scan-list"></div>
</div>

<!-- Chat -->
<div class="section" id="sec-chat">
  <h2 style="color:var(--accent);margin-bottom:15px" data-i18n="chat_title">Чат с ИИ</h2>
  <div class="chat-box" id="chat-box"></div>
  <div class="chat-input">
    <input id="chat-msg" data-i18n-placeholder="chat_placeholder" placeholder="Спроси о скане или о чём угодно..." onkeydown="if(event.key==='Enter')sendChat()">
    <button id="chat-send" onclick="sendChat()" data-i18n="chat_send">Отправить</button>
  </div>
</div>

<!-- Settings -->
<div class="section" id="sec-settings">
  <h2 style="color:var(--accent);margin-bottom:15px" data-i18n="settings_title">Настройки</h2>
  <div class="card">
    <div class="form-group">
      <label data-i18n="set_model">Модель</label>
      <select id="set-model" style="width:100%;background:var(--bg-input);border:1px solid var(--border);color:var(--text-bright);padding:10px;font-family:inherit;font-size:.9em;border-radius:6px;outline:none;"></select>
    </div>
    <div class="form-group">
      <label data-i18n="set_prompt">Системный промпт</label>
      <textarea id="set-prompt"></textarea>
    </div>
    <div class="form-group">
      <label data-i18n="set_tokens">Макс. токенов</label>
      <input id="set-tokens" type="number" value="300">
    </div>
    <button class="save-btn" onclick="saveSettings()" data-i18n="set_save">Сохранить</button>
  </div>

  <div class="card">
    <div class="card-title" data-i18n="wifi_title">Wi-Fi</div>
    <div id="wifi-status" class="card-text" style="margin-bottom:8px">—</div>
    <button class="save-btn" id="wifi-scan-btn" onclick="scanWifi()" data-i18n="wifi_scan">Сканировать</button>
    <div class="wifi-list" id="wifi-list"></div>
    <div id="wifi-manual" style="display:none">
      <input class="wifi-pass" id="wifi-ssid" type="text" data-i18n-placeholder="wifi_ssid_ph" placeholder="Имя сети (SSID)">
    </div>
    <div style="display:flex;gap:8px;align-items:center">
      <input class="wifi-pass" id="wifi-pass" type="password" data-i18n-placeholder="wifi_pass_ph" placeholder="Пароль выбранной сети" style="flex:1;margin:8px 0">
      <button type="button" class="play-btn" id="wifi-pass-toggle" onclick="toggleWifiPass()" data-i18n="wifi_show_pass">Показать</button>
    </div>
    <div class="wifi-actions">
      <button class="save-btn" onclick="connectWifi()" data-i18n="wifi_connect">Подключиться</button>
      <button class="del-btn" onclick="startHotspot()" data-i18n="wifi_hotspot">Точка доступа</button>
    </div>
    <div id="wifi-msg" class="card-text" style="margin-top:8px"></div>
  </div>
</div>

<!-- Logs -->
<div class="section" id="sec-logs">
  <h2 style="color:var(--accent);margin-bottom:15px" data-i18n="logs_title">Логи системы</h2>
  <div class="log-status"><div class="dot"></div><span data-i18n="logs_live">Обновление в реальном времени</span></div>
  <div class="log-panel" id="log-panel"></div>
</div>
</div>

<!-- Modal -->
<div class="modal" id="modal" onclick="this.classList.remove('active')">
  <span class="close">&times;</span>
  <img id="modal-img">
</div>

<div class="toast" id="toast" data-i18n="toast_saved">Сохранено!</div>

<script>
// i18n
const LANGS = {
  ru: {
    nav_scans:'Сканы', nav_chat:'Чат', nav_settings:'Настройки', nav_logs:'Логи',
    scans_title:'База сканов', chat_title:'Чат с ИИ', settings_title:'Настройки', logs_title:'Логи системы',
    chat_placeholder:'Спроси о скане или о чём угодно...', chat_send:'Отправить',
    set_model:'Модель', set_prompt:'Системный промпт', set_tokens:'Макс. токенов',
    set_save:'Сохранить', toast_saved:'Сохранено!',
    btn_play:'Озвучить', btn_ask:'Спросить ИИ', btn_delete:'Удалить',
    no_scans:'Пока нет сканов.', no_audio:'Нет аудио',
    confirm_delete:'Удалить скан', error:'Ошибка',
    label_you:'Вы', label_ai:'Сканер',
    ask_prompt:'Расскажи подробнее об этом скане.',
    logs_live:'Обновление в реальном времени',
    batt_title:'Батарея UPS', batt_na:'Нет данных',
    batt_percent:'Заряд', batt_voltage:'Напряжение', batt_current:'Ток',
    batt_power:'Мощность', batt_range:'Диапазон', batt_charging:'Идёт зарядка', batt_discharging:'Разрядка / работа',
    wifi_title:'Wi-Fi', wifi_scan:'Сканировать', wifi_connect:'Подключиться',
    wifi_connected:'Активна', wifi_hotspot:'Точка доступа', wifi_hotspot_off:'Выключить AP',
    wifi_hotspot_ok:'Точка доступа включена', wifi_pass_ph:'Пароль выбранной сети',
    wifi_state:'Состояние', wifi_none:'Сети не найдены', wifi_selected:'Выбрана сеть',
    wifi_select_first:'Сначала выберите сеть', wifi_connecting:'Подключение', wifi_ok:'Подключено',
    wifi_ssid_ph:'Имя сети (SSID)', wifi_manual_hint:'AP-режим: введите имя сети и пароль вручную.',
    wifi_show_pass:'Показать', wifi_hide_pass:'Скрыть',
  },
  en: {
    nav_scans:'Scans', nav_chat:'Chat', nav_settings:'Settings', nav_logs:'Logs',
    scans_title:'Scan Database', chat_title:'AI Chat', settings_title:'Settings', logs_title:'System Logs',
    chat_placeholder:'Ask about a scan or anything...', chat_send:'Send',
    set_model:'Model', set_prompt:'System Prompt', set_tokens:'Max Tokens',
    set_save:'Save', toast_saved:'Saved!',
    btn_play:'Play Audio', btn_ask:'Ask AI', btn_delete:'Delete',
    no_scans:'No scans yet.', no_audio:'No audio',
    confirm_delete:'Delete scan', error:'Error',
    label_you:'You', label_ai:'Scanner',
    ask_prompt:'Tell me more about this scan.',
    logs_live:'Real-time updates',
    batt_title:'UPS Battery', batt_na:'No data',
    batt_percent:'Charge', batt_voltage:'Voltage', batt_current:'Current',
    batt_power:'Power', batt_range:'Range', batt_charging:'Charging', batt_discharging:'Discharging / load',
    wifi_title:'Wi-Fi', wifi_scan:'Scan', wifi_connect:'Connect',
    wifi_connected:'Active', wifi_hotspot:'Hotspot', wifi_hotspot_off:'Stop AP',
    wifi_hotspot_ok:'Hotspot enabled', wifi_pass_ph:'Password for selected network',
    wifi_state:'State', wifi_none:'No networks found', wifi_selected:'Selected',
    wifi_select_first:'Select a network first', wifi_connecting:'Connecting', wifi_ok:'Connected',
    wifi_ssid_ph:'Network name (SSID)', wifi_manual_hint:'AP mode: enter SSID and password manually.',
    wifi_show_pass:'Show', wifi_hide_pass:'Hide',
  },
  zh: {
    nav_scans:'扫描', nav_chat:'聊天', nav_settings:'设置', nav_logs:'日志',
    scans_title:'扫描数据库', chat_title:'AI 聊天', settings_title:'设置', logs_title:'系统日志',
    chat_placeholder:'询问扫描结果或任何问题...', chat_send:'发送',
    set_model:'模型', set_prompt:'系统提示词', set_tokens:'最大令牌数',
    set_save:'保存', toast_saved:'已保存！',
    btn_play:'播放音频', btn_ask:'询问AI', btn_delete:'删除',
    no_scans:'暂无扫描记录。', no_audio:'无音频',
    confirm_delete:'删除扫描', error:'错误',
    label_you:'你', label_ai:'扫描仪',
    ask_prompt:'请详细介绍这次扫描。',
    logs_live:'实时更新',
    batt_title:'UPS 电池', batt_na:'无数据',
    batt_percent:'电量', batt_voltage:'电压', batt_current:'电流',
    batt_power:'功率', batt_range:'范围', batt_charging:'充电中', batt_discharging:'放电 / 使用中',
    wifi_title:'Wi-Fi', wifi_scan:'扫描', wifi_connect:'连接',
    wifi_connected:'已连接', wifi_hotspot:'热点', wifi_hotspot_off:'关闭热点',
    wifi_hotspot_ok:'热点已开启', wifi_pass_ph:'所选网络的密码',
    wifi_state:'状态', wifi_none:'未找到网络', wifi_selected:'已选择',
    wifi_select_first:'请先选择网络', wifi_connecting:'连接中', wifi_ok:'已连接',
    wifi_ssid_ph:'网络名称 (SSID)', wifi_manual_hint:'AP 模式：请手动输入 SSID 和密码。',
    wifi_show_pass:'显示', wifi_hide_pass:'隐藏',
  },
  es: {
    nav_scans:'Escaneos', nav_chat:'Chat', nav_settings:'Ajustes', nav_logs:'Logs',
    scans_title:'Base de Escaneos', chat_title:'Chat con IA', settings_title:'Ajustes', logs_title:'Logs del Sistema',
    chat_placeholder:'Pregunta sobre un escaneo o cualquier cosa...', chat_send:'Enviar',
    set_model:'Modelo', set_prompt:'Prompt del Sistema', set_tokens:'Máx. Tokens',
    set_save:'Guardar', toast_saved:'¡Guardado!',
    btn_play:'Audio', btn_ask:'Preguntar IA', btn_delete:'Eliminar',
    no_scans:'Aún no hay escaneos.', no_audio:'Sin audio',
    confirm_delete:'Eliminar escaneo', error:'Error',
    label_you:'Tú', label_ai:'Escáner',
    ask_prompt:'Cuéntame más sobre este escaneo.',
    logs_live:'Actualización en tiempo real',
    batt_title:'Batería UPS', batt_na:'Sin datos',
    batt_percent:'Carga', batt_voltage:'Voltaje', batt_current:'Corriente',
    batt_power:'Potencia', batt_range:'Rango', batt_charging:'Cargando', batt_discharging:'Descarga / uso',
    wifi_title:'Wi-Fi', wifi_scan:'Escanear', wifi_connect:'Conectar',
    wifi_connected:'Activa', wifi_hotspot:'Punto de acceso', wifi_hotspot_off:'Apagar AP',
    wifi_hotspot_ok:'Punto de acceso activado', wifi_pass_ph:'Contraseña de la red seleccionada',
    wifi_state:'Estado', wifi_none:'Sin redes', wifi_selected:'Seleccionada',
    wifi_select_first:'Selecciona una red primero', wifi_connecting:'Conectando', wifi_ok:'Conectado',
    wifi_ssid_ph:'Nombre de red (SSID)', wifi_manual_hint:'Modo AP: introduce SSID y contraseña a mano.',
    wifi_show_pass:'Mostrar', wifi_hide_pass:'Ocultar',
  },
};

let curLang = localStorage.getItem('scanner_lang') || 'ru';
function t(key) { return LANGS[curLang]?.[key] || LANGS['ru'][key] || key; }

function setLang(lang) {
  curLang = lang;
  localStorage.setItem('scanner_lang', lang);
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  loadScans();
  fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({language:lang})});
}

function showSection(name) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.getElementById('sec-'+name).classList.add('active');
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  if (name==='scans') loadScans();
  if (name==='settings') { loadSettings(); loadWifiStatus(); }
}

// WiFi
let selectedWifi = null;
function loadWifiStatus() {
  fetch('/api/wifi/status').then(r=>r.json()).then(st => {
    const el = document.getElementById('wifi-status');
    if (!el) return;
    el.textContent = t('wifi_state') + ': ' + (st.wlan_state||'?') +
      (st.wlan_connection ? ' (' + st.wlan_connection + ')' : '') +
      (st.hotspot ? ' · ' + t('wifi_hotspot') : '');
    const scanBtn = document.getElementById('wifi-scan-btn');
    const manual = document.getElementById('wifi-manual');
    const list = document.getElementById('wifi-list');
    if (st.hotspot) {
      if (scanBtn) scanBtn.style.display = 'none';
      if (manual) manual.style.display = 'block';
      if (list) list.innerHTML = '<div class="card-text">' + t('wifi_manual_hint') + '</div>';
    } else {
      if (scanBtn) scanBtn.style.display = '';
      if (manual) manual.style.display = 'none';
    }
  }).catch(()=>{});
}

function scanWifi() {
  const list = document.getElementById('wifi-list');
  const manual = document.getElementById('wifi-manual');
  list.innerHTML = '<div class="card-text">…</div>';
  fetch('/api/wifi/scan').then(r=>r.json()).then(d => {
    if (d.ap_mode) {
      if (manual) manual.style.display = 'block';
      list.innerHTML = '<div class="card-text">' + t('wifi_manual_hint') + '</div>';
      loadWifiStatus();
      return;
    }
    if (manual) manual.style.display = 'none';
    if (!d.ok) { list.innerHTML = '<div class="status-error">' + (d.error||t('error')) + '</div>'; return; }
    list.innerHTML = (d.networks||[]).map(n => `
      <div class="wifi-item${n.active?' active':''}" data-ssid="${(n.ssid||'').replace(/"/g,'&quot;')}">
        <span class="ssid">${n.ssid||'(hidden)'}</span>
        <span class="sig">${n.signal}%</span>
        <span class="sig">${n.security?'🔒':'—'}</span>
        <button class="play-btn" onclick="pickWifi(this)">${n.active?t('wifi_connected'):t('wifi_connect')}</button>
      </div>`).join('') || '<div class="card-text">' + t('wifi_none') + '</div>';
    loadWifiStatus();
  }).catch(e => { list.innerHTML = '<div class="status-error">'+e+'</div>'; });
}

function pickWifi(btn) {
  const item = btn.closest('.wifi-item');
  selectedWifi = item.dataset.ssid;
  document.querySelectorAll('.wifi-item').forEach(i => i.style.borderColor='');
  item.style.borderColor = 'var(--accent)';
  const m = document.getElementById('wifi-ssid');
  if (m) m.value = selectedWifi;
  document.getElementById('wifi-msg').textContent = t('wifi_selected') + ': ' + selectedWifi;
}

function toggleWifiPass() {
  const input = document.getElementById('wifi-pass');
  const btn = document.getElementById('wifi-pass-toggle');
  if (!input || !btn) return;
  const show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  btn.textContent = show ? t('wifi_hide_pass') : t('wifi_show_pass');
}

function connectWifi() {
  const manual = document.getElementById('wifi-ssid');
  const ssid = (manual && manual.value.trim()) || selectedWifi;
  const password = document.getElementById('wifi-pass').value;
  if (!ssid) { document.getElementById('wifi-msg').textContent = t('wifi_select_first'); return; }
  document.getElementById('wifi-msg').textContent = t('wifi_connecting') + '…';
  fetch('/api/wifi/connect', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ssid, password})}).then(r=>r.json()).then(d => {
    document.getElementById('wifi-msg').textContent = d.ok ? (d.message||t('wifi_ok')) : (t('error')+': '+(d.error||''));
    loadWifiStatus();
    setTimeout(loadWifiStatus, 3000);
  }).catch(e => { document.getElementById('wifi-msg').textContent = String(e); });
}

function startHotspot() {
  fetch('/api/wifi/hotspot', {method:'POST', headers:{'Content-Type':'application/json'}, body: '{}'})
    .then(r=>r.json()).then(d => {
      document.getElementById('wifi-msg').textContent = d.ok ? t('wifi_hotspot_ok') : (t('error')+': '+(d.error||''));
      loadWifiStatus();
    });
}

function stopHotspot() {
  fetch('/api/wifi/hotspot', {method:'DELETE'}).then(r=>r.json()).then(d => {
    document.getElementById('wifi-msg').textContent = d.ok ? t('wifi_hotspot_off') : (t('error')+': '+(d.error||''));
    loadWifiStatus();
  });
}

// Scans (auto-refresh)
let lastScanCount = 0;
function loadScans() {
  fetch('/api/scans').then(r=>r.json()).then(scans => {
    const el = document.getElementById('scan-list');
    if (!scans.length) { el.innerHTML=`<div class="card"><p>${t('no_scans')}</p></div>`; return; }
    el.innerHTML = scans.map(s => `
      <div class="card">
        <div class="card-title">${s.id}</div>
        ${s.image ? `<img class="card-img" src="/api/scan/${s.id}/image" onclick="showModal('/api/scan/${s.id}/image')">` : ''}
        <div class="card-text">${s.answer||''}</div>
        <br>
        <button class="play-btn" onclick="playAudio('${s.id}')">${t('btn_play')}</button>
        <span class="scan-ref" onclick="chatAbout('${s.id}')">${t('btn_ask')}</span>
        <button class="del-btn" onclick="deleteScan('${s.id}')">${t('btn_delete')}</button>
      </div>
    `).join('');
    lastScanCount = scans.length;
  });
}

// Auto-refresh scans every 5s
setInterval(() => {
  if (document.getElementById('sec-scans').classList.contains('active')) {
    fetch('/api/scans').then(r=>r.json()).then(scans => {
      if (scans.length !== lastScanCount) loadScans();
    });
  }
}, 5000);

// Battery
function toggleBattPanel() {
  const p = document.getElementById('batt-panel');
  const show = p.style.display === 'none';
  p.style.display = show ? 'block' : 'none';
  if (show) loadBattery(true);
}

function loadBattery(force) {
  fetch('/api/battery').then(r=>r.json()).then(b => {
    const fill = document.getElementById('batt-fill');
    const text = document.getElementById('batt-text');
    if (!b || !b.available) {
      fill.style.width = '0%';
      fill.className = 'batt-fill low';
      text.textContent = t('batt_na');
      if (force) {
        document.getElementById('batt-grid').innerHTML = '';
        const st = document.getElementById('batt-status');
        st.className = 'status-error';
        st.textContent = (b && b.error) ? b.error : t('batt_na');
      }
      return;
    }
    const pct = Math.max(0, Math.min(100, Math.round(b.percent || 0)));
    fill.style.width = pct + '%';
    fill.className = 'batt-fill' + (pct < 20 ? ' low' : pct < 50 ? ' mid' : '');
    text.textContent = pct + '%' + (b.charging ? ' ⚡' : '');
    if (force || document.getElementById('batt-panel').style.display !== 'none') {
      const rows = [
        [t('batt_percent'), pct + '%'],
        [t('batt_voltage'), b.voltage_v + ' V'],
        [t('batt_current'), (b.current_a * 1000).toFixed(0) + ' mA'],
        [t('batt_power'), b.power_w + ' W'],
      ];
      document.getElementById('batt-grid').innerHTML = rows.map(([l,v]) =>
        `<div class="item"><div class="label">${l}</div><div class="value">${v}</div></div>`).join('');
      const st = document.getElementById('batt-status');
      st.className = b.charging ? 'status-charging' : 'status-idle';
      st.textContent = b.charging ? t('batt_charging') : t('batt_discharging');
    }
  }).catch(() => {});
}
loadBattery(true);
setInterval(() => loadBattery(false), 5000);

function showModal(src) { document.getElementById('modal-img').src = src; document.getElementById('modal').classList.add('active'); }

function deleteScan(scanId) {
  if (!confirm(t('confirm_delete') + ' ' + scanId + '?')) return;
  fetch('/api/scan/' + scanId, {method:'DELETE'}).then(r=>r.json()).then(d => { if (d.ok) loadScans(); else alert(t('error') + ': ' + (d.error||'')); });
}

let currentAudio = null;
let playingId = null;
function playAudio(scanId) {
  if (currentAudio && playingId === scanId) { currentAudio.pause(); currentAudio.currentTime = 0; currentAudio = null; playingId = null; return; }
  if (currentAudio) { currentAudio.pause(); currentAudio.currentTime = 0; }
  currentAudio = new Audio('/api/scan/' + scanId + '/audio');
  playingId = scanId;
  currentAudio.play().catch(() => { currentAudio = null; playingId = null; alert(t('no_audio')); });
  currentAudio.onended = () => { currentAudio = null; playingId = null; };
}

function chatAbout(scanId) {
  showSection('chat');
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.nav-btn')[1].classList.add('active');
  const box = document.getElementById('chat-box');
  const div = document.createElement('div');
  div.className = 'msg user';
  div.innerHTML = `<div class="label">${t('label_you')}</div><img class="chat-img" src="/api/scan/${scanId}/image"><br>${t('ask_prompt')}`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  chatHistory.push({role:'user', content:t('ask_prompt') + ' (ID: ' + scanId + ')'});
  fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({messages:chatHistory, scan_id:scanId})}).then(r=>r.json()).then(d => {
    const reply = d.answer || t('error');
    addChatMsg('ai', reply);
    chatHistory.push({role:'assistant', content:reply});
  });
}

let chatHistory = [];
function addChatMsg(role, text) {
  const box = document.getElementById('chat-box');
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.innerHTML = `<div class="label">${role==='user'?t('label_you'):t('label_ai')}</div>${text}`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function sendChat() {
  const input = document.getElementById('chat-msg');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  addChatMsg('user', text);
  chatHistory.push({role:'user', content:text});
  document.getElementById('chat-send').disabled = true;
  fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({messages:chatHistory})}).then(r=>r.json()).then(d => {
    const reply = d.answer || 'No response';
    addChatMsg('ai', reply);
    chatHistory.push({role:'assistant', content:reply});
    document.getElementById('chat-send').disabled = false;
  }).catch(e => { addChatMsg('ai', 'Error: ' + e); document.getElementById('chat-send').disabled = false; });
}

// Settings
function loadSettings() {
  Promise.all([
    fetch('/api/settings').then(r=>r.json()),
    fetch('/api/models').then(r=>r.json())
  ]).then(([s, m]) => {
    const sel = document.getElementById('set-model');
    sel.innerHTML = '';
    (m.models||[]).forEach(name => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      if (name === s.model) opt.selected = true;
      sel.appendChild(opt);
    });
    document.getElementById('set-prompt').value = s.gpt_prompt||'';
    document.getElementById('set-tokens').value = s.max_tokens||300;
  });
}

function saveSettings() {
  const data = {
    model: document.getElementById('set-model').value,
    gpt_prompt: document.getElementById('set-prompt').value,
    max_tokens: parseInt(document.getElementById('set-tokens').value)||300,
  };
  fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)}).then(() => {
    const t = document.getElementById('toast');
    t.style.display='block';
    setTimeout(()=>t.style.display='none',2000);
  });
}

// Logs (SSE)
let logOffset = 0;
function startLogStream() {
  const evtSource = new EventSource('/api/logs/stream');
  evtSource.onmessage = function(event) {
    const logs = JSON.parse(event.data);
    const panel = document.getElementById('log-panel');
    logs.forEach(log => {
      const div = document.createElement('div');
      div.className = 'log-line';
      if (log.msg.includes('Ошибка') || log.msg.includes('ERROR')) div.className += ' log-error';
      else if (log.msg.includes('Снимок') || log.msg.includes('Готово')) div.className += ' log-scan';
      else if (log.msg.includes('Ответ') || log.msg.includes('AI')) div.className += ' log-ai';
      div.innerHTML = `<span class="log-time">${log.time}</span>${log.msg}`;
      panel.appendChild(div);
      panel.scrollTop = panel.scrollHeight;
    });
  };
  evtSource.onerror = function() {
    setTimeout(startLogStream, 3000);
  };
}

// Init
document.getElementById('lang-select').value = curLang;
setLang(curLang);
loadScans();
startLogStream();
</script>
</body>
</html>"""


# ── HTTP Handler ──────────────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split('?')[0]

        if path == '/':
            self._html(HTML_PAGE)

        elif path == '/api/scans':
            self._json(get_scans())

        elif path.startswith('/api/scan/') and path.endswith('/image'):
            scan_id = path.split('/')[3]
            img_path = os.path.join(DB_DIR, scan_id, "shot.jpg")
            if os.path.exists(img_path):
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.end_headers()
                with open(img_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()

        elif path.startswith('/api/scan/') and path.endswith('/audio'):
            scan_id = path.split('/')[3]
            scan_dir = os.path.join(DB_DIR, scan_id)
            # new sessions use audio.wav; old ones still have audio.mp3
            audio_path = None
            for name, mime in (("audio.wav", "audio/wav"), ("audio.mp3", "audio/mpeg")):
                p = os.path.join(scan_dir, name)
                if os.path.exists(p):
                    audio_path = p
                    content_type = mime
                    break
            if audio_path:
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.end_headers()
                with open(audio_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()

        elif path == '/api/battery':
            self._json(get_battery_status())

        elif path == '/api/wifi/status':
            self._json(get_wifi_status())

        elif path == '/api/wifi/scan':
            try:
                from modules import wifi
                allow_drop = 'ap_drop=1' in self.path or 'force=1' in self.path
                self._json(wifi.scan_networks(allow_ap_drop=allow_drop))
            except Exception as e:
                self._json({"ok": False, "error": str(e), "networks": []})

        elif path == '/api/settings':
            self._json(load_settings())

        elif path == '/api/models':
            import requests as _req
            try:
                r = _req.get("http://localhost:11434/api/tags", timeout=3)
                models = [m["name"] for m in r.json().get("models", [])]
            except Exception:
                models = []
            self._json({"models": models})

        elif path == '/api/logs':
            offset = int(self.path.split('offset=')[1]) if 'offset=' in self.path else 0
            self._json({"logs": get_logs(offset), "total": len(_log_buffer)})

        elif path == '/api/logs/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            offset = 0
            try:
                while True:
                    logs = get_logs(offset)
                    if logs:
                        data = json.dumps(logs, ensure_ascii=False)
                        self.wfile.write(f"data: {data}\n\n".encode())
                        self.wfile.flush()
                        offset += len(logs)
                    time.sleep(1)
            except Exception:
                pass

        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        path = self.path.split('?')[0]
        if path == '/api/wifi/hotspot':
            try:
                from modules import wifi
                self._json(wifi.stop_hotspot())
            except Exception as e:
                self._json({"ok": False, "error": str(e)})
        elif path.startswith('/api/scan/'):
            scan_id = path.split('/')[3]
            scan_dir = os.path.join(DB_DIR, scan_id)
            if os.path.isdir(scan_dir):
                import shutil
                shutil.rmtree(scan_dir)
                self._json({"ok": True})
            else:
                self._json({"ok": False, "error": "not found"})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = self.path.split('?')[0]
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if path == '/api/wifi/connect':
            try:
                from modules import wifi
                self._json(wifi.connect(body.get('ssid', ''), body.get('password') or None))
            except Exception as e:
                self._json({"ok": False, "error": str(e)})

        elif path == '/api/wifi/hotspot':
            try:
                from modules import wifi
                s = load_settings()
                ssid = s.get('wifi_ap_ssid') or 'Scanner-AP'
                pw = s.get('wifi_ap_password') or 'scanner123'
                self._json(wifi.start_hotspot(ssid, pw))
            except Exception as e:
                self._json({"ok": False, "error": str(e)})

        elif path == '/api/chat':
            messages = body.get('messages', [])
            question = messages[-1]['content'] if messages else ""
            image_path = None
            scan_id = body.get('scan_id')
            if scan_id:
                img = os.path.join(DB_DIR, scan_id, "shot.jpg")
                if os.path.exists(img):
                    image_path = img
            answer = ask_llm(question, image_path)
            self._json({"answer": answer})

        elif path == '/api/settings':
            current = load_settings()
            for k in ('model', 'gpt_prompt', 'max_tokens', 'language'):
                if k in body:
                    current[k] = body[k]
                    if k == 'language':
                        print(f"[Web UI] Language changed: {body[k]}")
                    elif k == 'model':
                        print(f"[Web UI] Model changed: {body[k]}")
            save_settings(current)
            self._json({"ok": True})

        else:
            self.send_response(404)
            self.end_headers()

    def _html(self, content):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(content.encode())

    def _json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def start_web_ui(port=8080):
    def _run():
        server = ThreadedHTTPServer(("0.0.0.0", port), Handler)
        print(f"Web UI: http://0.0.0.0:{port}")
        server.serve_forever()
    t = threading.Thread(target=_run, daemon=True)
    t.start()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = ThreadedHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"Web UI: http://0.0.0.0:{args.port}")
    print("Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()