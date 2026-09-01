from __future__ import annotations

import asyncio
import cgi
import hashlib
import html
import io
import json
import os
import re
from datetime import datetime
from pathlib import Path
import secrets
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from .engine import ReviewEngine
from .models import ReviewJob
from .provider import FakeNotebookProvider, NotebookLMPyProvider
from .subjects import SUBJECT_LABELS, cleanup_subject_source, discover_question_files, resolve_subject
from . import sessions as _sessions_mod

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
SERVER_PID_PATH = ROOT / "work" / "server.pid"
BRAND_LOGO_PATH = ROOT / "assets" / "OGM_logo_beyaz_yatay.png"
PILOT_BUILD = "0.6.47-multiuser"
FAKE_MODE = os.environ.get("PILOT_FAKE") == "1"
# Legacy single-user globals kept for local / FAKE_MODE compatibility
_global_provider = FakeNotebookProvider() if FAKE_MODE else None
_global_connected = FAKE_MODE
# Per-session jobs are stored inside each _sessions_mod._Session object.
# The legacy global jobs dict below is only used in FAKE_MODE / local mode.
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
activity_lock = threading.Lock()
last_browser_activity = 0.0
MIME_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "md": "text/markdown; charset=utf-8",
    "json": "application/json; charset=utf-8",
}


