from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from .db import init_db, db
from .services import (
    parse_message,
    find_key,
    find_panels_by_address,
    write_key_to_panels,
    import_keys_file,
    import_panels_excel,
    get_panels,
)
from .settings import settings

app = FastAPI(title='Key Writer Simple')
BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / 'templates'))
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

@app.on_event('startup')
def startup():
    init_db()

@app.get('/', response_class=HTMLResponse)
def index(request: Request):
    with db() as conn:
        stats = {
            'keys': conn.execute('SELECT COUNT(*) FROM keys').fetchone()[0],
            'panels': conn.execute('SELECT COUNT(*) FROM panels WHERE enabled=1').fetchone()[0],
            'logs': conn.execute('SELECT COUNT(*) FROM operation_log').fetchone()[0],
        }
    return templates.TemplateResponse('index.html', {'request': request, 'stats': stats, 'dry_run': settings.dry_run})

@app.get('/message', response_class=HTMLResponse)
def message_form(request: Request):
    return templates.TemplateResponse('message.html', {'request': request})

@app.post('/message/preview', response_class=HTMLResponse)
def message_preview(request: Request, text: str = Form(...)):
    parsed = parse_message(text)
    keys = []
    for n in parsed['key_numbers']:
        keys.append({'number': n, 'item': find_key(n)})
    panels = find_panels_by_address(parsed['address'])
    return templates.TemplateResponse('message_preview.html', {'request': request, 'text': text, 'parsed': parsed, 'keys': keys, 'panels': panels})

@app.post('/message/write', response_class=HTMLResponse)
def message_write(
    request: Request,
    address: str = Form(""),
    apartment: str = Form(""),
    key_numbers: str = Form(""),
    panel_ids: list[int] = Form([]),
):
    if panel_ids:
        panels = get_panels(panel_ids=panel_ids)
    else:
        panels = find_panels_by_address(address)
    all_results = []
    for n in [x.strip() for x in key_numbers.replace(',', ' ').split() if x.strip()]:
        item = find_key(n)
        if item:
            all_results.append({'key': item, 'results': write_key_to_panels(
    'resident',
    item,
    panels,
    flat_num=apartment,
    inner=1,
    address=address,
)})
        else:
            all_results.append({'key': {'number': n, 'hex_value': 'НЕ НАЙДЕН'}, 'results': []})
    return templates.TemplateResponse('write_results.html', {'request': request, 'title': 'Результат записи жильца', 'all_results': all_results})
def normalize_hex(value: str) -> str:
    value = value.strip().upper().replace(" ", "").replace(":", "").replace("-", "")
    if value.startswith("000000") and len(value) == 14:
        value = value[6:]
    return value


def is_hex_like(value: str) -> bool:
    value = normalize_hex(value)
    return len(value) == 8 and all(ch in "0123456789ABCDEF" for ch in value)


def universal_find_key(query: str):
    q = query.strip()
    if not q:
        return None

    hex_candidate = normalize_hex(q)

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM keys WHERE number = ? LIMIT 1",
            (q,),
        ).fetchone()

        if row:
            return dict(row)

        row = conn.execute(
            "SELECT * FROM keys WHERE number = ? LIMIT 1",
            (q.replace(" ", ""),),
        ).fetchone()

        if row:
            return dict(row)

        if is_hex_like(q):
            row = conn.execute(
                "SELECT * FROM keys WHERE UPPER(hex_value) = ? LIMIT 1",
                (hex_candidate,),
            ).fetchone()

            if row:
                return dict(row)

    return None


@app.get("/write/manual", response_class=HTMLResponse)
def manual_write_form(request: Request):
    return templates.TemplateResponse(
        "manual_write.html",
        {
            "request": request,
            "key": None,
            "panels": [],
            "query": "",
            "address": "",
            "apartment": "",
            "error": None,
        },
    )


@app.post("/write/manual/preview", response_class=HTMLResponse)
def manual_write_preview(
    request: Request,
    key_query: str = Form(...),
    address: str = Form(...),
    apartment: str = Form(""),
):
    key = universal_find_key(key_query)
    panels = find_panels_by_address(address)

    error = None
    if not key:
        error = "Ключ не найден в базе"
    elif not panels:
        error = "Панели по этому адресу не найдены"

    return templates.TemplateResponse(
        "manual_write.html",
        {
            "request": request,
            "key": key,
            "panels": panels,
            "query": key_query,
            "address": address,
            "apartment": apartment,
            "error": error,
        },
    )


