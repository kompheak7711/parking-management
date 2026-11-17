"""Joint Inspection API (DL-201, DL-243).

Reading needs `units.read`; starting, saving, photos, signatures and finishing need
`joint_inspections.record`, and starting a replacement `joint_inspections.replace`. Each change
needs the browser mutation checks; saving, files and finishing need If-Match. A photo or a
signature is a JPG, PNG or WEBP body kept in the inspection files folder by its SHA-256.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.products_api import Json, ProductConflict, ProductNotFound, ProductStale
from property_rental.settings import Settings

HEADERS = {
    "Origin": "https://localhost",
    "Cookie": "__Host-prm_csrf=inspection-token",
    "X-CSRF-Token": "inspection-token",
}
RECORD = "joint_inspections.record"
REPLACE = "joint_inspections.replace"
READ = "units.read"


@dataclass
class InMemoryInspections:
    property_id: UUID = field(default_factory=uuid4)
    inspection_id: UUID = field(default_factory=uuid4)
    version: int = 1
    status: str = "DRAFT"
    calls: list[tuple[str, object]] = field(default_factory=list)
    files: dict[UUID, Json] = field(default_factory=dict)

    def _check(self, property_id: UUID, inspection_id: UUID | None = None) -> None:
        if property_id != self.property_id or inspection_id not in (None, self.inspection_id):
            raise ProductNotFound("the Joint Inspection does not exist")

    def _changed(self, version: int) -> None:
        if version != self.version:
            raise ProductStale
        if self.status != "DRAFT":
            raise ProductConflict("This inspection is done")
        self.version += 1

    def _inspection(self) -> Json:
        return {
            "inspection_id": str(self.inspection_id),
            "inspection_number": "JI260001",
            "status": self.status,
            "version": self.version,
        }

    def inspections(self, property_id: UUID, lease_id: UUID | None, *, actor_id: str) -> list[Json]:
        self._check(property_id)
        self.calls.append(("list", lease_id))
        return [self._inspection()]

    def inspection(self, property_id: UUID, inspection_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id, inspection_id)
        return self._inspection()

    def start(self, property_id: UUID, start: Json, *, actor_id: str) -> UUID:
        self._check(property_id)
        self.calls.append(("start", start))
        return self.inspection_id

    def save(
        self, property_id: UUID, inspection_id: UUID, version: int, changes: Json, *, actor_id: str
    ) -> None:
        self._check(property_id, inspection_id)
        self._changed(version)
        self.calls.append(("save", changes))

    def add_file(
        self, property_id: UUID, inspection_id: UUID, version: int, file: Json, *, actor_id: str
    ) -> UUID:
        self._check(property_id, inspection_id)
        self._changed(version)
        made = uuid4()
        self.files[made] = file
        self.calls.append(("file", file))
        return made

    def remove_file(self, property_id: UUID, file_id: UUID, *, actor_id: str) -> None:
        self._check(property_id)
        if file_id not in self.files:
            raise ProductNotFound("the photo does not exist")
        self.calls.append(("remove", file_id))

    def file(self, property_id: UUID, file_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id)
        if file_id not in self.files:
            raise ProductNotFound("the file does not exist")
        return self.files[file_id]

    def finish(
        self, property_id: UUID, inspection_id: UUID, version: int, *, actor_id: str
    ) -> Json:
        self._check(property_id, inspection_id)
        self._changed(version)
        self.status = "DONE"
        return {"inspection_number": "JI260001", "reports": ["UP260004"], "damage_findings": 0}


def client(flow: InMemoryInspections, *capabilities: str, files: Path | None = None) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    settings = Settings(
        _env_file=None, inspection_files_directory=None if files is None else str(files)
    )
    return TestClient(
        create_app(settings=settings, actor_resolver=lambda _: who, joint_inspection_flow=flow)
    )


def base(flow: InMemoryInspections) -> str:
    return f"/api/v1/properties/{flow.property_id}"


def test_reading_joint_inspections_needs_units_read() -> None:
    flow = InMemoryInspections()
    lease = uuid4()
    for url in (
        f"{base(flow)}/joint-inspections",
        f"{base(flow)}/joint-inspections?lease_id={lease}",
        f"{base(flow)}/joint-inspections/{flow.inspection_id}",
    ):
        assert client(flow, RECORD).get(url).status_code == 403
        answer = client(flow, READ).get(url)
        assert answer.status_code == 200
        assert answer.headers["Cache-Control"] == "private, no-store"
    assert ("list", lease) in flow.calls
    missing = client(flow, READ).get(f"{base(flow)}/joint-inspections/{uuid4()}")
    assert missing.status_code == 404


def test_starting_needs_the_record_right_and_a_replacement_the_replace_right() -> None:
    flow = InMemoryInspections()
    url = f"{base(flow)}/joint-inspections"
    body = {"lease_id": str(uuid4()), "kind": "MOVE_IN"}
    staff = client(flow, READ, RECORD)
    assert client(flow, READ).post(url, json=body, headers=HEADERS).status_code == 403
    assert staff.post(url, json=body).status_code == 403  # no browser mutation checks
    assert staff.post(url, json=body | {"kind": "LATER"}, headers=HEADERS).status_code == 422
    made = staff.post(url, json=body, headers=HEADERS)
    assert made.status_code == 201 and made.json()["data"]["inspection_number"] == "JI260001"
    assert flow.calls[-1] == ("start", body | {"replaces_id": None, "reason": None})
    again = body | {"replaces_id": str(uuid4()), "reason": " Wrong key count "}
    assert staff.post(url, json=again, headers=HEADERS).status_code == 403
    manager = client(flow, READ, RECORD, REPLACE)
    assert manager.post(url, json=again, headers=HEADERS).status_code == 201
    sent = flow.calls[-1][1]
    assert isinstance(sent, dict) and sent["reason"] == "Wrong key count"


def test_saving_sends_only_what_changed_at_the_version_in_if_match() -> None:
    flow = InMemoryInspections()
    url = f"{base(flow)}/joint-inspections/{flow.inspection_id}/save"
    line = str(uuid4())
    body = {
        "lines": [{"line_id": line, "result": "BROKEN", "note": " Window latch "}],
        "keys": {"door_keys": 2, "other_keys_note": ""},
        "meters": [{"utility_type": "ELECTRICITY", "reading": "1250.5"}],
    }
    staff = client(flow, READ, RECORD)
    assert staff.post(url, json=body, headers=HEADERS).status_code == 428
    assert staff.post(url, json=body, headers=HEADERS | {"If-Match": '"7"'}).status_code == 412
    bad = body | {"meters": [{"utility_type": "ELECTRICITY", "reading": "12,5"}]}
    assert staff.post(url, json=bad, headers=HEADERS | {"If-Match": '"1"'}).status_code == 422
    bad = body | {"keys": {"door_keys": 100}}
    assert staff.post(url, json=bad, headers=HEADERS | {"If-Match": '"1"'}).status_code == 422
    saved = staff.post(url, json=body, headers=HEADERS | {"If-Match": '"1"'})
    assert saved.status_code == 200 and saved.json()["data"]["version"] == 2
    assert flow.calls[-1] == (
        "save",
        {
            "lines": [{"line_id": line, "result": "BROKEN", "note": "Window latch"}],
            "keys": {"door_keys": 2, "other_keys_note": None},
            "meters": [{"utility_type": "ELECTRICITY", "reading": "1250.5"}],
        },
    )


def test_a_photo_is_kept_by_its_hash_and_sent_back(tmp_path: Path) -> None:
    flow = InMemoryInspections()
    url = f"{base(flow)}/joint-inspections/{flow.inspection_id}/files"
    line = uuid4()
    picture = b"\x89PNG\r\n\x1a\nfake picture"
    staff = client(flow, READ, RECORD, files=tmp_path)
    png = HEADERS | {"If-Match": '"1"', "Content-Type": "image/png"}
    # Without the folder the app cannot keep a photo.
    no_folder = client(flow, READ, RECORD)
    assert no_folder.post(f"{url}?role=PHOTO", content=picture, headers=png).status_code == 503
    assert (
        staff.post(
            f"{url}?role=PHOTO", content=b"%PDF", headers=png | {"Content-Type": "application/pdf"}
        ).status_code
        == 415
    )
    assert staff.post(f"{url}?role=PHOTO", content=b"", headers=png).status_code == 422
    assert staff.post(f"{url}?role=SELFIE", content=picture, headers=png).status_code == 422
    added = staff.post(f"{url}?role=PHOTO&line_id={line}", content=picture, headers=png)
    assert added.status_code == 201
    kept = flow.calls[-1][1]
    assert isinstance(kept, dict)
    assert kept["role"] == "PHOTO" and kept["line_id"] == str(line)
    assert kept["sha256"] == hashlib.sha256(picture).hexdigest()
    assert str(kept["storage_key"]).startswith(f"inspections/{flow.inspection_id}/")
    assert (tmp_path / str(kept["storage_key"])).read_bytes() == picture

    file_id = next(iter(flow.files))
    sent = client(flow, READ, files=tmp_path).get(f"{base(flow)}/joint-inspection-files/{file_id}")
    assert sent.status_code == 200 and sent.content == picture
    assert sent.headers["Content-Type"] == "image/png"
    assert sent.headers["X-Content-Type-Options"] == "nosniff"
    removed = staff.post(f"{base(flow)}/joint-inspection-files/{file_id}/remove", headers=HEADERS)
    assert removed.status_code == 200 and flow.calls[-1] == ("remove", file_id)

    # A refused file is taken off the disk again.
    stale = staff.post(f"{url}?role=TENANT_SIGNATURE", content=picture, headers=png)
    assert stale.status_code == 412
    assert len(list((tmp_path / "inspections" / str(flow.inspection_id)).iterdir())) == 1


def test_finishing_answers_the_reports_it_made() -> None:
    flow = InMemoryInspections()
    url = f"{base(flow)}/joint-inspections/{flow.inspection_id}/finish"
    assert client(flow, READ).post(url, headers=HEADERS | {"If-Match": '"1"'}).status_code == 403
    staff = client(flow, READ, RECORD)
    done = staff.post(url, headers=HEADERS | {"If-Match": '"1"'})
    assert done.status_code == 200
    data = done.json()["data"]
    assert data["status"] == "DONE" and data["finished"]["reports"] == ["UP260004"]
    assert staff.post(url, headers=HEADERS | {"If-Match": '"2"'}).status_code == 409