PAGE_STYLE = """
<style>
:root {
  color-scheme: light;
  --ink: #17365d;
  --ink-soft: #294b70;
  --muted: #666666;
  --brand: #215e99;
  --brand-dark: #174a7a;
  --brand-soft: #eaf2f8;
  --brand-line: #bdd7ee;
  --cyan: #45b0e1;
  --orange: #f1a983;
  --peach: #fce4d6;
  --green-soft: #e2f0d9;
  --yellow-soft: #fff2cc;
  --paper: #f2f2f2;
  --surface: #ffffff;
  --line: #d9e2ec;
  --line-strong: #b8c9da;
  --danger: #c00000;
  --warning: #9a6700;
  --success: #276749;
  --shadow: 0 20px 52px rgba(23, 54, 93, .10);
}
* { box-sizing: border-box; }
html { min-height: 100%; background: var(--paper); }
body {
  margin: 0;
  min-height: 100vh;
  color: var(--ink);
  background:
    radial-gradient(circle at 92% 3%, rgba(69, 176, 225, .16), transparent 30rem),
    radial-gradient(circle at -8% 34%, rgba(241, 169, 131, .15), transparent 28rem),
    var(--paper);
  font: 16px/1.55 "Segoe UI Variable", "Segoe UI", Arial, sans-serif;
}
button, input, select, textarea { font: inherit; }
button, .button {
  appearance: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 0;
  border-radius: 12px;
  background: var(--brand);
  color: #fff;
  padding: 11px 17px;
  font-weight: 720;
  line-height: 1.25;
  text-decoration: none;
  cursor: pointer;
  box-shadow: 0 8px 18px rgba(33, 94, 153, .20);
  transition: transform .16s ease, background .16s ease, box-shadow .16s ease;
}
button:hover, .button:hover { background: var(--brand-dark); transform: translateY(-1px); text-decoration: none; }
button:focus-visible, .button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible, summary:focus-visible, .upload-zone:focus-visible {
  outline: 3px solid rgba(69, 176, 225, .32);
  outline-offset: 2px;
}
button:disabled { cursor: not-allowed; background: #a9bbb8; box-shadow: none; transform: none; }
button.secondary, .button.secondary { border: 1px solid var(--brand-line); background: var(--brand-soft); color: var(--brand-dark); box-shadow: none; }
button.secondary:hover, .button.secondary:hover { background: #dbeaf5; }
.button.ghost { border: 1px solid var(--line-strong); background: #fff; color: var(--brand-dark); box-shadow: none; }
.button.ghost:hover { border-color: var(--cyan); background: var(--brand-soft); }
a { color: var(--brand); text-decoration: none; }
a:hover { text-decoration: underline; }
.institution-header { position: relative; color: #fff; background: var(--brand); box-shadow: 0 10px 28px rgba(23, 54, 93, .18); }
.institution-header::after { content: ""; position: absolute; inset: auto 0 0; height: 5px; background: linear-gradient(90deg, var(--orange) 0 62%, var(--cyan) 62% 100%); }
.institution-inner { width: min(1180px, calc(100% - 40px)); min-height: 136px; margin: 0 auto; padding: 18px 0 23px; display: flex; align-items: center; justify-content: space-between; gap: 28px; }
.brand { display: flex; align-items: center; gap: 23px; min-width: 0; }
.brand-logo { width: 270px; height: 94px; object-fit: contain; object-position: left center; flex: 0 0 auto; }
.brand-copy { min-width: 0; padding-left: 23px; border-left: 1px solid rgba(255,255,255,.35); }
.brand-kicker { display: block; margin-bottom: 3px; color: #dbeaf5; font-size: 11px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
.brand h1 { margin: 0; color: #fff; font-size: clamp(22px, 3vw, 29px); line-height: 1.12; letter-spacing: -.025em; }
.brand p { margin: 5px 0 0; color: rgba(255,255,255,.82); font-size: 13px; }
.header-badge { white-space: nowrap; border: 1px solid rgba(255,255,255,.42); color: var(--ink); background: var(--orange); padding: 8px 12px; border-radius: 7px; font-size: 13px; font-weight: 800; box-shadow: 0 6px 15px rgba(23,54,93,.14); }
.app-shell { width: min(1180px, calc(100% - 40px)); margin: 0 auto; padding: 28px 0 52px; }
.card { background: rgba(255,255,255,.97); border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow); padding: 24px; margin: 0 0 18px; }
.connection-card { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 18px 21px; }
.connection-main { display: flex; align-items: center; gap: 14px; min-width: 0; }
.connection-main p { margin: 4px 0 0; color: var(--muted); font-size: 14px; }
.status-pill { display: inline-flex; align-items: center; gap: 8px; padding: 6px 10px; border-radius: 999px; font-size: 13px; font-weight: 760; }
.status-pill.ready { color: var(--success); background: var(--green-soft); }
.status-pill.waiting { color: var(--warning); background: var(--yellow-soft); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; box-shadow: 0 0 0 4px rgba(255,255,255,.6); }
.connection-actions form { margin: 0; display: flex; gap: 9px; }
.workspace { display: grid; grid-template-columns: minmax(0, 1fr) 310px; gap: 20px; align-items: start; }
.primary-card { padding: clamp(24px, 4vw, 34px); }
.eyebrow { margin: 0 0 8px; color: var(--brand); font-size: 12px; font-weight: 820; letter-spacing: .1em; text-transform: uppercase; }
.eyebrow::before { content: ""; display: inline-block; width: 24px; height: 4px; margin: 0 8px 2px 0; border-radius: 1px; background: var(--orange); }
.primary-card h2, .action-card h2 { margin: 0; line-height: 1.2; letter-spacing: -.025em; }
.primary-card > .intro { margin: 10px 0 22px; color: var(--muted); max-width: 680px; }
.upload-zone {
  min-height: 210px; display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; padding: 28px; border: 2px dashed var(--cyan); border-radius: 14px;
  background: linear-gradient(180deg, #ffffff, var(--brand-soft)); cursor: pointer;
  transition: border-color .18s ease, background .18s ease, transform .18s ease;
}
.upload-zone:hover, .upload-zone.dragging { border-color: var(--brand); background: var(--brand-soft); transform: translateY(-1px); }
.upload-zone.has-file { border-style: solid; border-color: var(--brand); background: var(--brand-soft); }
.upload-icon { width: 54px; height: 54px; display: grid; place-items: center; border-radius: 10px; margin-bottom: 13px; color: #fff; background: var(--cyan); font-size: 28px; font-weight: 500; box-shadow: 0 10px 22px rgba(33,94,153,.18); }
.upload-zone strong { font-size: 18px; color: var(--ink); }
.upload-zone .upload-copy { color: var(--muted); margin-top: 5px; font-size: 14px; }
.file-summary { margin-top: 12px; color: var(--brand-dark); font-weight: 720; overflow-wrap: anywhere; }
.sr-only { position: absolute !important; width: 1px !important; height: 1px !important; padding: 0 !important; margin: -1px !important; overflow: hidden !important; clip: rect(0,0,0,0) !important; white-space: nowrap !important; border: 0 !important; }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-top: 22px; }
.field label, .advanced-block > label { display: block; margin: 0 0 7px; color: var(--ink-soft); font-weight: 730; }
input[type="text"], input:not([type]), select, textarea {
  width: 100%; border: 1px solid var(--line-strong); border-radius: 11px; color: var(--ink);
  background: #fff; padding: 11px 12px; transition: border-color .16s ease, box-shadow .16s ease;
}
input:hover, select:hover, textarea:hover { border-color: var(--cyan); }
select { min-height: 48px; }
textarea { min-height: 150px; resize: vertical; }
.help { margin: 7px 0 0; color: var(--muted); font-size: 13px; }
.muted { color: var(--muted); }
.report-mode-choice { margin-top: 12px !important; padding: 12px 13px !important; border: 1px solid var(--brand-line); background: var(--brand-soft); }
.report-mode-choice .help { margin-top: 3px; }
.advanced { margin-top: 22px; border: 1px solid var(--line); border-radius: 12px; background: #f8fbfd; overflow: hidden; }
.advanced > summary { list-style: none; cursor: pointer; padding: 16px 18px; font-weight: 760; color: var(--ink-soft); display: flex; justify-content: space-between; gap: 16px; }
.advanced > summary::-webkit-details-marker { display: none; }
.advanced > summary::after { content: "+"; color: var(--brand); font-size: 22px; font-weight: 500; line-height: 1; }
.advanced[open] > summary::after { content: "−"; }
.advanced[open] > summary { border-bottom: 1px solid var(--line); }
.advanced-content { padding: 20px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.advanced-block { min-width: 0; padding: 18px; border: 1px solid var(--line); border-radius: 14px; background: #fff; }
.advanced-block.full { grid-column: 1 / -1; }
.advanced-block h3 { margin: 0 0 6px; font-size: 16px; }
.advanced-block .help { margin-bottom: 13px; }
.inline-input { display: flex; gap: 8px; }
.inline-input input { min-width: 0; }
.files { max-height: 220px; overflow: auto; margin-top: 13px; padding: 7px; border: 1px solid var(--line); border-radius: 9px; background: #f8fbfd; }
.files label, .check-row { display: flex; align-items: flex-start; gap: 9px; margin: 0; padding: 9px 10px; border-radius: 9px; font-weight: 540; cursor: pointer; }
.files label:hover, .check-row:hover { background: var(--brand-soft); }
.files input, .check-row input { margin-top: 4px; accent-color: var(--brand); }
.action-card { position: sticky; top: 22px; padding: 25px; border-top: 6px solid var(--orange); }
.action-step { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 7px; margin-bottom: 17px; color: #fff; background: var(--cyan); font-weight: 840; }
.action-card p { color: var(--muted); }
.summary-list { list-style: none; margin: 20px 0; padding: 0; border-top: 1px solid var(--line); }
.summary-list li { position: relative; padding: 11px 0 11px 25px; border-bottom: 1px solid var(--line); color: var(--ink-soft); font-size: 14px; }
.summary-list li::before { content: "✓"; position: absolute; left: 1px; color: var(--success); font-weight: 850; }
.review-button { width: 100%; min-height: 52px; display: flex; align-items: center; justify-content: center; gap: 10px; font-size: 16px; }
.review-hint { margin: 11px 0 0 !important; text-align: center; font-size: 12px; }
.notice { margin-top: 12px; padding: 10px 12px; border-radius: 10px; background: #fff6e4; color: var(--warning); font-size: 13px; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.ok { color: #147348; }
.warn { color: var(--warning); }
.error { color: var(--danger); }
.report { white-space: pre-wrap; line-height: 1.65; background: #fff; border: 1px solid var(--line); padding: 22px; border-radius: 14px; }
progress { width: 100%; height: 13px; overflow: hidden; border: 0; border-radius: 999px; accent-color: var(--brand); }
progress::-webkit-progress-bar { background: #e4eeeb; border-radius: 999px; }
progress::-webkit-progress-value { background: linear-gradient(90deg, var(--brand), var(--cyan)); border-radius: 999px; }
.progress-card { padding: clamp(24px, 4vw, 34px); overflow: hidden; }
.progress-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.progress-heading { min-width: 0; }
.progress-state { display: inline-flex; align-items: center; gap: 8px; margin-bottom: 10px; color: var(--brand-dark); font-size: 12px; font-weight: 820; letter-spacing: .08em; text-transform: uppercase; }
.progress-state.success { color: var(--success); }
.progress-state.danger { color: var(--danger); }
.live-dot { width: 9px; height: 9px; border-radius: 50%; background: currentColor; }
.progress-state.active .live-dot { animation: live-pulse 1.5s ease-out infinite; }
@keyframes live-pulse { 0% { box-shadow: 0 0 0 0 rgba(12,116,108,.34); } 70% { box-shadow: 0 0 0 8px rgba(12,116,108,0); } 100% { box-shadow: 0 0 0 0 rgba(12,116,108,0); } }
.progress-heading h2 { margin: 0; font-size: clamp(24px, 4vw, 34px); line-height: 1.15; letter-spacing: -.035em; }
.progress-description { margin: 10px 0 0; max-width: 720px; color: var(--muted); }
.progress-overall { flex: 0 0 112px; min-height: 96px; display: flex; flex-direction: column; align-items: center; justify-content: center; border: 1px solid var(--brand-line); border-radius: 18px; color: var(--brand-dark); background: var(--brand-soft); }
.progress-overall strong { display: block; font-size: 27px; line-height: 1; letter-spacing: -.04em; }
.progress-overall span { margin-top: 7px; color: var(--muted); font-size: 11px; font-weight: 720; text-transform: uppercase; }
.progress-file { display: grid; grid-template-columns: auto minmax(0,1fr); align-items: center; gap: 13px; margin: 24px 0 20px; padding: 13px 15px; border: 1px solid var(--line); border-radius: 10px; background: var(--brand-soft); }
.progress-file-label { padding: 5px 9px; border-radius: 8px; color: var(--brand-dark); background: var(--brand-soft); font-size: 12px; font-weight: 800; white-space: nowrap; }
.progress-file strong { min-width: 0; overflow-wrap: anywhere; }
.phase-track { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 10px; margin: 0 0 22px; }
.phase-item { display: grid; grid-template-columns: 34px minmax(0,1fr); align-items: center; gap: 9px; min-height: 64px; padding: 11px; border: 1px solid var(--line); border-radius: 10px; color: var(--muted); background: #fff; }
.phase-number { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 7px; background: var(--brand-soft); font-size: 13px; font-weight: 820; }
.phase-item strong { color: inherit; font-size: 14px; }
.phase-item.active { border-color: var(--brand-line); color: var(--brand-dark); background: var(--brand-soft); box-shadow: 0 8px 20px rgba(12,116,108,.08); }
.phase-item.active .phase-number { color: #fff; background: var(--cyan); }
.phase-item.done { border-color: #c6dfb8; color: var(--success); background: var(--green-soft); }
.phase-item.done .phase-number { color: #fff; background: var(--success); }
.phase-item.error { border-color: #efcccc; color: var(--danger); background: #fff6f6; }
.phase-item.error .phase-number { color: #fff; background: var(--danger); }
.phase-item.pending { opacity: .72; }
.progress-meter-row, .progress-meta { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.progress-meter-row { margin-bottom: 8px; color: var(--ink-soft); font-size: 13px; }
.progress-meta { margin-top: 11px; color: var(--muted); font-size: 12px; }
.progress-live { display: inline-flex; align-items: center; gap: 7px; }
.progress-live .live-dot { width: 7px; height: 7px; color: var(--brand); }
.progress-details { padding: 0; overflow: hidden; box-shadow: 0 12px 34px rgba(20,56,54,.06); }
.progress-details > summary { list-style: none; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 21px; cursor: pointer; }
.progress-details > summary::-webkit-details-marker { display: none; }
.progress-details > summary strong, .progress-details > summary small { display: block; }
.progress-details > summary small { margin-top: 3px; color: var(--muted); font-size: 12px; font-weight: 500; }
.details-toggle { color: var(--brand-dark); font-size: 13px; font-weight: 760; }
.details-toggle::before { content: "Göster"; }
.progress-details[open] .details-toggle::before { content: "Gizle"; }
.progress-details-body { padding: 0 20px 20px; border-top: 1px solid var(--line); }
.batch-queue { padding: clamp(20px, 3vw, 27px); }
.queue-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 17px; }
.queue-header h3 { margin: 0; font-size: 20px; letter-spacing: -.02em; }
.queue-header p { margin: 5px 0 0; color: var(--muted); font-size: 13px; }
.queue-count { flex: 0 0 auto; padding: 7px 11px; border: 1px solid var(--brand-line); border-radius: 999px; color: var(--brand-dark); background: var(--brand-soft); font-size: 12px; font-weight: 790; }
.queue-list { list-style: none; display: grid; gap: 9px; margin: 0; padding: 0; }
.queue-item { display: grid; grid-template-columns: 40px minmax(0,1fr); gap: 12px; align-items: start; padding: 14px; border: 1px solid var(--line); border-radius: 11px; background: #fff; }
.queue-index { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 8px; color: var(--brand-dark); background: var(--brand-soft); font-size: 13px; font-weight: 820; }
.queue-main { min-width: 0; }
.queue-name-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.queue-name-row strong { min-width: 0; overflow-wrap: anywhere; }
.queue-status { flex: 0 0 auto; padding: 4px 8px; border-radius: 999px; color: var(--muted); background: var(--brand-soft); font-size: 11px; font-weight: 790; white-space: nowrap; }
.queue-detail { margin: 5px 0 0; color: var(--muted); font-size: 12px; }
.queue-item.running { border-color: var(--brand-line); background: var(--brand-soft); box-shadow: 0 8px 20px rgba(12,116,108,.07); }
.queue-item.running .queue-index { color: #fff; background: var(--brand); }
.queue-item.running .queue-status { color: var(--brand-dark); background: #dbeaf5; }
.queue-item.completed { border-color: #c6dfb8; background: var(--green-soft); }
.queue-item.completed .queue-index { color: #fff; background: var(--success); }
.queue-item.completed .queue-status { color: var(--success); background: #f1f8ed; }
.queue-item.error { border-color: #efcccc; background: #fff7f7; }
.queue-item.error .queue-index { color: #fff; background: var(--danger); }
.queue-item.error .queue-status { color: var(--danger); background: #fae2e2; }
.queue-error { margin: 7px 0 0; color: var(--danger); font-size: 12px; overflow-wrap: anywhere; }
.queue-item .report-actions, .queue-item .queue-error-action { grid-column: 2 / -1; margin: 10px 0 0; }
.queue-item .report-actions .button { padding: 8px 12px; border-radius: 10px; font-size: 13px; }
.steps { list-style: none; padding: 0; margin: 16px 0 0; display: grid; grid-template-columns: 1fr; gap: 8px; }
.steps li { display: grid; grid-template-columns: 35px minmax(0,1fr); align-items: center; gap: 11px; border: 1px solid var(--line); border-radius: 9px; padding: 10px 12px; background: #fff; }
.steps li.active { border-color: var(--brand-line); background: var(--brand-soft); }
.steps li.done { border-color: #d2e8db; background: #f3faf6; }
.steps li.skipped { color: var(--muted); background: #f7f9f8; }
.step-index { width: 32px; height: 32px; display: grid; place-items: center; border-radius: 9px; color: var(--muted); background: #e9efed; font-size: 12px; font-weight: 820; }
.steps li.active .step-index { color: #fff; background: var(--brand); }
.steps li.done .step-index { color: #fff; background: var(--success); }
.steps li.skipped .step-index { color: #70817e; background: #e9eeed; }
.step-copy { min-width: 0; }
.step-copy b, .step-copy small { display: block; }
.step-copy small { margin-top: 2px; color: var(--muted); }
.result-banner { margin: 0 0 18px; padding: 14px 16px; border-radius: 13px; font-weight: 740; }
.result-banner.ok { border: 1px solid #c6dfb8; background: var(--green-soft); }
.result-banner.warn { border: 1px solid #eed7a9; background: #fff8e9; }
.status-page-actions { margin-top: 20px; }
.actions, .report-actions, .preview-actions { display: flex; flex-wrap: wrap; gap: 9px; align-items: center; }
.report-actions { margin-top: 15px; }
.actions a, .report-actions a { display: inline-flex; }
.actions a:hover { text-decoration: none; }
.preview-toolbar {
  position: sticky;
  top: 12px;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin: 0 0 14px;
  padding: 12px;
  border: 1px solid rgba(198, 214, 210, .9);
  border-radius: 16px;
  background: rgba(255, 255, 255, .92);
  box-shadow: 0 14px 34px rgba(20, 56, 54, .12);
  backdrop-filter: blur(14px);
}
.preview-card { padding: clamp(20px, 4vw, 32px); }
.preview-heading { margin-bottom: 19px; }
.preview-heading h2 { margin: 0; overflow-wrap: anywhere; line-height: 1.25; letter-spacing: -.02em; }
.preview-heading .help { margin-top: 8px; }
.app-footer { margin-top: 28px; padding: 18px 12px 0; border-top: 4px solid var(--brand); color: var(--muted); font-size: 12px; text-align: center; }
@media (max-width: 860px) {
  .institution-inner { align-items: flex-start; }
  .brand { gap: 16px; }
  .brand-logo { width: 220px; height: 82px; }
  .brand-copy { padding-left: 16px; }
  .brand h1 { font-size: 22px; }
  .workspace { grid-template-columns: 1fr; }
  .action-card { position: static; }
  .connection-card { align-items: flex-start; }
  .advanced-content, .field-grid, .grid { grid-template-columns: 1fr; }
  .phase-track { grid-template-columns: repeat(2, minmax(0,1fr)); }
}
@media (max-width: 580px) {
  .app-shell { width: min(100% - 24px, 1180px); padding-top: 18px; }
  .institution-inner { width: min(100% - 24px, 1180px); align-items: flex-start; flex-direction: column; gap: 13px; padding: 14px 0 19px; }
  .brand { width: 100%; align-items: flex-start; flex-direction: column; gap: 11px; }
  .brand-logo { width: 250px; height: 78px; }
  .brand-copy { width: 100%; padding: 10px 0 0; border-left: 0; border-top: 1px solid rgba(255,255,255,.32); }
  .header-badge { align-self: flex-start; }
  .connection-card { align-items: flex-start; flex-direction: column; }
  .connection-actions, .connection-actions form, .connection-actions button { width: 100%; }
  .inline-input { flex-direction: column; }
  .upload-zone { min-height: 185px; padding: 22px 16px; }
  .card { border-radius: 17px; }
  .report-actions { align-items: stretch; }
  .report-actions .button { flex: 1 1 100%; }
  .preview-toolbar { position: sticky; top: 8px; align-items: stretch; flex-direction: column; }
  .preview-toolbar > .button { width: 100%; }
  .preview-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); width: 100%; }
  .preview-actions .button:last-child { grid-column: 1 / -1; }
  .report { padding: 17px; }
  .progress-head { flex-direction: column; }
  .progress-overall { align-self: stretch; min-height: 76px; flex-basis: auto; }
  .progress-file { grid-template-columns: 1fr; }
  .progress-file-label { justify-self: start; }
  .phase-track { grid-template-columns: 1fr; }
  .progress-meter-row, .progress-meta { align-items: flex-start; flex-direction: column; gap: 5px; }
  .progress-details > summary { align-items: flex-start; }
  .queue-header, .queue-name-row { align-items: flex-start; flex-direction: column; }
  .queue-item { grid-template-columns: 36px minmax(0,1fr); padding: 12px; }
  .queue-index { width: 34px; height: 34px; }
  .queue-item .report-actions { grid-column: 1 / -1; }
  .queue-item .report-actions .button { flex: 1 1 100%; }
}
@media (prefers-reduced-motion: reduce) { .progress-state.active .live-dot { animation: none; } }
</style>
"""