@app.post("/write/manual/write", response_class=HTMLResponse)
def manual_write_execute(
    request: Request,
    key_query: str = Form(...),
    address: str = Form(...),
    apartment: str = Form(""),
    inner: int = Form(1),
    panel_ids: list[int] = Form([]),
):
    key = universal_find_key(key_query)

    if panel_ids:
        panels = get_panels(panel_ids=panel_ids)
    else:
        panels = find_panels_by_address(address)

    all_results = []

    if key:
        all_results.append(
            {
                "key": key,
                "results": write_key_to_panels(
                    "resident_manual",
                    key,
                    panels,
                    flat_num=apartment,
                    inner=inner,
                    address=address,
                ),
            }
        )
    else:
        all_results.append(
            {
                "key": {
                    "number": key_query,
                    "hex_value": "НЕ НАЙДЕН",
                },
                "results": [],
            }
        )

    return templates.TemplateResponse(
        "write_results.html",
        {
            "request": request,
            "title": "Результат ручной записи ключа",
            "all_results": all_results,
        },
    )


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request):
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "result": None,
        },
    )


@app.post("/search", response_class=HTMLResponse)
def search_result(request: Request, query: str = Form(...)):
    from .services import universal_search

    result = universal_search(query)

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "result": result,
        },
    )

