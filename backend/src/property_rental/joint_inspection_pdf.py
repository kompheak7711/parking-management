"""The Joint Inspection as an A4 PDF (DL-243 answer 6, DL-244): the copy the Tenant bot sends when
an inspection is Done, and the page staff print.

It shows what the app shows on a Done inspection: each room and item with its result and note,
the keys, the meter numbers and both signatures, in Khmer and English like the Invoice. Photos
stay in the app (the copy names how many a line has), so the file stays small enough for
Telegram. WeasyPrint draws the page because it joins Khmer letters. Nothing here reads the
database: the caller passes the inspection (``app.joint_inspection_json``) and the two signature
pictures.
"""

from __future__ import annotations

import base64
import html
from collections.abc import Mapping, Sequence
from typing import Any, Final

from .invoice_pdf import ASSETS, day_text

STYLE: Final = (ASSETS / "joint-inspection.css").read_text(encoding="utf-8")

# The app's words (frontend src/joint/text.ts), Khmer then English.
WORDS: Final[dict[str, tuple[str, str]]] = {
    "title": ("ការត្រួតពិនិត្យរួម", "Joint Inspection"),
    "MOVE_IN": ("ពេលចូល", "Move-in"),
    "MOVE_OUT": ("ពេលចាកចេញ", "Move-out"),
    "GOOD": ("ល្អ", "Good"),
    "BROKEN": ("ខូច", "Broken"),
    "MISSING": ("បាត់", "Missing"),
    "number": ("លេខ", "Number"),
    "kind": ("ប្រភេទ", "Kind"),
    "date": ("កាលបរិច្ឆេទ", "Date"),
    "tenant": ("អ្នកជួល", "Tenant"),
    "unit_lease": ("បន្ទប់ និងកិច្ចសន្យា", "Unit and Lease"),
    "rooms": ("បន្ទប់ និងរបស់របរ", "Rooms and items"),
    "item": ("របស់", "Item"),
    "result": ("លទ្ធផល", "Result"),
    "note": ("កំណត់ចំណាំ", "Note"),
    "room_itself": ("បន្ទប់ផ្ទាល់", "The room itself"),
    "keys": ("កូនសោ", "Keys"),
    "door_keys": ("កូនសោទ្វារ", "Door keys"),
    "key_cards": ("កាតសោ", "Key cards"),
    "mailbox_keys": ("កូនសោប្រអប់សំបុត្រ", "Mailbox keys"),
    "other_keys": ("ផ្សេងៗ", "Other"),
    "count": ("ចំនួន", "Count"),
    "meters": ("នាឡិកា", "Meters"),
    "ELECTRICITY": ("នាឡិកាអគ្គិសនី", "Electricity meter"),
    "WATER": ("នាឡិកាទឹក", "Water meter"),
    "meter": ("នាឡិកា", "Meter"),
    "reading": ("លេខនាឡិកា", "Meter number"),
    "signs": ("ហត្ថលេខា", "Signatures"),
    "tenant_sign": ("អ្នកជួល", "Tenant"),
    "staff_sign": ("បុគ្គលិក", "Staff member"),
}
# Words in one language only, after the Khmer line of a cell.
TENANT_CAUSED: Final = "Tenant caused · អ្នកជួលបង្ក"
PET_CAUSED: Final = "Caused by a pet · បង្កដោយសត្វចិញ្ចឹម"


def _label(key: str) -> str:
    kh, en = WORDS[key]
    return f'<span class="lbl"><span class="kh">{kh}</span><span class="en">{en}</span></span>'


def _both(key: str) -> str:
    kh, en = WORDS[key]
    return f'<span class="kh">{kh}</span>{en}'


def _text(value: Any) -> str:
    return html.escape(str(value)) if value is not None and str(value).strip() else ""


def _png(picture: bytes | None) -> str | None:
    if not picture:
        return None
    return "data:image/png;base64," + base64.b64encode(picture).decode("ascii")