PAGE_SCRIPT = """
<script>
(function () {
  const heartbeat = () => fetch('/heartbeat', {cache: 'no-store'}).catch(() => {});
  heartbeat();
  window.setInterval(heartbeat, 20000);

  document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('question-files');
    const zone = document.getElementById('upload-zone');
    const summary = document.getElementById('file-summary');
    const renderFiles = () => {
      if (!input || !summary || !zone) return;
      const files = Array.from(input.files || []);
      summary.textContent = files.length === 0
        ? 'Henüz dosya seçilmedi'
        : files.length === 1 ? files[0].name : `${files.length} dosya seçildi`;
      zone.classList.toggle('has-file', files.length > 0);
    };
    if (input && zone) {
      input.addEventListener('change', renderFiles);
      zone.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); }
      });
      ['dragenter', 'dragover'].forEach(name => zone.addEventListener(name, event => {
        event.preventDefault(); zone.classList.add('dragging');
      }));
      ['dragleave', 'drop'].forEach(name => zone.addEventListener(name, event => {
        event.preventDefault(); zone.classList.remove('dragging');
      }));
      zone.addEventListener('drop', event => {
        const incoming = Array.from(event.dataTransfer?.files || []).filter(file => /\\.(pdf|docx)$/i.test(file.name));
        if (!incoming.length || typeof DataTransfer === 'undefined') return;
        const transfer = new DataTransfer();
        incoming.forEach(file => transfer.items.add(file));
        input.files = transfer.files;
        renderFiles();
      });
      renderFiles();
    }

    const folderInput = document.getElementById('folder-path');
    const folderButton = document.getElementById('folder-go');
    const openFolder = () => {
      const value = folderInput?.value.trim();
      if (value) window.location.href = window.location.pathname.split('?')[0] + '?folder=' + encodeURIComponent(value);
    };
    folderButton?.addEventListener('click', openFolder);
    folderInput?.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); openFolder(); }
    });

    let statusTimer = null;
    let statusRequestRunning = false;
    const refreshStatus = async () => {
      const current = document.getElementById('status-content');
      const url = current?.dataset.statusUrl;
      if (!current || !url) {
        if (statusTimer) window.clearInterval(statusTimer);
        statusTimer = null;
        return;
      }
      if (statusRequestRunning || document.hidden) return;
      statusRequestRunning = true;
      try {
        const response = await fetch(url, {cache: 'no-store', headers: {'X-Status-Fragment': '1'}});
        if (!response.ok) return;
        const template = document.createElement('template');
        template.innerHTML = (await response.text()).trim();
        const fresh = template.content.querySelector('#status-content');
        if (!fresh || fresh.dataset.statusRevision === current.dataset.statusRevision) return;

        const openDetails = new Set(Array.from(current.querySelectorAll('details[open][data-preserve-id]')).map(item => item.dataset.preserveId));
        const focused = current.contains(document.activeElement) ? document.activeElement?.dataset.focusKey : '';
        const scrollX = window.scrollX;
        const scrollY = window.scrollY;
        current.replaceWith(fresh);
        openDetails.forEach(key => {
          const detail = Array.from(fresh.querySelectorAll('details[data-preserve-id]')).find(item => item.dataset.preserveId === key);
          if (detail) detail.open = true;
        });
        if (focused) fresh.querySelector(`[data-focus-key="${focused}"]`)?.focus({preventScroll: true});
        window.scrollTo(scrollX, scrollY);
        if (!fresh.dataset.statusUrl && statusTimer) {
          window.clearInterval(statusTimer);
          statusTimer = null;
        }
      } catch (_) {
        // A temporary local connection interruption is retried automatically.
      } finally {
        statusRequestRunning = false;
      }
    };
    if (document.getElementById('status-content')?.dataset.statusUrl) {
      statusTimer = window.setInterval(refreshStatus, 2000);
      document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshStatus(); });
    }
  });
})();
</script>
"""


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"input_dir": "", "subject_sources": {}}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


def rules_update_label() -> str:
    """Show the date recorded when the remote V7 package was applied."""
    try:
        payload = json.loads((ROOT / "rules" / "version.json").read_text(encoding="utf-8-sig"))
        raw = str(payload.get("updated_at") or "").strip()
        if raw:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return f"V7 güncelleme: {value.astimezone().strftime('%d.%m.%Y')}"
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return "V7 güncelleme tarihi bekleniyor"


def idle_shutdown_seconds() -> int:
    """Return the browser-disconnect timeout; zero disables the watchdog."""
    raw = os.environ.get("PILOT_IDLE_TIMEOUT_SECONDS", "")
    if not raw:
        try:
            raw = str(load_config().get("idle_shutdown_seconds", 300))
        except Exception:
            raw = "300"
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 300
    if value <= 0:
        return 0
    return min(3600, max(30, value))


def touch_browser_activity() -> None:
    global last_browser_activity
    with activity_lock:
        last_browser_activity = time.monotonic()


def has_active_jobs() -> bool:
    with jobs_lock:
        return any(state.get("status") in {"queued", "running"} for state in jobs.values())


def idle_watchdog(server: ThreadingHTTPServer, timeout_seconds: int) -> None:
    """Stop the local server after the browser has disappeared and work is idle."""
    if timeout_seconds <= 0:
        return
    while True:
        time.sleep(5)
        with activity_lock:
            idle_for = time.monotonic() - last_browser_activity
        if idle_for < timeout_seconds or has_active_jobs():
            continue
        print(f"Tarayici baglantisi {timeout_seconds} saniyedir yok; yerel sunucu kapatiliyor.", flush=True)
        server.shutdown()
        return


