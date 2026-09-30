from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from config import get_settings
from storage.models import FileMetadata
from storage.store import FileStorage

router = APIRouter()


def _storage() -> FileStorage:
    return FileStorage(get_settings().STORAGE_PATH)


@router.post("/", response_model=FileMetadata)
async def upload_file(file: UploadFile = File(...)) -> FileMetadata:
    data = await file.read()
    return FileMetadata(**_storage().save(data, file.filename or ""))


@router.get("/", response_model=list[FileMetadata])
async def list_files() -> list[FileMetadata]:
    return [FileMetadata(**m) for m in _storage().list_all()]


@router.get("/{file_id}/meta", response_model=FileMetadata)
async def get_meta(file_id: str) -> FileMetadata:
    meta = _storage().get_meta(file_id)
    if not meta:
        raise HTTPException(404, "File not found")
    return FileMetadata(**meta)


@router.get("/{file_id}")
async def download_file(file_id: str) -> Response:
    data = _storage().get_bytes(file_id)
    if data is None:
        raise HTTPException(404, "File not found")
    meta = _storage().get_meta(file_id)
    filename = (meta or {}).get("filename") or file_id
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{file_id}")
async def delete_file(file_id: str) -> dict:
    if not _storage().delete(file_id):
        raise HTTPException(404, "File not found")
    return {"deleted": file_id}