def _groups(lines: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    """Lines in their order, a new group each time the room changes (as the app shows them)."""
    found: list[list[Mapping[str, Any]]] = []
    ordered = sorted(lines, key=lambda line: int(line.get("ordinal") or 0))
    for line in ordered:
        if found and found[-1][0].get("group_en") == line.get("group_en"):
            found[-1].append(line)
        else:
            found.append([line])
    return found


def _line_row(line: Mapping[str, Any], *, move_out: bool) -> str:
    if line.get("line_kind") == "PLACE":
        name = _both("room_itself")
    else:
        km = _text(line.get("item_name_km"))
        name = (f'<span class="kh">{km}</span>' if km else "") + _text(line.get("item_name"))
    quantity = line.get("quantity")
    if isinstance(quantity, int) and quantity > 1:
        name += f" \u00d7 {quantity}"
    item_type = _text(line.get("item_type_name"))
    sub = f'<span class="sub">{item_type}</span>' if item_type else ""
    result = line.get("result")
    if result in ("GOOD", "BROKEN", "MISSING"):
        kh, en = WORDS[str(result)]
        tone = "" if result == "GOOD" else " bad"
        result_html = f'<span class="res{tone}"><span class="kh">{kh}</span>{en}</span>'
    else:
        result_html = "—"
    notes: list[str] = []
    note = _text(line.get("note"))
    if note:
        notes.append(note)
    if move_out:
        before = line.get("move_in_result")
        # The move-in result is named where it matters: a problem now, or a change.
        if before in ("GOOD", "BROKEN", "MISSING") and (result != "GOOD" or before != result):
            kh, en = WORDS[str(before)]
            before_note = _text(line.get("move_in_note"))
            notes.append(
                f'<span class="sub">At move-in · ពេលចូល: {en} · {kh}'
                + (f" ({before_note})" if before_note else "")
                + "</span>"
            )
    tags: list[str] = []
    if line.get("tenant_caused"):
        tags.append(TENANT_CAUSED)
    if line.get("pet_caused"):
        tags.append(PET_CAUSED)
    report = line.get("problem_report")
    if isinstance(report, Mapping) and report.get("report_number"):
        tags.append(f"Problem report {_text(report['report_number'])}")
    photos = line.get("photos")
    if isinstance(photos, list) and photos:
        count = len(photos)
        tags.append(f"{count} photo{'s' if count > 1 else ''} in the app · រូបថត {count}")
    notes.extend(f'<span class="tag">{html.escape(tag, quote=False)}</span>' for tag in tags)
    return (
        f'<tr><td><span class="name">{name}</span>{sub}</td>'
        f"<td>{result_html}</td><td>{''.join(notes) or '—'}</td></tr>"
    )


def joint_inspection_html(
    inspection: Mapping[str, Any],
    *,
    tenant_signature: bytes | None,
    staff_signature: bytes | None,
) -> str:
    """The page as HTML: the inspection as the app shows it once Done."""
    e = _text
    number = e(inspection.get("inspection_number")) or "—"
    kind = str(inspection.get("kind") or "")
    move_out = kind == "MOVE_OUT"
    kind_html = _both(kind) if kind in WORDS else e(kind)
    unit = e(inspection.get("unit_number"))
    lease = e(inspection.get("lease_number"))
    notices: list[str] = []
    replaces = inspection.get("replaces")
    if isinstance(replaces, Mapping) and replaces.get("inspection_number"):
        reason = e(inspection.get("replace_reason"))
        notices.append(
            f"This copy replaces {e(replaces['inspection_number'])}."
            + (f" Reason: {reason}" if reason else "")
            + f' <span class="kh">ជំនួស {e(replaces["inspection_number"])}។</span>'
        )
    replaced_by = inspection.get("replaced_by")
    if isinstance(replaced_by, Mapping) and replaced_by.get("inspection_number"):
        notices.append(
            f"This inspection was replaced by {e(replaced_by['inspection_number'])}."
            f' <span class="kh">ត្រូវបានជំនួសដោយ {e(replaced_by["inspection_number"])}។</span>'
        )
    rows: list[str] = []
    for group in _groups(inspection.get("lines") or []):
        first = group[0]
        room_km = e(first.get("group_km"))
        rows.append(
            '<tr><td class="room" colspan="3">'
            + (f'<span class="kh">{room_km}</span>' if room_km else "")
            + f"{e(first.get('group_en'))}</td></tr>"
        )
        rows.extend(_line_row(line, move_out=move_out) for line in group)
    keys = inspection.get("keys") if isinstance(inspection.get("keys"), Mapping) else {}
    key_rows = []
    for key in ("door_keys", "key_cards", "mailbox_keys", "other_keys"):
        value = keys.get(key) if isinstance(keys, Mapping) else None
        extra = ""
        if key == "other_keys" and isinstance(keys, Mapping) and keys.get("other_keys_note"):
            extra = f'<span class="sub">{e(keys["other_keys_note"])}</span>'
        key_rows.append(
            f"<tr><td>{_both(key)}{extra}</td>"
            f'<td class="r">{e(value) if value is not None else "—"}</td></tr>'
        )
    meter_rows = []
    for meter in inspection.get("meters") or []:
        utility = str(meter.get("utility_type") or "")
        name = _both(utility) if utility in WORDS else e(utility)
        serial = e(meter.get("serial_number"))
        unit_code = e(meter.get("measurement_unit_code"))
        reading = e(meter.get("reading")) or "—"
        meter_rows.append(
            f"<tr><td>{name}" + (f'<span class="sub">{serial}</span>' if serial else "") + "</td>"
            f'<td class="r">{reading}{(" " + unit_code) if unit_code and reading != "—" else ""}'
            "</td></tr>"
        )
    signatures = inspection.get("signatures")
    signatures = signatures if isinstance(signatures, Mapping) else {}

    def sign_box(role: str, picture: bytes | None, words: str) -> str:
        found = signatures.get(role)
        signed_at = day_text(found.get("signed_at")) if isinstance(found, Mapping) else "—"
        who = (
            e(found.get("name")) if isinstance(found, Mapping) and found.get("name") else ""
        ) or (e(inspection.get("tenant_name")) if role == "tenant" else "")
        source = _png(picture)
        image = (
            f'<img src="{source}" alt="Signature">'
            if source
            else '<div class="none">Not signed · មិនទាន់ចុះហត្ថលេខា</div>'
        )
        return (
            f'<div class="sign">{_label(words)}{image}'
            f"<small>{who}</small><small>{signed_at}</small></div>"
        )

    done = inspection.get("done_at")
    done_by = e(inspection.get("done_by"))
    end = (
        f'<p class="end">Done {day_text(done)}' + (f" by {done_by}" if done_by else "") + "."
        f' <span class="kh">រួចរាល់ {day_text(done)}។</span> '
        "Ask the office for the photos. សូមសួរការិយាល័យសម្រាប់រូបថត។</p>"
        if done
        else ""
    )
    style = STYLE.replace("FONT_DIR", ASSETS.as_uri())
    logo = (ASSETS / "CHETANA_Logo_Horizontal_FullColor.svg").as_uri()
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{number}</title><style>{style}</style></head><body>"
        '<article class="doc" lang="en">'
        f'<div class="top"><div><img class="logo" src="{logo}" alt="CHETANA">'
        '<div class="biz"><b>CHETANA Residence</b></div></div>'
        f'<div class="title"><span class="kh">{WORDS["title"][0]}</span>'
        f'<span class="en">{WORDS["title"][1]}</span>'
        '<table class="meta">'
        f"<tr><td>{_label('number')}</td>"
        f'<td class="dd"><span class="number">{number}</span></td></tr>'
        f'<tr><td>{_label("kind")}</td><td class="dd">{WORDS.get(kind, ("", e(kind)))[1]}</td></tr>'
        f'<tr><td>{_label("date")}</td><td class="dd">{day_text(inspection.get("inspection_date"))}'
        "</td></tr></table></div></div><hr>"
        f'<div class="parties"><div>{_label("tenant")}<div class="v">'
        f"{e(inspection.get('tenant_name')) or '—'}</div></div>"
        f'<div>{_label("unit_lease")}<div class="v">'
        + (f"Unit {unit.removeprefix('Unit ')}" if unit else "—")
        + (f"<small>Lease {lease}</small>" if lease else "")
        + f"<small>{kind_html}</small></div></div></div>"
        + "".join(f'<p class="notice">{notice}</p>' for notice in notices)
        + f"<h2>{_both('rooms')}</h2>"
        f'<table class="lines"><thead><tr><th>{_label("item")}</th>'
        f"<th>{_label('result')}</th>"
        f"<th>{_label('note')}</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
        f"<h2>{_both('keys')}</h2>"
        f'<table><thead><tr><th>{_label("keys")}</th><th class="r">{_label("count")}</th>'
        f"</tr></thead><tbody>{''.join(key_rows)}</tbody></table>"
        + (
            f"<h2>{_both('meters')}</h2>"
            f'<table><thead><tr><th>{_label("meter")}</th><th class="r">{_label("reading")}</th>'
            f"</tr></thead><tbody>{''.join(meter_rows)}</tbody></table>"
            if meter_rows
            else ""
        )
        + f"<h2>{_both('signs')}</h2>"
        f'<div class="signs">{sign_box("tenant", tenant_signature, "tenant_sign")}'
        f"{sign_box('staff', staff_signature, 'staff_sign')}</div>"
        f"{end}</article></body></html>"
    )


def joint_inspection_pdf(
    inspection: Mapping[str, Any],
    *,
    tenant_signature: bytes | None,
    staff_signature: bytes | None,
) -> bytes:
    """The A4 PDF of the inspection (one page or more)."""
    # Imported here: it loads Pango, which only the sender and the print page need.
    from weasyprint import HTML  # type: ignore[import-untyped]

    page = joint_inspection_html(
        inspection, tenant_signature=tenant_signature, staff_signature=staff_signature
    )
    document = HTML(string=page, base_url=ASSETS.as_uri()).write_pdf()
    if not isinstance(document, bytes):  # pragma: no cover - write_pdf without a target
        raise ValueError("pdf_not_made")
    return document


def file_name(inspection: Mapping[str, Any]) -> str:
    """JI260005.pdf: the inspection number, safe as a file name."""
    number = "".join(
        character
        for character in str(inspection.get("inspection_number") or "inspection")
        if character.isalnum() or character in "-_"
    )
    return f"{number or 'inspection'}.pdf"