def safe_error(value: str | None) -> str:
    text = str(value or "Bilinmeyen hata")
    text = re.sub(r"(?i)(SID|PSID|cookie(?: value)?|token)\s*[=:]\s*[^\s,;]+", r"\1=[gizli]", text)
    text = re.sub(r"(?i)[A-Za-z]:\\[^\r\n]*storage_state\.json", "NotebookLM oturum dosyası", text)
    return " ".join(text.split())[:900]


def is_auth_error(value: str | None) -> bool:
    """Identify an expired NotebookLM login without exposing session data."""
    normalized = " ".join(str(value or "").casefold().split())
    return any(marker in normalized for marker in (
        "authentication expired",
        "authentication invalid",
        "_loginredirecterror",
        "run 'notebooklm login'",
        "notebooklm login' to re-authenticate",
    ))


def safe_output(name: str) -> Path | None:
    target = (ROOT / "outputs" / Path(os.path.basename(name))).resolve()
    return target if target.parent == (ROOT / "outputs").resolve() and target.is_file() else None


def stage_pasted_question(text: str, title: str, upload_root: Path) -> Path | None:
    """Create a short-lived Markdown question source without logging its text."""
    content = text.strip()
    if not content:
        return None
    if len(content) > 200_000:
        raise ValueError("Yapıştırılan soru metni en fazla 200.000 karakter olabilir.")
    requested_name = title.strip() or "yapistirilan-soru"
    safe_name = "".join("-" if char in '<>:\"/\\|?*' or ord(char) < 32 else char for char in requested_name)
    safe_name = safe_name.strip(" .-")[:100] or "yapistirilan-soru"
    upload_root.mkdir(parents=True, exist_ok=True)
    destination = upload_root / f"{secrets.token_hex(8)}-{safe_name}.md"
    destination.write_text(content + "\n", encoding="utf-8", newline="\n")
    return destination


