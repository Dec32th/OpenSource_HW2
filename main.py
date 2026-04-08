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
# API Endpoints
# ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse, summary="메인 시각화 페이지")
async def index(request: Request):
    """Jinja2 템플릿으로 렌더링된 메인 페이지를 반환한다. (D3.js 프론트엔드 연결)"""
    variants = load_variants()

    total = len(variants)
    korea_count = sum(1 for v in variants if v["is_korea"])
    if total > 0:
        max_variant = max(variants, key=lambda v: v["transmissibility"])
        min_fatality = min(variants, key=lambda v: v["fatality_rate"])
    else:
        max_variant = {"name": "-", "transmissibility": 0}
        min_fatality = {"name": "-", "fatality_rate": 0}

    content = render_template(
        "index.html",
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
