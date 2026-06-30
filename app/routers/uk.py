from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import db
from app.services import find_key, write_key_to_panels
from app.templates_config import templates

router = APIRouter()


@router.get("/uk", response_class=HTMLResponse)
def uk_page(request: Request):
    with db() as conn:
        groups = [
            dict(r)
            for r in conn.execute(
                """
                SELECT *
                FROM uk_groups
                ORDER BY name
                """
            )
        ]

        panels = [
            dict(r)
            for r in conn.execute(
                """
                SELECT *
                FROM panels
                WHERE enabled = 1
                ORDER BY address, name
                """
            )
        ]

    return templates.TemplateResponse(
        "uk.html",
        {
            "request": request,
            "groups": groups,
            "panels": panels,
        },
    )


@router.post("/uk/group")
def uk_group(
    name: str = Form(...),
    panel_ids: list[int] = Form([]),
    note: str = Form(""),
):
    with db() as conn:

        conn.execute(
            """
            INSERT INTO uk_groups(name, note)
            VALUES(?, ?)
            ON CONFLICT(name)
            DO UPDATE SET
                note = excluded.note
            """,
            (
                name.strip(),
                note.strip(),
            ),
        )

        gid = conn.execute(
            """
            SELECT id
            FROM uk_groups
            WHERE name = ?
            """,
            (name.strip(),),
        ).fetchone()["id"]

        conn.execute(
            """
            DELETE
            FROM uk_group_panels
            WHERE group_id = ?
            """,
            (gid,),
        )

        conn.executemany(
            """
            INSERT OR IGNORE
            INTO uk_group_panels(group_id, panel_id)
            VALUES(?, ?)
            """,
            [
                (gid, int(pid))
                for pid in panel_ids
            ],
        )

    return RedirectResponse(
        "/uk",
        status_code=303,
    )


@router.post("/uk/write", response_class=HTMLResponse)
def uk_write(
    request: Request,
    group_id: int = Form(...),
    key_values: str = Form(...),
    flat_num: str = Form("0"),
    inner: int = Form(0),
):
    with db() as conn:

        panels = [
            dict(r)
            for r in conn.execute(
                """
                SELECT p.*
                FROM panels p
                JOIN uk_group_panels gp
                    ON gp.panel_id = p.id
                WHERE
                    gp.group_id = ?
                    AND p.enabled = 1
                ORDER BY
                    p.address,
                    p.name
                """,
                (group_id,),
            )
        ]

    all_results = []

    for value in [
        x.strip()
        for x in key_values.replace(",", " ").split()
        if x.strip()
    ]:

        item = find_key(value)

        if item:

            all_results.append(
                {
                    "key": item,
                    "results": write_key_to_panels(
                        "uk",
                        item,
                        panels,
                        flat_num=flat_num,
                        inner=inner,
                    ),
                }
            )

        else:

            all_results.append(
                {
                    "key": {
                        "number": value,
                        "hex_value": "НЕ НАЙДЕН",
                    },
                    "results": [],
                }
            )

    return templates.TemplateResponse(
        "write_results.html",
        {
            "request": request,
            "title": "Результат записи УК",
            "all_results": all_results,
        },
    )