class Handler(BaseHTTPRequestHandler):
    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------
    def _session_id_from_cookie(self) -> str | None:
        """Parse pilot_session cookie value from the Cookie header."""
        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith(f"{_sessions_mod.COOKIE_NAME}="):
                return part[len(_sessions_mod.COOKIE_NAME) + 1:]
        return None

    def _get_session(self) -> "_sessions_mod._Session":
        """Return the current user's session, creating one if needed."""
        sid = self._session_id_from_cookie()
        return _sessions_mod.get_or_create(sid, ROOT)

    def _set_session_cookie(self, session: "_sessions_mod._Session") -> None:
        """Emit a Set-Cookie header that binds this response to the session."""
        self.send_header(
            "Set-Cookie",
            f"{_sessions_mod.COOKIE_NAME}={session.session_id}; "
            "Path=/; HttpOnly; SameSite=Lax",
        )

    def _session_provider(self, session: "_sessions_mod._Session"):
        """Return the correct provider for a session (Fake or real per-user)."""
        if FAKE_MODE:
            return _global_provider
        return NotebookLMPyProvider(notebooklm_home=session.notebooklm_home)

    def _session_jobs(self, session: "_sessions_mod._Session") -> dict[str, dict]:
        return session.jobs

    def _session_jobs_lock(self, session: "_sessions_mod._Session") -> threading.Lock:
        return session.jobs_lock

    def _session_output_dir(self, session: "_sessions_mod._Session") -> Path:
        return session.outputs_dir

    def _session_upload_dir(self, session: "_sessions_mod._Session") -> Path:
        return session.uploads_dir

    # ------------------------------------------------------------------
    # Reverse Proxy / URL Prefix helpers
    # ------------------------------------------------------------------
    def _prefix(self) -> str:
        """Return the URL prefix (e.g. '/soru-inceleme') if deployed behind a reverse proxy."""
        # 1. Header from Reverse Proxy (IIS / Nginx)
        fwd_prefix = self.headers.get("X-Forwarded-Prefix", "").strip().rstrip("/")
        if fwd_prefix:
            return fwd_prefix
        # 2. Environment variable
        env_prefix = os.environ.get("PILOT_PREFIX") or os.environ.get("URL_PREFIX", "")
        env_prefix = env_prefix.strip().rstrip("/")
        if env_prefix:
            return env_prefix if env_prefix.startswith("/") else f"/{env_prefix}"
        # 3. Path sniffing (if reverse proxy forwards the path without stripping)
        raw_path = self.path.split("?")[0]
        for candidate in ("/soru-inceleme", "/soru-kontrol", "/sorukontrol", "/soruinceleme"):
            if raw_path == candidate or raw_path.startswith(candidate + "/"):
                return candidate
        return ""

    def _url(self, path: str = "") -> str:
        """Generate a prefix-aware relative or absolute URL."""
        prefix = self._prefix()
        if not path or path == "/":
            return f"{prefix}/" if prefix else "/"
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{prefix}{path}"

    def _clean_path(self, raw_path: str) -> str:
        """Strip the URL prefix from the incoming request path."""
        prefix = self._prefix()
        if prefix and (raw_path == prefix or raw_path.startswith(prefix + "/")):
            cleaned = raw_path[len(prefix):]
            return cleaned if cleaned.startswith("/") else f"/{cleaned}"
        return raw_path

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------
    def _page(self, body: str, title: str = "Bağlam Temelli Çoktan Seçmeli Soru Kontrol Modülü", *, session: "_sessions_mod._Session | None" = None) -> None:
        update_label = html.escape(rules_update_label())
        logo_url = self._url("/assets/ogm-logo.png")
        home_url = self._url("/")
        content = f"""<!doctype html><html lang='tr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><meta name='theme-color' content='#215e99'><title>{html.escape(title)}</title>{PAGE_STYLE}{PAGE_SCRIPT}</head><body><header class='institution-header'><div class='institution-inner'><div class='brand'><a href='{home_url}' style='text-decoration:none;display:flex;align-items:center;gap:18px'><img class='brand-logo' src='{logo_url}' alt='Ortaöğretim Genel Müdürlüğü'><div class='brand-copy'><span class='brand-kicker'>Türkiye Yüzyılı Maarif Modeli</span><h1>Bağlam Temelli Çoktan Seçmeli Soru Kontrol Modülü</h1><p>Öğretim Materyalleri ve İçerik Geliştirme Daire Başkanlığı</p></div></a></div><span class='header-badge'>{update_label}</span></div></header><div class='app-shell'><main>{body}</main><footer class='app-footer'>Öğretim Materyalleri ve İçerik Geliştirme Daire Başkanlığı</footer></div></body></html>"""
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if session:
            self._set_session_cookie(session)
        self.end_headers()
        self.wfile.write(data)

    def _fragment(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, target: str, *, session: "_sessions_mod._Session | None" = None) -> None:
        self.send_response(303)
        # Apply prefix to redirect target if relative
        final_target = target if target.startswith(("http://", "https://")) else self._url(target)
        self.send_header("Location", final_target)
        self.send_header("Content-Length", "0")
        if session:
            self._set_session_cookie(session)
        self.end_headers()



    def do_GET(self) -> None:
        touch_browser_activity()
        sess = self._get_session()
        parsed = urlparse(self.path)
        path = self._clean_path(parsed.path)
        query = parse_qs(parsed.query)
        if path == "/heartbeat":
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self._set_session_cookie(sess)
            self.end_headers()
            return
        if path == "/assets/ogm-logo.png": return self._brand_logo()
        if path == "/status": return self._status_page(query.get("job", [""])[0], session=sess)
        if path == "/status-fragment": return self._status_page(query.get("job", [""])[0], fragment=True, session=sess)
        if path == "/download": return self._download(query.get("name", [""])[0], session=sess)
        if path == "/bundle": return self._bundle(query.get("job", [""])[0], query.get("kind", [""])[0], session=sess)
        if path == "/preview": return self._preview(query.get("job", [""])[0], query.get("index", [""])[0], session=sess)
        self._home(query.get("folder", [""])[0], session=sess)


    def _brand_logo(self) -> None:
        if not BRAND_LOGO_PATH.is_file():
            self.send_error(404)
            return
        data = BRAND_LOGO_PATH.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _home(self, folder_value: str, *, session: "_sessions_mod._Session") -> None:
        connected = session.connected
        config = load_config()
        folder = folder_value or str(config.get("input_dir", ""))
        files: list[Path] = []
        folder_error = ""
        if folder:
            try: files = discover_question_files(Path(folder))
            except Exception as exc: folder_error = safe_error(str(exc))

        checkboxes = "".join(f"<label><input type='checkbox' name='selected_paths' value='{html.escape(str(path), quote=True)}'><span>{html.escape(path.name)}</span></label>" for path in files) or "<p class='help'>Henüz klasör taranmadı veya uygun dosya bulunamadı.</p>"
        subject_options = "<option value='auto'>Otomatik (dosya adı + içerik)</option>" + "".join(f"<option value='{key}'>{label}</option>" for key, label in SUBJECT_LABELS.items())
        post_url = self._url("")
        if connected:
            connection = "<span class='status-pill ready'><span class='status-dot'></span>Soru Kontrol Motoru Hazır</span><p>Soru dosyanızı yükleyerek hemen değerlendirmeye başlayabilirsiniz.</p>"
            connection_actions = f"<form method='post' action='{post_url}'><button class='secondary' name='action' value='disconnect' title='Gerekirse oturumu sıfırlayın'>Oturumu Sıfırla</button></form>"
            review_hint = "Dosyanız sıraya alınarak rapor hazırlanır."

        else:
            connection = "<span class='status-pill waiting'><span class='status-dot'></span>Giriş gerekli</span><p>Değerlendirme başlatmak için Gmail hesabınızı bağlayın veya oturum dosyanızı yükleyin.</p>"
            connection_actions = f"""
            <form method='post' action='{post_url}'><button name='action' value='connect'>Gmail ile otomatik bağlan</button></form>
            <details class='auth-manual-details' style='margin-top:10px;'>
              <summary style='cursor:pointer;color:#215e99;font-weight:600;font-size:0.9rem;'>📁 Oturum Dosyası (.json) Yükle veya Yapıştır</summary>
              <div style='background:#f8fafc;padding:12px;border-radius:6px;margin-top:8px;border:1px solid #e2e8f0;'>
                <p class='help' style='margin:0 0 8px 0;font-size:0.82rem;'>Sunucuda doğrudan bağlanmak için <code>storage_state.json</code> dosyanızı seçin:</p>
                <form method='post' action='{post_url}' enctype='multipart/form-data' style='display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap;'>
                  <input type='file' name='session_file' accept='.json' required style='font-size:0.85rem;'>
                  <button name='action' value='upload_session' style='padding:6px 12px;font-size:0.85rem;'>Yükle ve Bağlan</button>
                </form>
                <form method='post' action='{post_url}'>
                  <textarea name='session_json' rows='2' placeholder='Veya JSON içeriğini buraya yapıştırın...' style='width:100%;font-size:0.8rem;padding:6px;border-radius:4px;border:1px solid #cbd5e1;box-sizing:border-box;'></textarea>
                  <button name='action' value='paste_session' class='secondary' style='margin-top:4px;padding:4px 10px;font-size:0.8rem;'>Metni Kaydet</button>
                </form>
              </div>
            </details>
            """
            review_hint = "Önce üst bölümden Gmail ile giriş yapın veya oturum yükleyin."



        folder_error_html = f"<p class='error'>{html.escape(folder_error)}</p>" if folder_error else ""
        advanced_open = " open" if folder or folder_error else ""
        body = f"""
        <section class='card connection-card'>
          <div class='connection-main'><div>{connection}</div></div>
          <div class='connection-actions'>{connection_actions}</div>
        </section>
        <form id='review-form' method='post' action='{post_url}' enctype='multipart/form-data'>
          <div class='workspace'>
            <section class='card primary-card'>

              <p class='eyebrow'>Yeni değerlendirme</p>
              <h2>1. Soru dosyanızı yükleyin</h2>
              <p class='intro'>PDF veya Word dosyanızı seçin. Tek dosyalık günlük kullanım için bu alan yeterlidir.</p>
              <label id='upload-zone' class='upload-zone' for='question-files' tabindex='0'>
                <span class='upload-icon'>↑</span>
                <strong>Dosyayı buraya bırakın veya seçin</strong>
                <span class='upload-copy'>PDF ve DOCX dosyaları desteklenir</span>
                <span id='file-summary' class='file-summary'>Henüz dosya seçilmedi</span>
              </label>
              <input id='question-files' class='sr-only' type='file' name='uploads' accept='.pdf,.docx' multiple>

              <div class='field-grid'>
                <div class='field'>
                  <label for='subject'>2. Ders</label>
                  <select id='subject' name='subject'>{subject_options}</select>
                  <p class='help'>Emin değilseniz “Otomatik” seçeneğini bırakın.</p>
                </div>
                <div class='field'>
                  <label>Rapor çıktısı</label>
                  <input value='Word ve PDF birlikte hazırlanır' readonly>
                  <input type='hidden' name='report_mode' value='issues'>
                  <p class='help'><strong>V7 sorun raporu:</strong> Bütün uygulanabilir ölçütler iç değerlendirmede kontrol edilir; raporda yalnız ❌ Uygun Değil, ⚠️ Düzeltilmeli ve ⚪ İncelenemedi bulguları gösterilir. ✅ Uygun ve ⚪ Uygulanamaz ölçütler yazılmaz.</p>
                </div>
              </div>

              <details class='advanced'{advanced_open}>
                <summary>Toplu işlem ve diğer giriş yöntemleri</summary>
                <div class='advanced-content'>
                  <div class='advanced-block'>
                    <h3>Klasörden dosya seçimi</h3>
                    <p class='help'>Bir klasördeki PDF ve Word dosyalarını listeleyin.</p>
                    <div class='inline-input'>
                      <input id='folder-path' value='{html.escape(folder, quote=True)}' placeholder='D:\\soru-belgeleri'>
                      <button id='folder-go' class='secondary' type='button'>Listele</button>
                    </div>
                    {folder_error_html}
                    <div class='files'>{checkboxes}</div>
                  </div>
                  <div class='advanced-block'>
                    <h3>Soru metnini yapıştırın</h3>
                    <p class='help'>Dosya yerine doğrudan soru metniyle de çalışabilirsiniz.</p>
                    <textarea name='question_text' maxlength='200000' placeholder='Soru metnini buraya yapıştırın'></textarea>
                    <label for='question-title'>Rapor adı <span class='muted'>(isteğe bağlı)</span></label>
                    <input id='question-title' name='question_title' placeholder='Örn. BİY.9.1.5 soru seti'>
                  </div>
                  <div class='advanced-block full'>
                    <h3>Gelişmiş değerlendirme ayarları</h3>
                    <div class='field-grid'>
                      <div class='field'>
                        <label for='subject-file'>Özel ders kaynağı <span class='muted'>(isteğe bağlı)</span></label>
                        <input id='subject-file' name='subject_file' placeholder='D:\\kaynaklar\\biyoloji.pdf'>
                        <p class='help'>Yalnızca farklı bir ders kaynağı kullanmanız gerekiyorsa belirtin.</p>
                      </div>
                      <div class='field'>
                        <label class='check-row'><input type='checkbox' name='force_refresh' value='1'><span><strong>Yeniden değerlendir</strong><br><span class='help'>Mevcut raporu kullanmadan yeni değerlendirme oluşturur.</span></span></label>
                      </div>
                    </div>
                  </div>
                </div>
              </details>
            </section>

            <aside class='card action-card'>
              <div class='action-step'>3</div>
              <h2>Değerlendirmeyi başlatın</h2>
              <p>Seçtiğiniz soru güncel kontrol ölçütlerine göre incelenir.</p>
              <ul class='summary-list'>
                <li>Güncel V7 ölçütleri</li>
                <li>Derse göre içerik kontrolü</li>
                <li>Word ve PDF raporu</li>
              </ul>
              <button class='review-button' name='action' value='review' {'disabled' if not connected else ''}>Değerlendirmeyi başlat <span>→</span></button>
              <p class='review-hint'>{html.escape(review_hint)}</p>
            </aside>
          </div>
        </form>"""
        self._page(body, session=session)

    def _status_page(self, job_id: str, fragment: bool = False, *, session: "_sessions_mod._Session") -> None:
        sess_jobs = self._session_jobs(session)
        sess_lock = self._session_jobs_lock(session)
        with sess_lock:
            state = sess_jobs.get(job_id)
            state = dict(state) if state else None
        if not state:
            content = "<div id='status-content'><div class='card'><p>İş bulunamadı.</p><a href='/'>Geri</a></div></div>"
            return self._fragment(content) if fragment else self._page(content, session=session)
        view = progress_snapshot(state)
        step_rows = []

        status_symbols = {"done": "✓", "active": "•", "skipped": "–"}
        status_labels = {"done": "Tamamlandı", "active": "Devam ediyor", "skipped": "Çalıştırılmadı", "pending": "Bekliyor"}
        for number, item in enumerate(state.get("steps", []), 1):
            status = item.get("status", "pending")
            symbol = status_symbols.get(status, str(number))
            step_rows.append(
                f"<li class='{html.escape(status)}'>"
                f"<span class='step-index' aria-label='{html.escape(status_labels.get(status, status))}'>{html.escape(symbol)}</span>"
                f"<span class='step-copy'><b>{html.escape(item['label'])}</b><small>{html.escape(item['detail'])}</small></span></li>"
            )
        phases = "".join(
            f"<div class='phase-item {phase['status']}'{' aria-current=\'step\'' if phase['status'] == 'active' else ''}>"
            f"<span class='phase-number'>{'✓' if phase['status'] == 'done' else phase['number']}</span>"
            f"<strong>{html.escape(phase['label'])}</strong></div>"
            for phase in view["phases"]
        )
        body = (
            "<section class='card progress-card' aria-live='polite'>"
            "<div class='progress-head'><div class='progress-heading'>"
            f"<div class='progress-state {view['tone']}'><span class='live-dot'></span>{html.escape(view['eyebrow'])}</div>"
            f"<h2>{html.escape(view['title'])}</h2><p class='progress-description'>{html.escape(view['description'])}</p>"
            "</div>"
            f"<div class='progress-overall' aria-label='Genel ilerleme yüzde {view['percent']}'><strong>%{view['percent']}</strong><span>genel ilerleme</span></div></div>"
            "<div class='progress-file'>"
            f"<span class='progress-file-label'>Dosya {view['file_number']}/{view['total']}</span>"
            f"<strong>{html.escape(view['file_name'])}</strong></div>"
            f"<div class='phase-track' aria-label='Ana işlem aşamaları'>{phases}</div>"
            "<div class='progress-meter-row'><span>Değerlendirme ilerlemesi</span>"
            f"<strong>Adım {view['step_number']}/{view['step_total']}</strong></div>"
            f"<progress max='100' value='{view['percent']}' aria-label='Yüzde {view['percent']} tamamlandı'></progress>"
            "<div class='progress-meta'>"
            f"<span>{view['completed_files']}/{view['total']} dosya tamamlandı</span>"
            f"<span class='progress-live'><span class='live-dot'></span>{html.escape(view['refresh_text'])}</span>"
            "</div></section>"
        )
        batch_queue = state.get("queue") or []
        if len(batch_queue) > 1:
            body += self._batch_queue(job_id, state, view)
        body += (
            "<details class='card progress-details' data-preserve-id='progress-steps'><summary data-focus-key='progress-steps-summary'><span><strong>Tüm işlem adımları</strong>"
            f"<small>Şu anda {view['step_number']}. adım gösteriliyor.</small></span><span class='details-toggle' aria-hidden='true'></span></summary>"
            f"<div class='progress-details-body'><ol class='steps'>{''.join(step_rows)}</ol></div></details>"
        )
        if state["status"] not in {"queued", "running"}:
            complete = state["status"] == "completed"
            body += f"<div class='result-banner {'ok' if complete else 'warn'}'>{'Tüm raporlar hazır.' if complete else 'İş tamamlandı; bazı dosyalarda hata oluştu.'}</div>"
            ok_results = [item for item in state["results"] if not item.get("error")]
            if len(ok_results) > 1:
                bundle_pdf = self._url(f"/bundle?job={quote(job_id)}&kind=pdf")
                bundle_docx = self._url(f"/bundle?job={quote(job_id)}&kind=docx")
                body += (
                    "<nav class='actions' aria-label='Toplu rapor indirme'>"
                    f"<a class='button' href='{bundle_pdf}'>PDF raporlarını ZIP indir</a>"
                    f"<a class='button secondary' href='{bundle_docx}'>Word raporlarını ZIP indir</a>"
                    "</nav>"
                )
            if len(batch_queue) <= 1:
                post_action_url = self._url("")
                for index, item in enumerate(state["results"]):
                    cache_note = " • doğrulanmış önbellekten" if item.get("cached") else ""
                    mode_note = " • V7 sorun raporu"
                    body += f"<div class='card'><b>{html.escape(item['name'])}</b><br><small>Ders: {html.escape(item.get('subject',''))}{mode_note}{cache_note}</small><br>"
                    if item.get("error"):
                        body += f"<span class='error'>Hata: {html.escape(item['error'])}</span>"
                        if item.get("raw"):
                            raw_url = self._url(f"/download?name={quote(Path(item['raw']).name)}")
                            body += f"<p><a class='button secondary' href='{raw_url}'>Korunan NotebookLM yanıtını indir</a></p>"
                        if is_auth_error(item["error"]):
                            body += f"<p class='warn'>NotebookLM Gmail oturumu geçersiz veya süresi dolmuş. Aşağıdaki düğmeyle yeniden giriş yapın.</p><form method='post' action='{post_action_url}'><button name='action' value='reconnect'>Gmail girişini yenile</button></form>"
                    else:
                        body += self._report_actions(job_id, index, item)
                    body += "</div>"
        frag_url = self._url(f"/status-fragment?job={quote(job_id)}")
        live_attribute = f" data-status-url='{frag_url}'" if state["status"] in {"queued", "running"} else ""
        new_rev_url = self._url("/")
        content = (
            f"<div id='status-content' data-status-revision='{status_revision(state)}'{live_attribute}>"
            f"{body}<nav class='status-page-actions'><a class='button ghost' href='{new_rev_url}'>Yeni değerlendirme başlat</a></nav></div>"
        )
        return self._fragment(content) if fragment else self._page(content, session=session)

    def _batch_queue(self, job_id: str, state: dict, view: dict) -> str:
        queue = state.get("queue") or []
        ready = sum(item.get("status") == "completed" for item in queue)
        errors = sum(item.get("status") == "error" for item in queue)
        count_text = f"{ready}/{len(queue)} rapor hazır"
        if errors:
            count_text += f" • {errors} hata"
        status_labels = {"pending": "Sırada", "running": "İşleniyor", "completed": "Rapor hazır", "error": "Hata"}
        rows = []
        is_finished = state.get("status") not in {"queued", "running"}
        post_action_url = self._url("")
        for index, item in enumerate(queue):
            status = item.get("status", "pending")
            if status == "running":
                detail = view["title"]
            elif status == "completed":
                detail = f"Ders: {item.get('subject') or 'Belirlenmedi'}"
                detail += " • V7 sorun raporu"
                if item.get("cached"):
                    detail += " • doğrulanmış önbellekten"
            elif status == "error":
                detail = "Rapor hazırlanamadı"
            else:
                detail = "Değerlendirme sırası bekleniyor"
            row = (
                f"<li class='queue-item {html.escape(status)}'><span class='queue-index'>{index + 1}</span>"
                "<div class='queue-main'><div class='queue-name-row'>"
                f"<strong>{html.escape(str(item.get('name') or f'Dosya {index + 1}'))}</strong>"
                f"<span class='queue-status'>{html.escape(status_labels.get(status, status))}</span></div>"
                f"<p class='queue-detail'>{html.escape(detail)}</p>"
            )
            if status == "error" and item.get("error"):
                row += f"<p class='queue-error'>Hata: {html.escape(str(item['error']))}</p>"
                if item.get("raw"):
                    raw_url = self._url(f"/download?name={quote(Path(str(item['raw'])).name)}")
                    row += f"<p><a class='button secondary' href='{raw_url}'>Korunan NotebookLM yanıtını indir</a></p>"
            row += "</div>"
            if status == "completed" and item.get("pdf") and item.get("docx"):
                row += self._report_actions(job_id, index, item, new_tab=True)
            elif status == "error" and is_finished and is_auth_error(str(item.get("error") or "")):
                row += f"<form class='queue-error-action' method='post' action='{post_action_url}'><button name='action' value='reconnect'>Gmail girişini yenile</button></form>"
            rows.append(row + "</li>")

        return (
            "<section class='card batch-queue'><header class='queue-header'><div>"
            "<h3>Dosya kuyruğu</h3><p>Biten raporu seri tamamlanmadan görüntüleyebilir veya indirebilirsiniz.</p>"
            f"</div><span class='queue-count'>{html.escape(count_text)}</span></header>"
            f"<ol class='queue-list'>{''.join(rows)}</ol></section>"
        )

    def _report_actions(self, job_id: str, index: int, item: dict, new_tab: bool = False) -> str:
        preview_url = self._url(f"/preview?job={quote(job_id)}&index={index}")
        pdf_url = self._url(f"/download?name={quote(Path(item['pdf']).name)}")
        docx_url = self._url(f"/download?name={quote(Path(item['docx']).name)}")
        preview_target = " target='_blank' rel='noopener'" if new_tab else ""
        return (
            "<nav class='report-actions' aria-label='Rapor işlemleri'>"
            f"<a class='button' href='{preview_url}'{preview_target}>Raporu görüntüle</a>"
            f"<a class='button secondary' href='{pdf_url}'>PDF indir</a>"
            f"<a class='button secondary' href='{docx_url}'>Word indir</a>"
            "</nav>"
        )

    def _preview(self, job_id: str, index_value: str, *, session: "_sessions_mod._Session") -> None:
        sess_jobs = self._session_jobs(session)
        sess_lock = self._session_jobs_lock(session)
        try:
            index = int(index_value)
            with sess_lock:
                item = sess_jobs[job_id]["results"][index]
            content = Path(item["md"]).read_text(encoding="utf-8")
        except Exception:
            return self._page("<div class='card'><p>Rapor önizlemesi bulunamadı.</p></div>", session=session)
        status_url = self._url(f"/status?job={quote(job_id)}")
        pdf_url = self._url(f"/download?name={quote(Path(item['pdf']).name)}")
        docx_url = self._url(f"/download?name={quote(Path(item['docx']).name)}")
        new_url = self._url("/")
        subject = html.escape(str(item.get("subject") or "Belirlenmedi"))
        name = html.escape(str(item.get("name") or "Rapor"))
        body = (
            "<nav class='preview-toolbar' aria-label='Rapor gezinme'>"
            f"<a class='button secondary' href='{status_url}'>← Sonuçlara dön</a>"
            "<div class='preview-actions'>"
            f"<a class='button' href='{pdf_url}'>PDF indir</a>"
            f"<a class='button secondary' href='{docx_url}'>Word indir</a>"
            f"<a class='button ghost' href='{new_url}'>Yeni değerlendirme</a>"
            "</div></nav>"
            "<section class='card preview-card'>"
            "<header class='preview-heading'><p class='eyebrow'>Rapor önizleme</p>"

            f"<h2>{name}</h2><p class='help'>Ders: {subject}</p></header>"
            f"<div class='report' role='document'>{html.escape(content)}</div>"
            "</section>"
        )
        self._page(body, title=f"Rapor önizleme - {item.get('name') or 'Rapor'}", session=session)

    def _download(self, name: str, *, session: "_sessions_mod._Session") -> None:
        # Serve only from this user's outputs directory for isolation
        safe_name = os.path.basename(name)
        target = (session.outputs_dir / safe_name).resolve()
        if not target.parent == session.outputs_dir.resolve() or not target.is_file():
            return self._page("<div class='card'><p>Dosya bulunamadı.</p></div>", session=session)
        data = target.read_bytes()
        suffix = target.suffix.lower().lstrip(".")
        self.send_response(200)
        self.send_header("Content-Type", MIME_TYPES.get(suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(target.name)}")
        self._set_session_cookie(session)
        self.end_headers()
        self.wfile.write(data)

    def _bundle(self, job_id: str, kind: str, *, session: "_sessions_mod._Session") -> None:
        sess_jobs = self._session_jobs(session)
        sess_lock = self._session_jobs_lock(session)
        with sess_lock:
            result_items = list(sess_jobs.get(job_id, {}).get("results", []))
        keys = {"docx": ["docx"], "pdf": ["pdf"], "all": ["docx", "pdf"]}.get(kind)
        if not keys:
            return self._page("<div class='card'><p>Geçersiz paket isteği.</p></div>", session=session)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in result_items:
                for key in keys:
                    if item.get(key):
                        path = Path(item[key])
                        if path.is_file():
                            archive.write(path, path.name)
        data = buffer.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f"attachment; filename=soru-kontrol-{kind}-raporlari.zip")
        self._set_session_cookie(session)
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        touch_browser_activity()
        sess = self._get_session()
        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", "0"))
        uploads: list[Path] = []
        staged_names: dict[Path, str] = {}
        review_jobs: list[ReviewJob] = []
        try:
            form = None
            question_text = question_title = ""
            report_mode = "issues"
            if content_type.startswith("multipart/form-data"):
                form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_LENGTH": str(length)})
                action = form.getfirst("action", ""); requested_subject = form.getfirst("subject", "auto"); subject_file = form.getfirst("subject_file", ""); selected_paths = [Path(value) for value in form.getlist("selected_paths")]
                question_text = form.getfirst("question_text", "")
                question_title = form.getfirst("question_title", "")
                report_mode = "issues" if form.getfirst("report_mode", "") == "issues" else "full"
            else:
                values = parse_qs(self.rfile.read(length).decode("utf-8"))
                action = values.get("action", [""])[0]
                requested_subject, subject_file, selected_paths = "auto", "", []

            # --- Per-session provider ---
            sess_provider = self._session_provider(sess)

            home_url = self._url("/")
            if action == "upload_session" and form is not None:
                file_item = form["session_file"] if "session_file" in form else None
                raw_bytes = b""
                if getattr(file_item, "file", None):
                    raw_bytes = file_item.file.read()
                if not raw_bytes:
                    raise ValueError("Lütfen geçerli bir storage_state.json dosyası seçin.")
                sess_provider.import_storage_state(raw_bytes)
                sess.connected = True
                return self._page(f"<div class='card'><p class='ok'>✓ Oturum başarıyla yüklendi ve bağlandı!</p><a href='{home_url}'>Devam et</a></div>", session=sess)

            if action == "paste_session":
                session_json = (form.getfirst("session_json", "") if form else values.get("session_json", [""])[0]).strip()
                if not session_json:
                    raise ValueError("Lütfen JSON metnini girin.")
                sess_provider.import_storage_state(session_json)
                sess.connected = True
                return self._page(f"<div class='card'><p class='ok'>✓ Oturum başarıyla kaydedildi ve bağlandı!</p><a href='{home_url}'>Devam et</a></div>", session=sess)

            if action in {"connect", "reconnect"}:
                asyncio.run(sess_provider.login("chrome", force=action == "reconnect"))
                sess.connected = True
                return self._page(f"<div class='card'><p class='ok'>Gmail oturumu hazır.</p><a href='{home_url}'>Devam et</a></div>", session=sess)
            if action == "firefox":
                asyncio.run(sess_provider.login("firefox"))
                sess.connected = True
                return self._page(f"<div class='card'><p class='ok'>Firefox oturumu hazır.</p><a href='{home_url}'>Devam et</a></div>", session=sess)
            if action == "disconnect":
                asyncio.run(sess_provider.disconnect(clear_auth=True))
                sess.connected = False
                return self._page(f"<div class='card'><p>Bağlantı kaldırıldı ve NotebookLM oturumu temizlendi.</p><a href='{home_url}'>Geri</a></div>", session=sess)
            if action != "review":
                return self._page(f"<div class='card'><p>Bilinmeyen işlem.</p><a href='{home_url}'>Geri</a></div>", session=sess)
            if not sess.connected:
                return self._page(f"<div class='card'><p class='warn'>Önce NotebookLM'ye bağlanın.</p><a href='{home_url}'>Geri</a></div>", session=sess)



            upload_root = self._session_upload_dir(sess)
            if form is not None:
                items = form["uploads"] if "uploads" in form else []
                if not isinstance(items, list): items = [items]
                for item in items:
                    name = os.path.basename(item.filename or "")
                    if name.lower().endswith((".pdf", ".docx")) and item.file:
                        destination = upload_root / f"{secrets.token_hex(8)}-{name}"
                        upload_root.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(item.file.read())
                        uploads.append(destination)
                        staged_names[destination.resolve()] = name
                pasted = stage_pasted_question(question_text, question_title, upload_root)
                if pasted is not None:
                    uploads.append(pasted)
                    staged_names[pasted.resolve()] = (question_title.strip() or "yapistirilan-soru") + ".md"

            paths: list[Path] = []; seen = set()
            for path in [*selected_paths, *uploads]:
                resolved = path.resolve()
                suffix = resolved.suffix.lower()
                is_staged_text = resolved in staged_names and suffix == ".md"
                if resolved not in seen and resolved.is_file() and (suffix in {".pdf", ".docx"} or is_staged_text):
                    seen.add(resolved); paths.append(resolved)
            if not paths:
                raise ValueError("En az bir geçerli PDF, DOCX veya yapıştırılmış soru metni girin.")

            config = load_config()
            source_override = Path(subject_file) if subject_file else None
            uploaded_set = {item.resolve() for item in uploads}
            try:
                subject_timeout = int((config.get("rules_update") or {}).get("timeout_seconds", 20))
            except (TypeError, ValueError):
                subject_timeout = 20
            subject_timeout = min(120, max(1, subject_timeout))
            force_refresh = bool(form is not None and form.getfirst("force_refresh", "") == "1")
            for path in paths:
                resolution = resolve_subject(path, requested_subject, source_override, config.get("subject_sources", {}), ROOT, timeout=subject_timeout)
                if resolution.source_path is None:
                    raise ValueError(f"{resolution.label} için ders kaynağı bulunamadı.")
                review_jobs.append(ReviewJob(
                    path, display_name=staged_names.get(path, path.name),
                    subject=resolution.key, subject_path=resolution.source_path,
                    subject_label=resolution.label, temporary_input=path in uploaded_set,
                    temporary_subject=resolution.temporary, report_mode=report_mode,
                    force_refresh=force_refresh,
                ))

            job_id = uuid.uuid4().hex
            sess_jobs = self._session_jobs(sess)
            sess_lock = self._session_jobs_lock(sess)
            with sess_lock:
                sess_jobs[job_id] = {
                    "status": "queued", "current": 0, "total": len(review_jobs),
                    "file": "", "stage": "Kuyruğa alındı",
                    "steps": progress_steps(), "queue": review_queue(review_jobs), "results": [],
                }
            output_dir = self._session_output_dir(sess)
            threading.Thread(
                target=run_batch,
                args=(job_id, sess_provider, review_jobs, sess, output_dir),
                daemon=True,
            ).start()
            return self._redirect(f"/status?job={quote(job_id)}", session=sess)
        except Exception as exc:
            for path in uploads:
                path.unlink(missing_ok=True)
            for job in review_jobs:
                if job.temporary_subject:
                    cleanup_subject_source(job.subject_path)
            back_url = self._url("/")
            return self._page(f"<div class='card'><p class='error'>İşlem başarısız: {html.escape(safe_error(str(exc)))}</p><a href='{back_url}'>Geri</a></div>", session=sess)






