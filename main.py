"""
코로나19 변이 계통 추적 및 시각화 시스템 - Phase 1
Senior DevOps + FastAPI Implementation
"""

from __future__ import annotations

import html
import json
from markupsafe import Markup
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "variants.json"
TEMPLATES_DIR = BASE_DIR / "templates"

# ──────────────────────────────────────────────
# App Bootstrap
# ──────────────────────────────────────────────
app = FastAPI(
    title="코로나19 변이 계통 추적 시스템",
    version="1.0.0",
    description="SARS-CoV-2 변이 계통 계층 구조 추적 및 시각화 API",
)

# Jinja2 환경 직접 구성 (Starlette wrapper 우회)
_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True,
)


def render_template(name: str, **ctx) -> str:
    return _jinja_env.get_template(name).render(**ctx)


# ──────────────────────────────────────────────
# Data Loading & Normalization
# ──────────────────────────────────────────────
def load_variants() -> list[dict]:
    """variants.json을 읽어 정규화된 전파성 값과 치사율 bar 폭을 추가한다."""
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    variants: list[dict] = raw["variants"]

    # 1) 전파성 최대값 탐색
    max_raw: float = max(v["transmissibility_raw"] for v in variants)

    # 2) 정규화: 최고 전파성 = 100, 나머지 상대 비율
    for v in variants:
        v["transmissibility"] = round((v["transmissibility_raw"] / max_raw) * 100, 1)
        # 치사율 bar width: 최대 5% → 100% 매핑, 상한 100
        v["fatality_bar"] = min(round(v["fatality_rate"] * 20, 1), 100)

    return variants


def build_tree(variants: list[dict]) -> list[dict]:
    """평탄한 리스트를 계층적 트리로 변환한다."""
    by_id: dict[str, dict] = {v["id"]: {**v, "children": []} for v in variants}
    roots: list[dict] = []
    for node in by_id.values():
        pid = node.get("parent_id")
        if pid is None:
            roots.append(node)
        elif pid in by_id:
            by_id[pid]["children"].append(node)
    return roots


# ──────────────────────────────────────────────
# HTML Tree Generator (Python-side)
# ──────────────────────────────────────────────
def _tx_class(tx: float) -> str:
    if tx >= 90:
        return "tx-critical"
    elif tx >= 70:
        return "tx-high"
    elif tx >= 50:
        return "tx-mid"
    return "tx-low"


def _render_card(node: dict) -> str:
    """단일 변이 카드 HTML 문자열을 반환한다."""
    is_korea = node["is_korea"]
    tx = node["transmissibility"]
    tc = _tx_class(tx)
    extra_class = " mugunghwa-card" if is_korea else ""

    who_ribbon = '<div class="who-ribbon">WHO VOC</div>' if node["who_label"] else ""
    mug_icon = '<div class="mug-icon" title="한국 발생 확인">🌸</div>' if is_korea else ""
    korea_badge = '<div class="korea-badge">🇰🇷 국내 발생 확인</div>' if is_korea else ""

    desc = html.escape(node["description"])
    name = html.escape(node["name"])
    antibody = html.escape(node["antibody_characteristics"])
    clade = html.escape(node["clade"])
    first_det = html.escape(node["first_detected"])
    node_id = html.escape(node["id"])
    fat_bar = node["fatality_bar"]
    fat_rate = node["fatality_rate"]

    return f"""<div class="variant-card{extra_class}" id="card-{node_id}" role="article" aria-label="{name}">
  {who_ribbon}
  <div class="card-header">
    <div class="card-name">{name}</div>
    {mug_icon}
  </div>
  <div class="clade-badge">Clade {clade}</div>
  <p class="card-desc">{desc}</p>
  <div class="metrics">
    <div class="metric-row">
      <span class="metric-label {tc}">전파성</span>
      <div class="metric-bar-wrap"><div class="metric-bar bar-tx" style="width:{tx}%"></div></div>
      <span class="metric-val {tc}">{tx}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">치사율</span>
      <div class="metric-bar-wrap"><div class="metric-bar bar-fat" style="width:{fat_bar}%"></div></div>
      <span class="metric-val">{fat_rate}%</span>
    </div>
  </div>
  <div class="first-detected">📅 {first_det}</div>
  {korea_badge}
  <div class="antibody-row">
    <span class="antibody-trigger">🧬 항체 특성 보기</span>
    <div class="antibody-tooltip">{antibody}</div>
  </div>
</div>"""


def _stem_class(node: dict) -> str:
    return "connector-down mug-stem" if node["is_korea"] else "connector-down"


def _render_subtree(node: dict) -> str:
    """변이 노드와 하위 계통을 재귀적으로 HTML로 변환한다."""
    parts = ['<div class="branch">']
    parts.append(_render_card(node))

    children = node.get("children", [])
    if children:
        stem = _stem_class(node)
        parts.append(f'<div class="{stem}"></div>')
        parts.append('<div class="children-row">')
        for child in children:
            c_stem = _stem_class(child)
            parts.append('<div class="child-slot">')
            parts.append(f'<div class="{c_stem}"></div>')
            parts.append(_render_subtree(child))
            parts.append('</div>')
        parts.append('</div>')

    parts.append('</div>')
    return "\n".join(parts)


def render_forest(tree: list[dict]) -> str:
    """전체 트리를 HTML 문자열로 반환한다."""
    inner = "\n".join(_render_subtree(root) for root in tree)
    return f'<div class="forest">{inner}</div>'


# ──────────────────────────────────────────────
# API Endpoints
# ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse, summary="메인 시각화 페이지")
async def index(request: Request):
    """Jinja2 템플릿으로 렌더링된 변이 트리 페이지를 반환한다."""
    variants = load_variants()
    tree = build_tree(variants)

    total = len(variants)
    korea_count = sum(1 for v in variants if v["is_korea"])
    max_variant = max(variants, key=lambda v: v["transmissibility"])
    min_fatality = min(variants, key=lambda v: v["fatality_rate"])

    content = render_template(
        "index.html",
        tree_html=Markup(render_forest(tree)),
        stats={
            "total": total,
            "korea_count": korea_count,
            "max_transmissibility_variant": max_variant["name"],
            "max_transmissibility_value": max_variant["transmissibility"],
            "min_fatality_variant": min_fatality["name"],
            "min_fatality_value": min_fatality["fatality_rate"],
        },
    )
    return HTMLResponse(content=content)


@app.get("/api/variants", summary="변이 목록 (정규화 포함)")
async def get_variants():
    return {"variants": load_variants()}


@app.get("/api/variants/{variant_id}", summary="특정 변이 상세 정보")
async def get_variant(variant_id: str):
    variants = load_variants()
    match = next((v for v in variants if v["id"] == variant_id), None)
    if match is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"변이 '{variant_id}'를 찾을 수 없습니다.")
    return match


@app.get("/api/tree", summary="계층 트리 구조")
async def get_tree():
    variants = load_variants()
    return {"tree": build_tree(variants)}


@app.get("/health", summary="헬스 체크")
async def health():
    return {"status": "ok", "service": "covid-variant-tracker"}
