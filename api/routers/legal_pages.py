# api/routers/legal_pages.py
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from fastapi import HTTPException
from pathlib import Path
from typing import Dict

router = APIRouter(tags=["legal"])

BASE = Path(__file__).resolve().parents[2] / "web" / "legal"
CONF = Path(__file__).resolve().parents[2] / "config" / "company.yaml"

# 会社情報プレースホルダ（{{company.name}} 等）で利用
KEYS = ["name", "address", "phone", "email", "representative", "revised", "version"]


def _parse_company_yaml() -> Dict[str, str]:
    """
    company.yaml を読み込み、{key: value} を返す。
    - PyYAML があれば使用
    - ない場合は key: value 形式だけを拾う簡易パーサでフォールバック
    """
    data: Dict[str, str] = {k: "" for k in KEYS}
    if not CONF.exists():
        return data

    # 1) PyYAML が使えるならそれを優先
    try:
        import yaml  # type: ignore
        raw = yaml.safe_load(CONF.read_text(encoding="utf-8")) or {}
        src = (raw.get("company") or raw) if isinstance(raw, dict) else {}
        if isinstance(src, dict):
            for k in KEYS:
                if k in src and src[k] is not None:
                    data[k] = str(src[k])
        return data
    except Exception:
        # 2) 超簡易パーサ（"key: value" のみ）
        try:
            for line in CONF.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if not s or s.startswith("#") or ":" not in s:
                    continue
                k, v = s.split(":", 1)
                k, v = k.strip(), v.strip()
                if k in KEYS:
                    data[k] = v
                elif k.startswith("company."):
                    kk = k.split(".", 1)[1]
                    if kk in KEYS:
                        data[kk] = v
        except Exception:
            # フォールバックも失敗したら空の data を返す
            pass
        return data


def _inject_company_placeholders(html: str) -> str:
    """
    HTML 内の {{company.key}} を company.yaml の値で置換
    """
    company = _parse_company_yaml()
    for k, v in company.items():
        html = html.replace(f"{{{{company.{k}}}}}", v)
    return html


def _read_html(name: str) -> HTMLResponse:
    """
    web/legal/<name> を読み込んで HTML を返す。
    見つからなければ 404 を返却。
    """
    p = BASE / name
    if not p.is_file():
        # 正しく 404 を返す
        raise HTTPException(status_code=404, detail="Not Found")

    body = p.read_text(encoding="utf-8")
    body = _inject_company_placeholders(body)
    return HTMLResponse(content=body)  # text/html; charset=utf-8 が既定


@router.get("/privacy", response_class=HTMLResponse)
def privacy() -> HTMLResponse:
    return _read_html("privacy.html")


@router.get("/terms", response_class=HTMLResponse)
def terms() -> HTMLResponse:
    return _read_html("terms.html")


@router.get("/cookie", response_class=HTMLResponse)
def cookie() -> HTMLResponse:
    return _read_html("cookie.html")