def run_batch(
    job_id: str,
    active_provider,
    review_jobs: list[ReviewJob],
    session: "_sessions_mod._Session",
    output_dir: Path,
) -> None:
    sess_jobs = session.jobs
    sess_lock = session.jobs_lock

    def _jobs_update(data: dict) -> None:
        with sess_lock:
            if job_id in sess_jobs:
                sess_jobs[job_id].update(data)

    def _progress_callback(key: str, detail: str) -> None:
        _update_progress_in(job_id, key, detail, sess_jobs, sess_lock)

    async def work() -> None:
        engine = ReviewEngine(active_provider, ROOT / "rules" / "rules.bin", output_dir)
        _jobs_update({"status": "running"})
        for index, job in enumerate(review_jobs, 1):
            with sess_lock:
                if job_id in sess_jobs:
                    sess_jobs[job_id].update({"file": job.display_name or job.path.name, "stage": "Hazırlanıyor", "steps": progress_steps()})
                    if index <= len(sess_jobs[job_id].get("queue", [])):
                        sess_jobs[job_id]["queue"][index - 1].update({"status": "running", "detail": "Hazırlanıyor"})
            try:
                result = await engine.run(job, on_progress=_progress_callback)
            finally:
                if job.temporary_input:
                    job.path.unlink(missing_ok=True)
                if job.temporary_subject:
                    cleanup_subject_source(job.subject_path)
            item = {"name": job.display_name or job.path.name, "subject": job.subject_label or job.subject, "report_mode": job.report_mode}
            if result.error:
                item["error"] = safe_error(result.error)
                if result.markdown_path and result.markdown_path.is_file():
                    item["raw"] = str(result.markdown_path)
                if is_auth_error(result.error):
                    session.connected = False
            else:
                item.update({"docx": str(result.docx_path), "pdf": str(result.pdf_path), "md": str(result.markdown_path), "json": str(result.json_path), "cached": bool(result.metadata.get("cached"))})
            _progress_callback(
                "complete",
                "Raporlar hazır; geçici defter temizlendi"
                if not result.error
                else "İşlem tamamlandı; mevcut NotebookLM yanıtı korundu",
            )
            with sess_lock:
                if job_id in sess_jobs:
                    sess_jobs[job_id]["results"].append(item)
                    if index <= len(sess_jobs[job_id].get("queue", [])):
                        queue_item = sess_jobs[job_id]["queue"][index - 1]
                        queue_item.update(item)
                        queue_item.update({"status": "error" if item.get("error") else "completed", "detail": "Rapor hazırlanamadı" if item.get("error") else "Rapor hazır"})
                    sess_jobs[job_id].update({"current": index, "stage": "Rapor dışa aktarıldı; geçici defter temizlendi"})
        with sess_lock:
            if job_id in sess_jobs:
                sess_jobs[job_id]["status"] = "completed" if all("error" not in item for item in sess_jobs[job_id]["results"]) else "completed_with_errors"

    try:
        asyncio.run(work())
    except Exception as exc:
        error = safe_error(str(exc))
        with sess_lock:
            if job_id not in sess_jobs:
                return
            state = sess_jobs[job_id]
            state["status"] = "completed_with_errors"
            running_index = next((idx for idx, it in enumerate(state.get("queue", [])) if it.get("status") == "running"), None)
            if running_index is not None:
                failed = {"name": state["queue"][running_index].get("name", "İş kuyruğu"), "subject": state["queue"][running_index].get("subject", ""), "report_mode": state["queue"][running_index].get("report_mode", "full"), "error": error}
                state["queue"][running_index].update(failed | {"status": "error", "detail": "Rapor hazırlanamadı"})
                state["results"].append(failed)
            else:
                state["results"].append({"name": "İş kuyruğu", "error": error})
    finally:
        for job in review_jobs:
            if job.temporary_subject:
                cleanup_subject_source(job.subject_path)




