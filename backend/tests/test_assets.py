import pytest

from execution.storage import inspect_image
from tools.contracts.errors import AppError
from tools.contracts.models import ImageCommand, ImageInput, UploadComplete, UploadCreate


def upload(runtime, caller, project, data, key="upload"):
    request = UploadCreate(
        idempotency_key=key, title="Reference", mime_type="image/png", size_bytes=len(data)
    )
    result = runtime.commands.initiate_upload(caller, project, request).data
    runtime.commands.upload_content(caller, project, result["upload_id"], data, "image/png")
    return runtime.commands.complete_upload(
        caller, project, UploadComplete(upload_id=result["upload_id"], idempotency_key=key + "-complete")
    ).data


def test_reference_import_and_dependency_edges(runtime, alice, project, png):
    asset = upload(runtime, alice, project, png)
    command = ImageCommand(
        project_id=project,
        idempotency_key="ref-image",
        input=ImageInput(prompt="Product reveal", reference_artifact_ids=[asset["id"]]),
    )
    handle = runtime.commands.generate_image(alice, command)
    runtime.worker.execute(project, handle.job_id)
    generated = runtime.commands.get_asset(
        alice, project, runtime.commands.get_job(alice, project, handle.job_id).artifact_ids[0]
    ).data
    assert generated["input_artifact_ids"] == [asset["id"]]


@pytest.mark.parametrize("data,mime", [(b"not an image", "image/png"), (b"", "image/png")])
def test_invalid_media(data, mime):
    with pytest.raises(AppError) as exc:
        inspect_image(data, mime)
    assert exc.value.payload.code == "INVALID_MEDIA"


def test_mime_size_and_upload_expiration(runtime, alice, project, png):
    result = runtime.commands.initiate_upload(
        alice,
        project,
        UploadCreate(idempotency_key="upload", title="Logo", mime_type="image/jpeg", size_bytes=len(png)),
    ).data
    with pytest.raises(AppError):
        runtime.commands.upload_content(alice, project, result["upload_id"], png, "image/jpeg")
    with pytest.raises(AppError):
        runtime.commands.upload_content(alice, project, result["upload_id"], png[:-1], "image/jpeg")
    runtime.commands.clock.advance(301)
    with pytest.raises(AppError):
        runtime.commands.upload_content(alice, project, result["upload_id"], png, "image/jpeg")


def test_upload_completion_checks_ownership_and_missing_bytes(runtime, alice, bob, project, png):
    record = runtime.commands.initiate_upload(
        alice,
        project,
        UploadCreate(idempotency_key="upload", title="Logo", mime_type="image/png", size_bytes=len(png)),
    ).data
    request = UploadComplete(upload_id=record["upload_id"], idempotency_key="complete")
    with pytest.raises(AppError) as exc:
        runtime.commands.complete_upload(alice, project, request)
    assert exc.value.payload.code == "UPLOAD_INCOMPLETE"
    with pytest.raises(AppError):
        runtime.commands.complete_upload(bob, project, request)


def test_asset_pagination_and_cursor_validation(runtime, alice, project, png):
    for i in range(3):
        upload(runtime, alice, project, png, str(i))
    page = runtime.commands.list_assets(alice, project, limit=2)
    assert len(page.assets) == 2 and page.next_cursor
    last = runtime.commands.list_assets(alice, project, limit=2, cursor=page.next_cursor)
    assert len(last.assets) == 1 and not last.next_cursor
    assert {a["id"] for a in page.assets}.isdisjoint({a["id"] for a in last.assets})
    with pytest.raises(AppError):
        runtime.commands.list_assets(alice, project, cursor="bad-cursor")
    with pytest.raises(AppError):
        runtime.commands.list_assets(alice, project, limit=101)
