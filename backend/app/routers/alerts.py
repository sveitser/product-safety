import json
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..db import get_conn

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")
templates.env.filters["basename"] = lambda p: Path(p).name if p else ""

PAGE_SIZE = 20


def _row_to_dict(row) -> dict:
    d = dict(row)
    for field in ("brands", "model_types", "risk_types", "measures"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                d[field] = []
        else:
            d[field] = []
    return d


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = "",
    category: str = "",
    page: int = Query(1, ge=1),
) -> HTMLResponse:
    conn = get_conn()
    offset = (page - 1) * PAGE_SIZE

    if q:
        rows = conn.execute(
            """
            SELECT a.* FROM alerts a
            JOIN alerts_fts f ON a.id = f.rowid
            WHERE alerts_fts MATCH ?
              AND (? = '' OR a.product_category = ?)
            ORDER BY a.publication_date DESC
            LIMIT ? OFFSET ?
            """,
            (q, category, category, PAGE_SIZE, offset),
        ).fetchall()
        total = conn.execute(
            """
            SELECT COUNT(*) FROM alerts a
            JOIN alerts_fts f ON a.id = f.rowid
            WHERE alerts_fts MATCH ?
              AND (? = '' OR a.product_category = ?)
            """,
            (q, category, category),
        ).fetchone()[0]
    else:
        rows = conn.execute(
            """
            SELECT * FROM alerts
            WHERE (? = '' OR product_category = ?)
            ORDER BY publication_date DESC
            LIMIT ? OFFSET ?
            """,
            (category, category, PAGE_SIZE, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE (? = '' OR product_category = ?)",
            (category, category),
        ).fetchone()[0]

    alerts_list = [_row_to_dict(r) for r in rows]

    # Attach main photo path for each alert
    for alert in alerts_list:
        photo = conn.execute(
            "SELECT * FROM photos WHERE alert_id=? AND main_picture=1 LIMIT 1",
            (alert["id"],),
        ).fetchone()
        alert["main_photo"] = dict(photo) if photo else None

    categories = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT product_category FROM alerts ORDER BY product_category"
        ).fetchall()
        if r[0]
    ]
    conn.close()

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "partials/alert_list.html" if is_htmx else "index.html"

    return templates.TemplateResponse(
        template,
        {
            "request": request,
            "alerts": alerts_list,
            "q": q,
            "category": category,
            "categories": categories,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )


@router.get("/alert/{alert_id}", response_class=HTMLResponse)
def alert_detail(request: Request, alert_id: int) -> HTMLResponse:
    conn = get_conn()
    row = conn.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
    if row is None:
        conn.close()
        return HTMLResponse("<h1>Not found</h1>", status_code=404)

    alert = _row_to_dict(row)
    photos = [
        dict(p)
        for p in conn.execute(
            "SELECT * FROM photos WHERE alert_id=? ORDER BY main_picture DESC",
            (alert_id,),
        ).fetchall()
    ]
    conn.close()

    return templates.TemplateResponse(
        "detail.html",
        {"request": request, "alert": alert, "photos": photos},
    )