PROGRESS_STEPS = [
    ("rules", "V7 hazırlığı"), ("cache_hit", "Önbellek"), ("notebook", "NotebookLM bağlantısı"), ("notebook_create", "Geçici defter"),
    ("rules_upload", "Kontrol yönergesi"), ("subject_upload", "Ders kaynağı"), ("question_upload", "Soru dosyası"),
    ("detail_mode", "Ayrıntılı yanıt modu"), ("analysis", "NotebookLM değerlendirmesi"),
    ("detail_recovery", "V7 biçim doğrulaması"), ("cleanup", "Güvenli temizlik"),
    ("export", "Word ve PDF raporları"), ("complete", "Tamamlandı"),
]

PROGRESS_PHASES = [
    ("Hazırlık", {"rules", "cache_hit", "notebook"}),
    ("Kaynaklar", {"notebook_create", "rules_upload", "subject_upload", "question_upload"}),
    ("Değerlendirme", {"detail_mode", "analysis", "detail_recovery"}),
    ("Rapor", {"cleanup", "export", "complete"}),
]

PROGRESS_COPY = {
    "rules": ("Kontrol ölçütleri hazırlanıyor", "Güncel V7 ölçütleri güvenli biçimde hazırlanıyor."),
    "cache_hit": ("Daha önceki rapor kontrol ediliyor", "Aynı dosya için doğrulanmış bir rapor olup olmadığı kontrol ediliyor."),
    "notebook": ("NotebookLM bağlantısı kuruluyor", "Gmail oturumu üzerinden güvenli bağlantı açılıyor."),
    "notebook_create": ("Geçici çalışma alanı hazırlanıyor", "Bu soru dosyasına özel geçici bir NotebookLM alanı oluşturuluyor."),
    "rules_upload": ("Kontrol ölçütleri ekleniyor", "Güncel V7 ölçütleri değerlendirme alanına ekleniyor."),
    "subject_upload": ("Ders kaynağı ekleniyor", "İlgili ders programı değerlendirme alanına ekleniyor."),
    "question_upload": ("Soru dosyası hazırlanıyor", "Seçtiğiniz soru dosyası değerlendirme alanına ekleniyor."),
    "detail_mode": ("Ayrıntılı değerlendirme hazırlanıyor", "Kapsamlı bir rapor için ayrıntılı yanıt modu ayarlanıyor."),
    "analysis": ("NotebookLM tam V7 değerlendirmesini yapıyor", "Bütün V7 ölçütleri, güncel kural paketi ve ilgili ders kaynağıyla inceleniyor. Bu adım birkaç dakika sürebilir."),
    "detail_recovery": ("V7 rapor yapısı doğrulanıyor", "Yaygın Markdown farklılıkları güvenle düzeltiliyor; tamamlanamayan yanıt silinmeden indirilebilir olarak korunuyor."),
    "cleanup": ("Geçici kaynaklar temizleniyor", "Bu değerlendirmeye ait geçici NotebookLM alanı güvenli biçimde kaldırılıyor."),
    "export": ("Word ve PDF raporları hazırlanıyor", "Değerlendirme okunabilir Word ve PDF belgelerine dönüştürülüyor."),
    "complete": ("Rapor hazır", "Değerlendirme tamamlandı; raporları görüntüleyebilir veya indirebilirsiniz."),
}