@app.get('/employees', response_class=HTMLResponse)
def employees(request: Request):
    panels = get_panels()

    with db() as conn:
        employees_rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT *
                FROM employees
                WHERE enabled = 1
                ORDER BY full_name
                """
            )
        ]

    return templates.TemplateResponse(
        'employees.html',
        {
            'request': request,
            'panels': panels,
            'employees': employees_rows,
        },
    )

@app.post("/employees/add")
def employees_add(
    full_name: str = Form(...),
    note: str = Form(""),
):
    with db() as conn:
        conn.execute(
            """
            INSERT INTO employees(full_name, note)
            VALUES(?, ?)
            """,
            (
                full_name.strip(),
                note.strip(),
            ),
        )

    return RedirectResponse("/employees", status_code=303)

@app.post("/employees/delete")
def employees_delete(employee_id: int = Form(...)):
    with db() as conn:
        conn.execute(
            """
            UPDATE employees
            SET enabled = 0
            WHERE id = ?
            """,
            (employee_id,),
        )

    return RedirectResponse("/employees", status_code=303)

@app.post('/employees/write', response_class=HTMLResponse)
def employees_write(
    request: Request,
    employee_name: str = Form(...),
    key_values: str = Form(...),
    scope: str = Form('all'),
    panel_ids: list[int] = Form([]),
    flat_num: str = Form('0'),
    inner: int = Form(0),
):
    if scope == 'selected':
        panels = get_panels(panel_ids=panel_ids)
    elif scope == 'employee_tag':
        panels = get_panels(tag='employee')
    else:
        panels = get_panels()

    all_results = []

    for val in [x.strip() for x in key_values.replace(',', ' ').split() if x.strip()]:
        item = find_key(val)

        if item:
            all_results.append({
                'key': item,
                'results': write_key_to_panels(
                    'employee',
                    item,
                    panels,
                    flat_num=flat_num,
                    inner=inner,
                    address=f'Сотрудник: {employee_name}',
                )
            })
        else:
            all_results.append({
                'key': {
                    'number': val,
                    'hex_value': 'НЕ НАЙДЕН'
                },
                'results': []
            })

    return templates.TemplateResponse(
        'write_results.html',
        {
            'request': request,
            'title': f'Результат записи сотрудника: {employee_name}',
            'all_results': all_results,
        }
    )
@app.get('/uk', response_class=HTMLResponse)
def uk(request: Request):
    with db() as conn:
        groups = [dict(r) for r in conn.execute('SELECT * FROM uk_groups ORDER BY name')]
        panels = [dict(r) for r in conn.execute('SELECT * FROM panels WHERE enabled=1 ORDER BY address,name')]
    return templates.TemplateResponse('uk.html', {'request': request, 'groups': groups, 'panels': panels})

@app.post('/uk/group')
def uk_group(name: str = Form(...), panel_ids: list[int] = Form([]), note: str = Form('')):
    with db() as conn:
        conn.execute('INSERT INTO uk_groups(name,note) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET note=excluded.note', (name.strip(), note.strip()))
        gid = conn.execute('SELECT id FROM uk_groups WHERE name=?', (name.strip(),)).fetchone()['id']
        conn.execute('DELETE FROM uk_group_panels WHERE group_id=?', (gid,))
        conn.executemany('INSERT OR IGNORE INTO uk_group_panels(group_id,panel_id) VALUES(?,?)', [(gid, int(pid)) for pid in panel_ids])
    return RedirectResponse('/uk', status_code=303)

@app.post('/uk/write', response_class=HTMLResponse)
def uk_write(request: Request, group_id: int = Form(...), key_values: str = Form(...), flat_num: str = Form('0'), inner: int = Form(0)):
    with db() as conn:
        panels = [dict(r) for r in conn.execute('SELECT p.* FROM panels p JOIN uk_group_panels gp ON gp.panel_id=p.id WHERE gp.group_id=? AND p.enabled=1 ORDER BY p.address,p.name', (group_id,))]
    all_results = []
    for val in [x.strip() for x in key_values.replace(',', ' ').split() if x.strip()]:
        item = find_key(val)
        if item:
            all_results.append({'key': item, 'results': write_key_to_panels('uk', item, panels, flat_num=flat_num, inner=inner)})
        else:
            all_results.append({'key': {'number': val, 'hex_value': 'НЕ НАЙДЕН'}, 'results': []})
    return templates.TemplateResponse('write_results.html', {'request': request, 'title': 'Результат записи УК', 'all_results': all_results})

@app.get('/panels', response_class=HTMLResponse)
def panels_page(request: Request):
    panels = get_panels()
    return templates.TemplateResponse('panels.html', {'request': request, 'panels': panels})

@app.post('/panels/add')
def panels_add(address: str = Form(...), name: str = Form(...), mac: str = Form(...), entrance: str = Form(''), tags: str = Form('')):
    with db() as conn:
        conn.execute('INSERT INTO panels(address,entrance,name,mac,tags) VALUES(?,?,?,?,?) ON CONFLICT(mac) DO UPDATE SET address=excluded.address,entrance=excluded.entrance,name=excluded.name,tags=excluded.tags', (address.strip(), entrance.strip(), name.strip(), mac.strip().upper(), tags.strip()))
    return RedirectResponse('/panels', status_code=303)
@app.post("/panels/edit")
def panels_edit(
    panel_id: int = Form(...),
    address: str = Form(...),
    entrance: str = Form(""),
    name: str = Form(...),
    mac: str = Form(...),
    tags: str = Form(""),
):
    with db() as conn:
        conn.execute(
            """
            UPDATE panels
            SET address = ?,
                entrance = ?,
                name = ?,
                mac = ?,
                tags = ?
            WHERE id = ?
            """,
            (
                address.strip(),
                entrance.strip(),
                name.strip(),
                mac.strip().upper(),
                tags.strip(),
                panel_id,
            ),
        )

    return RedirectResponse("/panels", status_code=303)


@app.post("/panels/delete")
def panels_delete(panel_id: int = Form(...)):
    with db() as conn:
        conn.execute(
            "UPDATE panels SET enabled = 0 WHERE id = ?",
            (panel_id,),
        )

    return RedirectResponse("/panels", status_code=303)


@app.get("/panels/export")
def panels_export():
    from io import BytesIO
    from openpyxl import Workbook

    with db() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT id, address, entrance, name, mac, tags
                FROM panels
                WHERE enabled = 1
                ORDER BY address, entrance, name
                """
            )
        ]

    wb = Workbook()
    ws = wb.active
    ws.title = "Панели"

    ws.append(["ID", "Адрес", "Вход", "Панель", "MAC", "Теги"])

    for r in rows:
        ws.append([
            r["id"],
            r["address"],
            r["entrance"],
            r["name"],
            r["mac"],
            r["tags"],
        ])

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)

    return Response(
        content=stream.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="panels.xlsx"'
        },
    )

@app.post('/panels/import')
async def panels_import(file: UploadFile = File(...)):
    result = import_panels_excel(file.filename, await file.read())

    return RedirectResponse(
        f"/panels?added={result['added']}&updated={result['updated']}&skipped={result['skipped']}&errors={result['errors']}",
        status_code=303,
    )

@app.get('/keys', response_class=HTMLResponse)
def keys_page(request: Request):
    with db() as conn:
        keys = [dict(r) for r in conn.execute('SELECT * FROM keys ORDER BY id DESC LIMIT 300')]
    return templates.TemplateResponse('keys.html', {'request': request, 'keys': keys})

@app.post('/keys/import')
async def keys_import(file: UploadFile = File(...)):
    count = import_keys_file(file.filename, await file.read())
    return RedirectResponse(f'/keys?imported={count}', status_code=303)

@app.get('/log', response_class=HTMLResponse)
def log_page(request: Request):
    with db() as conn:
        rows = [dict(r) for r in conn.execute('SELECT * FROM operation_log ORDER BY id DESC LIMIT 500')]
    return templates.TemplateResponse('log.html', {'request': request, 'rows': rows})
