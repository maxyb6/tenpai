"""6.1 Portfolio health: import, column mapping, health check, PDF."""
import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import Ctx, ctx
from app.config import ROOT, SAMPLE_DATA_DIR
from app.ingest import pipeline
from app.ingest.canonical import FIELDS_BY_KIND
from app.models import ColumnMapping, ImportBatch
from app.services import pdf
from app.services.health import health_check, visit_list_csv

router = APIRouter(prefix="/api/t/{tenant_id}")
UPLOADS = ROOT / "uploads"
KINDS = ("loans", "schedule", "savings")


def _fields(kind):
    return [{"key": f.key, "label": f.label, "kind": f.kind, "required": f.required, "help": f.help}
            for f in FIELDS_BY_KIND[kind]]


@router.post("/imports/preview")
async def preview(c: Ctx = Depends(ctx), loans: UploadFile = File(...), schedule: UploadFile | None = File(None),
                  savings: UploadFile | None = File(None)):
    c.require("head_of_collections")
    upload_id = uuid.uuid4().hex
    folder = UPLOADS / c.tenant.id / upload_id
    folder.mkdir(parents=True)
    saved = list(c.session.scalars(select(ColumnMapping).where(ColumnMapping.tenant_id == c.tenant.id)))
    out = {"upload_id": upload_id, "files": {}}
    for kind, up in (("loans", loans), ("schedule", schedule), ("savings", savings)):
        if up is None or not up.filename:
            continue
        content = await up.read()
        name = Path(up.filename).name
        (folder / f"{kind}__{name}").write_bytes(content)
        try:
            headers, rows = pipeline.read_table(content, name)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Could not read {name}: {e}")
        mine = [m for m in saved if m.file_kind == kind]
        suggestion = pipeline.suggest_mapping(headers, kind, [m.mapping for m in mine])
        matched = next((m.name for m in mine if all(
            m.mapping.get(k) == v for k, v in suggestion.items() if v)), None)
        out["files"][kind] = {
            "filename": name, "headers": headers, "rows": len(rows),
            "sample": [{h: str(r.get(h, "")) for h in headers} for r in rows[:5]],
            "fields": _fields(kind), "mapping": suggestion,
            "saved_mappings": [{"name": m.name, "mapping": m.mapping} for m in mine],
            "matched_saved": matched,
        }
    return out


class CommitBody(BaseModel):
    upload_id: str
    mappings: dict[str, dict[str, str | None]]
    anonymise: bool = False
    save_mapping_as: str | None = None


@router.post("/imports/commit")
def commit(body: CommitBody, c: Ctx = Depends(ctx)):
    c.require("head_of_collections")
    folder = UPLOADS / c.tenant.id / body.upload_id
    if not folder.is_dir():
        raise HTTPException(404, "upload expired; upload the file again")
    files = {}
    for p in folder.iterdir():
        kind, _, name = p.name.partition("__")
        files[kind] = (name, p.read_bytes())
    for kind, mapping in body.mappings.items():
        missing = [f.key for f in FIELDS_BY_KIND[kind] if f.required and not mapping.get(f.key)]
        if missing and kind in files:
            raise HTTPException(400, f"{kind}: map required fields {', '.join(missing)}")
    result = pipeline.import_files(c.session, c.tenant, files, mappings=body.mappings, anonymise=body.anonymise,
                                   actor=c.actor)
    if body.save_mapping_as:
        for kind, mapping in body.mappings.items():
            if kind not in files:
                continue
            existing = c.session.scalars(select(ColumnMapping).where(
                ColumnMapping.tenant_id == c.tenant.id, ColumnMapping.file_kind == kind,
                ColumnMapping.name == body.save_mapping_as)).first()
            clean = {k: v for k, v in mapping.items() if v}
            if existing:
                existing.mapping = clean
            else:
                c.session.add(ColumnMapping(tenant_id=c.tenant.id, name=body.save_mapping_as, file_kind=kind,
                                            mapping=clean))
    shutil.rmtree(folder, ignore_errors=True)
    return result


@router.get("/imports")
def batches(c: Ctx = Depends(ctx)):
    rows = c.session.scalars(select(ImportBatch).where(ImportBatch.tenant_id == c.tenant.id)
                             .order_by(ImportBatch.id.desc()).limit(30))
    return [{"id": b.id, "filename": b.filename, "kind": b.file_kind, "rows": b.row_count,
             "accepted": b.accepted_count, "anonymised": b.anonymised, "as_of": b.as_of and b.as_of.isoformat(),
             "created_at": b.created_at.isoformat(), "created_by": b.created_by,
             "report": {k: v for k, v in (b.report or {}).items() if k != "issues"},
             "issues": (b.report or {}).get("issues", [])[:200]} for b in rows]


@router.get("/health")
def health(c: Ctx = Depends(ctx)):
    return health_check(c.session, c.tenant)


@router.get("/health/visit-list.csv")
def health_csv(c: Ctx = Depends(ctx)):
    hc = health_check(c.session, c.tenant)
    return Response(visit_list_csv(hc), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="visit-list-{hc["as_of"]}.csv"'})


@router.get("/health.pdf")
def health_pdf(c: Ctx = Depends(ctx)):
    hc = health_check(c.session, c.tenant)
    return Response(pdf.health_check_pdf(c.tenant, hc), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="health-check-{hc["as_of"]}.pdf"'})


sample_router = APIRouter()


@sample_router.get("/api/sample-files")
def sample_files():
    return sorted(p.name for p in SAMPLE_DATA_DIR.glob("*.csv"))


@sample_router.get("/api/sample-files/{name}")
def sample_file(name: str):
    p = SAMPLE_DATA_DIR / Path(name).name
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="text/csv", filename=p.name)