def progress_steps() -> list[dict]:
    return [{"key": key, "label": label, "detail": "Bekliyor", "status": "pending"} for key, label in PROGRESS_STEPS]


def review_queue(review_jobs: list[ReviewJob]) -> list[dict]:
    return [
        {
            "name": job.display_name or job.path.name,
            "subject": job.subject_label or job.subject,
            "report_mode": job.report_mode,
            "status": "pending",
            "detail": "Değerlendirme sırası bekleniyor",
        }
        for job in review_jobs
    ]


def progress_snapshot(state: dict) -> dict:
    steps = state.get("steps") or progress_steps()
    step_total = len(steps)
    status = state.get("status", "queued")
    active_index = next((index for index, step in enumerate(steps) if step.get("status") == "active"), None)
    if active_index is None:
        if status in {"completed", "completed_with_errors"}:
            active_index = step_total - 1
        else:
            active_index = next((index for index, step in enumerate(steps) if step.get("status") == "pending"), 0)
    current_key = steps[active_index]["key"] if steps else "rules"
    title, description = PROGRESS_COPY.get(current_key, ("Değerlendirme sürüyor", "Seçilen soru dosyası işleniyor."))

    total = max(int(state.get("total") or 1), 1)
    completed_files = min(max(int(state.get("current") or 0), 0), total)
    if status in {"completed", "completed_with_errors"}:
        percent = 100
        file_number = total
    else:
        step_fraction = (active_index + (0.45 if steps[active_index].get("status") == "active" else 0)) / max(step_total, 1)
        percent = round(100 * min(completed_files + step_fraction, total) / total)
        file_number = min(completed_files + 1, total)

    phase_index = next((index for index, (_, keys) in enumerate(PROGRESS_PHASES) if current_key in keys), 0)
    phases = []
    for index, (label, _) in enumerate(PROGRESS_PHASES):
        if status == "completed":
            phase_status = "done"
        elif status == "completed_with_errors":
            phase_status = "error" if index == len(PROGRESS_PHASES) - 1 else "done"
        elif index < phase_index:
            phase_status = "done"
        elif index == phase_index:
            phase_status = "active"
        else:
            phase_status = "pending"
        phases.append({"number": index + 1, "label": label, "status": phase_status})

    if status == "queued":
        eyebrow, tone = "Değerlendirme sırada", "active"
        title, description = "Değerlendirme hazırlanıyor", "Dosya işlem sırasına alındı; değerlendirme kısa süre içinde başlayacak."
    elif status == "running":
        eyebrow, tone = "Değerlendirme devam ediyor", "active"
    elif status == "completed":
        eyebrow, tone = "Değerlendirme tamamlandı", "success"
        title, description = PROGRESS_COPY["complete"]
    else:
        eyebrow, tone = "İşlem tamamlandı", "danger"
        title, description = "Bazı raporlar hazırlanamadı", "Aşağıdaki sonuçlarda hata ayrıntısını ve gerekiyorsa yeniden giriş seçeneğini görebilirsiniz."

    return {
        "eyebrow": eyebrow,
        "tone": tone,
        "title": title,
        "description": description,
        "percent": max(0, min(percent, 100)),
        "file_number": file_number,
        "total": total,
        "file_name": str(state.get("file") or "Dosya hazırlanıyor"),
        "step_number": min(active_index + 1, step_total),
        "step_total": step_total,
        "completed_files": completed_files,
        "refresh_text": "Sayfa otomatik güncelleniyor" if status in {"queued", "running"} else "İşlem sona erdi",
        "phases": phases,
    }


def status_revision(state: dict) -> str:
    payload = {
        "status": state.get("status"),
        "current": state.get("current"),
        "total": state.get("total"),
        "file": state.get("file"),
        "stage": state.get("stage"),
        "steps": [
            {"key": step.get("key"), "status": step.get("status"), "detail": step.get("detail")}
            for step in state.get("steps", [])
        ],
        "results": state.get("results", []),
        "queue": state.get("queue", []),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def _update_progress_in(job_id: str, key: str, detail: str, sess_jobs: dict, sess_lock: threading.Lock) -> None:
    """Session-aware progress updater used by run_batch."""
    with sess_lock:
        state = sess_jobs.get(job_id)
        if not state:
            return
        steps = state.get("steps", [])
        current_index = next((i for i, step in enumerate(steps) if step["key"] == key), None)
        if current_index is None:
            return
        for index, step in enumerate(steps):
            if index < current_index:
                if step["status"] == "active":
                    step["status"] = "done"
                elif step["status"] == "pending":
                    step.update({"status": "skipped", "detail": "Bu işlemde çalıştırılmadı"})
            elif index == current_index:
                step.update({"status": "done" if key == "complete" else "active", "detail": detail})
        state["stage"] = detail


def update_progress(job_id: str, key: str, detail: str) -> None:
    """Legacy global-jobs progress updater (retained for FAKE_MODE / tests)."""
    with jobs_lock:
        state = jobs.get(job_id)
        if not state: return
        steps = state.get("steps", [])
        current_index = next((i for i, step in enumerate(steps) if step["key"] == key), None)
        if current_index is None: return
        for index, step in enumerate(steps):
            if index < current_index:
                if step["status"] == "active": step["status"] = "done"
                elif step["status"] == "pending": step.update({"status": "skipped", "detail": "Bu işlemde çalıştırılmadı"})
            elif index == current_index: step.update({"status": "done" if key == "complete" else "active", "detail": detail})
        state["stage"] = detail


def _write_server_pid() -> None:
    """Record the foreground web-server PID for the matching stop script."""
    SERVER_PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    SERVER_PID_PATH.write_text(str(os.getpid()), encoding="ascii")


def _clear_server_pid() -> None:
    """Remove our PID marker without deleting a newer server's marker."""
    try:
        if SERVER_PID_PATH.read_text(encoding="ascii").strip() == str(os.getpid()):
            SERVER_PID_PATH.unlink(missing_ok=True)
    except (FileNotFoundError, OSError, UnicodeError):
        pass


def main() -> None:
    global last_browser_activity
    port = int(os.environ.get("PORT") or os.environ.get("PILOT_PORT", "8765"))
    host = os.environ.get("PILOT_HOST", "0.0.0.0" if (os.environ.get("PORT") or os.environ.get("RENDER")) else "127.0.0.1")
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        raise SystemExit(
            f"{host}:{port} zaten kullanimda. Yeni sunucuyu baslatmadan once "
            f"'.\\stop.ps1 -Port {port}' calistirin. Ayrinti: {exc}"
        ) from exc
    _write_server_pid()
    touch_browser_activity()
    # Start per-user session cleanup daemon
    _sessions_mod.start_cleanup_daemon()
    timeout_seconds = idle_shutdown_seconds()
    if timeout_seconds > 0:
        threading.Thread(target=idle_watchdog, args=(server, timeout_seconds), daemon=True).start()
    print(f"Soru Kontrol Merkezi hazir: http://127.0.0.1:{port}/")
    if timeout_seconds > 0:
        print(f"Tarayici baglantisi kesilirse ve aktif is yoksa {timeout_seconds} saniye sonra sunucu otomatik kapanir.")
    print("Durdurmak icin bu pencerede Ctrl+C kullanin veya ayri PowerShell'de .\\stop.ps1 calistirin.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        _clear_server_pid()


if __name__ == "__main__":
    main()
