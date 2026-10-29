# Known failures (pre-existing, not caused by Parking work)

Checked on 2026-10-29 on this Mac mini (macOS, Node v26.10.0, Python 3.11 via uv). Each one
fails the same way on an untouched copy of Property Rental at commit df3ec76
(`implementation/foundation`, 2026-10-28). Parking does not fix them; the fix belongs in
Property Rental first and is copied afterwards.

Every step report must say "same 3 known failures, no new failures", or name any new one.

## 1. Front end: TEST-FE-894 (`frontend/src/utilityClient.test.tsx`)

```
FAIL  src/utilityClient.test.tsx > Utility client > TEST-FE-894 sends a readings file to be read, parses its rows and problem, and downloads the blank file
TypeError: blob.text is not a function
```

Proof on untouched Property Rental df3ec76 (`npx vitest run src/utilityClient.test.tsx`):
`Tests  1 failed | 11 passed (12)` with the same `TypeError: blob.text is not a function`.
Cause: the test browser stand-in (jsdom 27) on this Node version has no `Blob.text()`.

## 2. Backend: `tests/test_local_run_scripts.py::test_the_owner_set_up_says_whether_the_owner_was_made`

```
>           assert result.returncode == code
E           assert 1 == 0
```

Proof on untouched Property Rental df3ec76 (`uv run pytest tests/test_local_run_scripts.py::test_the_owner_set_up_says_whether_the_owner_was_made`):
`E   assert 1 == 0` (same line). The test's copied repository lacks a file the script needs,
so the script exits 1 before the "made" message.

## 3. Backend type check: `src/property_rental/backup_job.py:537`

```
src/property_rental/backup_job.py:537: error: Module has no attribute
Found 1 error in 1 file (checked 528 source files)
```

Proof on untouched Property Rental df3ec76 (`uv run mypy src`): `mypy: 1 errors in 1 files`,
`L537: Module has no attribute`. Cause: `os.posix_fadvise` exists on Linux only; the check
runs on macOS.
