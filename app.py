import os
import tempfile
from fastapi import FastAPI, File, UploadFile, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from parser import parse_pdf, groups_to_rows
from excel_writer import create_excel

app = FastAPI(title="月结单 PDF → Excel")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return JSONResponse(status_code=400, content={"error": "请上传PDF文件"})

    # Save uploaded file to temp
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
        content = await file.read()
        tmp_pdf.write(content)
        tmp_pdf_path = tmp_pdf.name

    try:
        groups = parse_pdf(tmp_pdf_path)
        if not groups:
            return JSONResponse(status_code=400, content={"error": "未能解析出任何交易记录"})

        rows = groups_to_rows(groups, pdf_path=tmp_pdf_path)

        # Generate Excel
        out_name = file.filename.rsplit(".", 1)[0] + ".xlsx"
        tmp_xlsx = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp_xlsx.close()
        create_excel(rows, tmp_xlsx.name)

        return FileResponse(
            tmp_xlsx.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=out_name,
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"解析失败: {str(e)}"})
    finally:
        os.unlink(tmp_pdf_path)
