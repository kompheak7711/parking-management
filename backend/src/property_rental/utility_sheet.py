"""V1-058 R4c: the meter-readings spreadsheet (DESIGN.md "Import from a spreadsheet").

The file has one row for each Unit and the columns Unit, Electricity and Water (owner,
22/10/2026). V1.1 part 7 (DL-124, owner 30/10/2026): two more columns, "Electricity broken" and
"Water broken", say yes or no (no by default); yes means no reading and the meter is broken.
A file without them still reads, with every meter working. These helpers only turn a file into
rows and rows into a blank file; they read and change nothing in the database. Each reading is
checked again when it is saved, the same as a typed reading.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 500
# An .xlsx is a zip; a small file can unpack to gigabytes, so each part and the whole file
# are checked before it is opened.
MAX_PART_BYTES = 10 * 1024 * 1024
MAX_UNPACKED_BYTES = 20 * 1024 * 1024
MAX_PARTS = 200
# A header further right than this is not looked for; it keeps a huge sheet cheap to read.
MAX_COLUMNS = 26
COLUMNS = ("unit", "electricity", "water")
BROKEN_COLUMNS = ("electricity broken", "water broken")

SheetProblem = Literal["FILE_TYPE", "UNREADABLE", "COLUMNS", "TOO_MANY_ROWS", "EMPTY"]


@dataclass(frozen=True)
class SheetRow:
    row: int
    unit: str
    electricity: str
    water: str
    electricity_broken: str = ""
    water_broken: str = ""


class SheetError(ValueError):
    def __init__(self, problem: SheetProblem) -> None:
        super().__init__(problem)
        self.problem: SheetProblem = problem


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        number = Decimal(repr(value))
        return format(number.normalize(), "f") if number == number.to_integral() else repr(value)
    return str(value).strip()


class _Rows:
    """The rows that are not empty, with their row numbers. Empty rows are not counted, so a
    sheet formatted far down still fits; more than one header and MAX_ROWS rows is refused."""

    def __init__(self) -> None:
        self.items: list[tuple[int, list[object]]] = []

    def add(self, number: int, values: list[object]) -> None:
        if not any(_text(cell) for cell in values):
            return
        if len(self.items) > MAX_ROWS:
            raise SheetError("TOO_MANY_ROWS")
        self.items.append((number, values))


def _rows(cells: _Rows) -> list[SheetRow]:
    # The header is the first row that is not empty; its three names may be in any order.
    if not cells.items:
        raise SheetError("EMPTY")
    # "unit" is the header of files downloaded before the Parking wording; both names are read.
    names = [_text(cell).lower() for cell in cells.items[0][1]]
    names = ["parking" if name == "unit" else name for name in names]
    if any(name not in names for name in COLUMNS):
        raise SheetError("COLUMNS")
    where = {name: names.index(name) for name in COLUMNS + BROKEN_COLUMNS if name in names}
    found: list[SheetRow] = []
    for number, row in cells.items[1:]:
        values = [
            _text(row[where[name]]) if name in where and where[name] < len(row) else ""
            for name in COLUMNS + BROKEN_COLUMNS
        ]
        # A row with only "no" in the broken columns is an empty row of the blank file.
        if not any(values[:3]) and all(value.lower() in ("", "no") for value in values[3:]):
            continue
        found.append(
            SheetRow(
                row=number,
                unit=values[0],
                electricity=values[1],
                water=values[2],
                electricity_broken=values[3],
                water_broken=values[4],
            )
        )
    if not found:
        raise SheetError("EMPTY")
    return found


def _check_zip(content: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            parts = archive.infolist()
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise SheetError("UNREADABLE") from exc
    if (
        len(parts) > MAX_PARTS
        or any(part.file_size > MAX_PART_BYTES for part in parts)
        or sum(part.file_size for part in parts) > MAX_UNPACKED_BYTES
    ):
        raise SheetError("UNREADABLE")


def read_sheet(file_name: str, content: bytes) -> list[SheetRow]:
    """The rows of an .xlsx or .csv file, with each cell as the text a person sees."""
    if len(content) > MAX_FILE_BYTES:
        raise SheetError("UNREADABLE")
    kind = file_name.lower().rsplit(".", 1)[-1]
    cells = _Rows()
    if kind == "csv":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SheetError("UNREADABLE") from exc
        # Excel in many countries saves a .csv with ";" between the columns.
        first = next((line for line in text.splitlines() if line.strip()), "")
        delimiter = ";" if ";" in first and "," not in first else ","
        try:
            for number, line in enumerate(
                csv.reader(io.StringIO(text), delimiter=delimiter), start=1
            ):
                cells.add(number, list(line[:MAX_COLUMNS]))
        except csv.Error as exc:
            raise SheetError("UNREADABLE") from exc
    elif kind == "xlsx":
        _check_zip(content)
        try:
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as exc:  # a broken file can fail in many ways inside openpyxl
            raise SheetError("UNREADABLE") from exc
        try:
            sheet = workbook.worksheets[0]
            for number, values in enumerate(
                sheet.iter_rows(max_col=MAX_COLUMNS, values_only=True), start=1
            ):
                cells.add(number, list(values))
        except SheetError:
            raise
        except Exception as exc:  # broken XML inside the zip, and the like
            raise SheetError("UNREADABLE") from exc
        finally:
            workbook.close()
    else:
        raise SheetError("FILE_TYPE")
    return _rows(cells)


def blank_sheet(units: list[str]) -> bytes:
    """An .xlsx file with every Unit filled in, so staff type only the readings."""
    workbook = Workbook()
    sheet = workbook.active
    if sheet is None:  # pragma: no cover - a new Workbook always has one sheet
        raise RuntimeError("New workbook has no sheet")
    sheet.title = "Readings"
    sheet.append(["Unit", "Electricity", "Electricity broken", "Water", "Water broken"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for unit in units:
        sheet.append([unit, None, "no", None, "no"])
        # A Unit is always text, so a name that starts with "=" never becomes a formula.
        sheet.cell(row=sheet.max_row, column=1).data_type = "s"
    # The broken columns offer only yes and no.
    if units:
        choice = DataValidation(type="list", formula1='"yes,no"', allow_blank=True)
        sheet.add_data_validation(choice)
        last = len(units) + 1
        choice.add(f"C2:C{last}")
        choice.add(f"E2:E{last}")
    sheet.column_dimensions["A"].width = 12
    for column in ("B", "C", "D", "E"):
        sheet.column_dimensions[column].width = 18
    sheet.freeze_panes = "A2"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
