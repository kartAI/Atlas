from azure.storage.blob import BlobServiceClient

from config import AZURE_CONNECTION_STRING, BLOB_CONTAINER_NAME

_PDF_SUFFIXES = (".pdf", ".PDF")


def _get_container_client():
    assert AZURE_CONNECTION_STRING and BLOB_CONTAINER_NAME
    blob_service = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
    return blob_service.get_container_client(BLOB_CONTAINER_NAME)


def _is_pdf_blob_name(blob_name: str) -> bool:
    return blob_name.endswith(_PDF_SUFFIXES)


def download_blob_bytes(blob_name: str) -> bytes:
    container = _get_container_client()
    return container.download_blob(blob_name).readall()


def list_documents() -> list[str]:
    container = _get_container_client()
    return [blob.name for blob in container.list_blobs() if _is_pdf_blob_name(blob.name)]


def list_documents_with_metadata() -> list[dict]:
    container = _get_container_client()
    return [
        {
            "name": blob.name,
            "last_modified": blob.last_modified,
            "file_hash": blob.etag or "",
        }
        for blob in container.list_blobs()
        if _is_pdf_blob_name(blob.name)
    ]
