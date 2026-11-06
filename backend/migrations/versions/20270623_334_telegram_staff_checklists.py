# ruff: noqa: E501
"""Telegram bots, step 4d: the daily checklists in the Staff bot and the 18:00 summary (DL-177).

Owner rules (24-25 Oct 2026, staff checklists; staff forms mock-up v14, approved 3 Nov 2026):

1. Three daily checklists, Khmer only: Cleaning daily check (cleaners), Caretaker shift check
   (Property Caretakers, one per shift: Morning, Afternoon, Night) and Technical daily check
   (the Technician). The Owner and the Managers (Authorizers) may send each of them.
2. Each task is answered Done or Not done (Cleaning), Done or Problem (Caretakers), Good or Needs
   fixing (Technical), with an optional short note. Tasks only for some days show only on those
   days; caretaker tasks only for some shifts show only on those shifts.
3. Caretakers send each patrol round (3 or 4 a shift) with the places they walked; the time is
   the real time the office received it. A caretaker's shift comes from HR (the weekly plan, else
   the usual shift) and cannot be changed in the form.
4. At 18:00 (Property time) the Authorizers get one summary in the Staff bot: who sent the
   cleaning and technical checks, missed patrol rounds and missing shift checks of the last 24
   hours, the tasks not done or with a problem, and the incidents.

The task lists are the draft lists of the mock-up (the owner will send the real lists): they live
in ``staff_checklists`` and ``staff_checklist_items`` with a version, so a new list is a new
version and the sent checks keep the version they used. Tables, all append-only:
``staff_checklists``, ``staff_checklist_items``, ``staff_checklist_reports``,
``staff_patrol_rounds`` and ``staff_summary_runs``. Technical choices by Claude under the owner's
2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270623_334"
down_revision: str | None = "20270622_333"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVERY = None
MON, TUE, WED, THU, FRI, SAT = 1, 2, 3, 4, 5, 6

# One task: key, section number, section name, text, days of the week (None: every day), shifts
# (None: every shift), asks the floor.
Item = tuple[str, int, str, str, tuple[int, ...] | None, tuple[str, ...] | None, bool]
# code, kind, name, extras, sort order, the tasks.
CHECKLISTS: tuple[tuple[str, str, str, tuple[str, ...], int, tuple[Item, ...]], ...] = (
    (
        "CLEAN_BUILDING",
        "CLEANING",
        "បញ្ជីសម្អាតប្រចាំថ្ងៃ · អគារចេតនា",
        ("OUT_UNITS", "PROBLEMS", "SUPPLIES"),
        1,
        (
            ("d1", 1, "រាល់ថ្ងៃ", "យកសំរាម (07:00)", EVERY, None, False),
            ("d2", 1, "រាល់ថ្ងៃ", "ជាន់ផ្ទាល់ដី៖ បោសឥដ្ឋ និងជញ្ជាំង ជូតឥដ្ឋ", EVERY, None, False),
            ("d3", 1, "រាល់ថ្ងៃ", "ជាន់ផ្ទាល់ដី៖ ទ្វារកញ្ចក់ និងជញ្ជាំងកញ្ចក់", EVERY, None, False),
            ("d4", 1, "រាល់ថ្ងៃ", "ជាន់ទី 1-5៖ បោសឥដ្ឋ ជញ្ជាំង ជណ្តើរ និងសំបុកពីងពាង", EVERY, None, False),
            ("d5", 1, "រាល់ថ្ងៃ", "លាងសម្អាត និងទុកសម្ភារៈក្នុងឃ្លាំង (11:00)", EVERY, None, False),
            ("b1", 2, "ការងារថ្ងៃនេះ", "បន្ទប់គេង និងបន្ទប់ទឹកឪពុកម្តាយ (ព្រឹក)", (MON,), None, False),
            ("b2", 2, "ការងារថ្ងៃនេះ", "បន្ទប់គេងផ្សេងទៀត និងបន្ទប់ទឹក (រសៀល)", (MON,), None, False),
            ("b3", 2, "ការងារថ្ងៃនេះ", "ជូតឥដ្ឋ និងប៊ូតុងជណ្តើរយន្ត ជាន់ទី 1-5", (TUE, THU, SAT), None, False),
            ("b4", 2, "ការងារថ្ងៃនេះ", "សម្អាតជាន់ឲ្យស្អាតល្អ", (WED, FRI), None, True),
        ),
    ),
    (
        "CLEAN_HOUSE",
        "CLEANING",
        "បញ្ជីសម្អាតប្រចាំថ្ងៃ · ផ្ទះ 103",
        ("MARKET_RIEL", "PROBLEMS"),
        2,
        (
            ("d1", 1, "រាល់ថ្ងៃ", "រៀបចំអាហារពេលព្រឹក កាហ្វេ និងផ្លែឈើ", EVERY, None, False),
            ("d2", 1, "រាល់ថ្ងៃ", "លាងចាន និងពែង", EVERY, None, False),
            ("d3", 1, "រាល់ថ្ងៃ", "បោសបន្ទប់ទទួលភ្ញៀវ", EVERY, None, False),
            ("d4", 1, "រាល់ថ្ងៃ", "ទៅផ្សារ និងរក្សាបង្កាន់ដៃ (09:00)", EVERY, None, False),
            ("d5", 1, "រាល់ថ្ងៃ", "លាងសម្អាត និងទុកសម្ភារៈក្នុងឃ្លាំង (11:00)", EVERY, None, False),
            ("b1", 2, "ការងារថ្ងៃនេះ", "បន្ទប់គេង និងបន្ទប់ទឹកឪពុកម្តាយ (ព្រឹក)", (MON,), None, False),
            ("b2", 2, "ការងារថ្ងៃនេះ", "បន្ទប់ទទួលភ្ញៀវ និងបន្ទប់ទឹក (រសៀល)", (MON,), None, False),
            (
                "b3",
                2,
                "ការងារថ្ងៃនេះ",
                "ជាន់ផ្ទាល់ដី បន្ទប់ទទួលភ្ញៀវ និងផ្ទះបាយ៖ បោសឥដ្ឋ ជញ្ជាំង ជណ្តើរ និងសំបុកពីងពាង",
                (TUE, WED, THU, FRI, SAT),
                None,
                False,
            ),
        ),
    ),
    (
        "CARETAKER",
        "CARETAKER",
        "បញ្ជីវេនប្រចាំថ្ងៃ",
        ("VISITORS", "BROKEN", "INCIDENT"),
        3,
        (
            ("h1", 1, "ផ្ទេរវេន", "ទទួលសោ និងសៀវភៅកត់ត្រា", EVERY, None, False),
            ("h2", 1, "ផ្ទេរវេន", "អានកំណត់ត្រារបស់វេនមុន", EVERY, None, False),
            ("g1", 2, "ទ្វារធំ និងភ្លើង", "បើកទ្វារធំ 06:00", EVERY, ("NIGHT",), False),
            ("g2", 2, "ទ្វារធំ និងភ្លើង", "បើកភ្លើងខាងក្រៅ 18:00", EVERY, ("AFTERNOON",), False),
            ("g3", 2, "ទ្វារធំ និងភ្លើង", "បិទទ្វារធំ 22:00", EVERY, ("AFTERNOON",), False),
            ("c1", 3, "ការងារសម្អាត", "ចំណត តំបន់ A និង B", EVERY, ("MORNING",), False),
            ("c2", 3, "ការងារសម្អាត", "ចំណត តំបន់ C និង D", EVERY, ("AFTERNOON",), False),
            ("c3", 3, "ការងារសម្អាត", "ស្រោចសួន", EVERY, ("MORNING", "AFTERNOON"), False),
            ("c4", 3, "ការងារសម្អាត", "លាងធុងសំរាម ក្រោយឡានសំរាម (ពាក់ស្រោមដៃ)", EVERY, ("NIGHT",), False),
            ("c5", 3, "ការងារសម្អាត", "ការងារពីអ្នកគ្រប់គ្រង", EVERY, None, False),
        ),
    ),
    (
        "TECHNICAL",
        "TECHNICAL",
        "បញ្ជីបច្ចេកទេសប្រចាំថ្ងៃ",
        ("FIXED_TODAY", "PARTS"),
        4,
        (
            ("a1", 1, "អគារចេតនា (07:30)", "ជណ្តើរយន្ត៖ ទ្វារ ប៊ូតុង សំឡេងរោទ៍", EVERY, None, False),
            ("a2", 1, "អគារចេតនា (07:30)", "ម៉ាស៊ីនបូមទឹក (សំឡេង និងសម្ពាធ)", EVERY, None, False),
            (
                "a3",
                1,
                "អគារចេតនា (07:30)",
                "បន្ទប់អគ្គិសនី គ្មានក្លិនឆេះ ឬក្តៅ (មើលតែប៉ុណ្ណោះ)",
                EVERY,
                None,
                False,
            ),
            ("a4", 1, "អគារចេតនា (07:30)", "អំពូលភ្លើងកន្លែងរួម", EVERY, None, False),
            ("a5", 1, "អគារចេតនា (07:30)", "បង្គន់រួម 2 គ្មានលេចទឹក", EVERY, None, False),
            ("p1", 2, "បន្ទប់ជួល និងចំណតរថយន្ត (08:30)", "ទ្វារធំ និងសោ", EVERY, None, False),
            ("p2", 2, "បន្ទប់ជួល និងចំណតរថយន្ត (08:30)", "អំពូលភ្លើង", EVERY, None, False),
            ("p3", 2, "បន្ទប់ជួល និងចំណតរថយន្ត (08:30)", "ម៉ាស៊ីនបូមទឹក", EVERY, None, False),
            ("p4", 2, "បន្ទប់ជួល និងចំណតរថយន្ត (08:30)", "លូទឹកហូរល្អ", EVERY, None, False),
        ),
    ),
)
# Patrol rounds (sample times of the mock-up) and the places walked.
PATROL_TIMES = '{"MORNING": ["08:30", "11:30", "14:00"], "AFTERNOON": ["15:00", "20:00", "22:00"], "NIGHT": ["23:00", "01:30", "03:00", "05:00"]}'
PATROL_PLACES = (
    '[{"k": "CHETANA", "t": "ចេតនា"}, {"k": "RENTAL", "t": "បន្ទប់ជួល"}, {"k": "PARKING", "t": "ចំណត"}]'
)
EXTRAS = (
    "OUT_UNITS",
    "PROBLEMS",
    "SUPPLIES",
    "MARKET_RIEL",
    "VISITORS",
    "BROKEN",
    "INCIDENT",
    "FIXED_TODAY",
    "PARTS",
)


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _seed() -> str:
    statements = []
    for code, kind, name, extras, order, items in CHECKLISTS:
        caretaker = kind == "CARETAKER"
        statements.append(
            "INSERT INTO app.staff_checklists (code, version, kind, name_km, extras, patrol_times, "
            f"patrol_places, sort_order) VALUES ({_text(code)}, 1, {_text(kind)}, {_text(name)}, "
            f"ARRAY[{', '.join(_text(extra) for extra in extras)}]::text[], "
            f"{_text(PATROL_TIMES) + '::jsonb' if caretaker else 'NULL'}, "
            f"{_text(PATROL_PLACES) + '::jsonb' if caretaker else 'NULL'}, {order});"
        )
        for position, (key, section, section_name, task, days, shifts, floor) in enumerate(
            items, start=1
        ):
            day_list = "NULL" if days is None else f"ARRAY{list(days)}::smallint[]"
            shift_list = (
                "NULL"
                if shifts is None
                else "ARRAY[" + ", ".join(_text(shift) for shift in shifts) + "]::text[]"
            )
            statements.append(
                "INSERT INTO app.staff_checklist_items (checklist_id, item_key, section_number, "
                "section_km, sort_order, text_km, iso_days, shifts, asks_floor) "
                f"SELECT checklist.id, {_text(key)}, {section}, {_text(section_name)}, "
                f"{position}, {_text(task)}, {day_list}, {shift_list}, {floor} "
                f"FROM app.staff_checklists AS checklist WHERE checklist.code = {_text(code)} "
                "AND checklist.version = 1;"
            )
    return "\n".join(statements)


TABLES = f"""
    CREATE TABLE app.staff_checklists (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        code text NOT NULL CHECK (code ~ '^[A-Z][A-Z0-9_]{{1,40}}$'),
        version integer NOT NULL CHECK (version > 0),
        kind text NOT NULL CHECK (kind IN ('CLEANING', 'CARETAKER', 'TECHNICAL')),
        name_km text NOT NULL CHECK (name_km = btrim(name_km) AND length(name_km) BETWEEN 1 AND 120),
        extras text[] NOT NULL DEFAULT '{{}}'
            CHECK (extras <@ ARRAY[{", ".join(_text(extra) for extra in EXTRAS)}]::text[]),
        patrol_times jsonb CHECK (jsonb_typeof(patrol_times) = 'object'),
        patrol_places jsonb CHECK (jsonb_typeof(patrol_places) = 'array'),
        sort_order smallint NOT NULL CHECK (sort_order > 0),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT staff_checklists_version UNIQUE (code, version),
        CONSTRAINT staff_checklists_patrols CHECK (
            (kind = 'CARETAKER') = (patrol_times IS NOT NULL)
            AND (kind = 'CARETAKER') = (patrol_places IS NOT NULL))
    );
    COMMENT ON TABLE app.staff_checklists IS
        'Telegram bots step 4d (DL-177): one version of a daily checklist of the Staff bot; the newest version of a code is the one staff see.';

    CREATE TABLE app.staff_checklist_items (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        checklist_id uuid NOT NULL REFERENCES app.staff_checklists (id) ON DELETE RESTRICT,
        item_key text NOT NULL CHECK (item_key ~ '^[a-z][a-z0-9_]{{0,30}}$'),
        section_number smallint NOT NULL CHECK (section_number BETWEEN 1 AND 20),
        section_km text NOT NULL
            CHECK (section_km = btrim(section_km) AND length(section_km) BETWEEN 1 AND 120),
        sort_order smallint NOT NULL CHECK (sort_order > 0),
        text_km text NOT NULL CHECK (text_km = btrim(text_km) AND length(text_km) BETWEEN 1 AND 200),
        iso_days smallint[] CHECK (cardinality(iso_days) > 0
            AND iso_days <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]),
        months smallint[] CHECK (cardinality(months) > 0
            AND months <@ ARRAY[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]::smallint[]),
        month_days smallint[] CHECK (cardinality(month_days) > 0
            AND 1 <= ALL (month_days) AND 31 >= ALL (month_days)),
        shifts text[] CHECK (cardinality(shifts) > 0
            AND shifts <@ ARRAY['MORNING', 'AFTERNOON', 'NIGHT']::text[]),
        asks_floor boolean NOT NULL DEFAULT false,
        CONSTRAINT staff_checklist_items_key UNIQUE (checklist_id, item_key),
        CONSTRAINT staff_checklist_items_order UNIQUE (checklist_id, sort_order)
    );
    COMMENT ON TABLE app.staff_checklist_items IS
        'Telegram bots step 4d (DL-177): one task of a checklist version, with the days, months, days of the month and shifts it is due.';

    CREATE TABLE app.staff_checklist_reports (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        inbound_event_id uuid NOT NULL UNIQUE
            REFERENCES app.telegram_inbound_events (id) ON DELETE RESTRICT,
        checklist_id uuid NOT NULL REFERENCES app.staff_checklists (id) ON DELETE RESTRICT,
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        work_date date NOT NULL,
        shift_code text REFERENCES app.work_shifts (code) ON DELETE RESTRICT,
        answers jsonb NOT NULL CHECK (jsonb_typeof(answers) = 'object'),
        floor_label text CHECK (floor_label = btrim(floor_label) AND length(floor_label) BETWEEN 1 AND 20),
        extras jsonb NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(extras) = 'object'),
        done_count smallint NOT NULL CHECK (done_count >= 0),
        problem_count smallint NOT NULL CHECK (problem_count >= 0),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX staff_checklist_reports_day_idx
        ON app.staff_checklist_reports (property_id, work_date, created_at);
    COMMENT ON TABLE app.staff_checklist_reports IS
        'Telegram bots step 4d (DL-177): one daily checklist sent in the Staff bot; a check sent again for the same day (and shift) is a new row, and the newest counts.';

    CREATE TABLE app.staff_patrol_rounds (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        inbound_event_id uuid NOT NULL UNIQUE
            REFERENCES app.telegram_inbound_events (id) ON DELETE RESTRICT,
        checklist_id uuid NOT NULL REFERENCES app.staff_checklists (id) ON DELETE RESTRICT,
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        work_date date NOT NULL,
        shift_code text NOT NULL REFERENCES app.work_shifts (code) ON DELETE RESTRICT,
        round_time time NOT NULL,
        places text[] NOT NULL CHECK (cardinality(places) > 0),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT staff_patrol_rounds_once UNIQUE (property_id, work_date, shift_code, round_time)
    );
    COMMENT ON TABLE app.staff_patrol_rounds IS
        'Telegram bots step 4d (DL-177): one patrol round a caretaker sent, at the real time the office received it.';

    CREATE TABLE app.staff_summary_runs (
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        work_date date NOT NULL,
        details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object'),
        messages integer NOT NULL CHECK (messages >= 0),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        PRIMARY KEY (property_id, work_date)
    );
    COMMENT ON TABLE app.staff_summary_runs IS
        'Telegram bots step 4d (DL-177): the 18:00 summary of a day, sent once to the Authorizers.';
"""

TRIGGERS = "\n".join(
    f"""
    CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON app.{table}
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON app.{table}
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();"""
    for table in (
        "staff_checklists",
        "staff_checklist_items",
        "staff_checklist_reports",
        "staff_patrol_rounds",
        "staff_summary_runs",
    )
)

FUNCTIONS = """
    -- The newest version of each checklist.
    CREATE FUNCTION app.staff_live_checklists() RETURNS SETOF app.staff_checklists
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT DISTINCT ON (checklist.code) checklist.*
        FROM app.staff_checklists AS checklist
        ORDER BY checklist.code, checklist.version DESC
    $$;

    -- Is a task due on a day (and a shift; NULL shift: any shift)?
    CREATE FUNCTION app.staff_item_due(p_item app.staff_checklist_items, p_day date, p_shift text)
    RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT (p_item.iso_days IS NULL OR extract(isodow FROM p_day)::smallint = ANY (p_item.iso_days))
            AND (p_item.months IS NULL OR extract(month FROM p_day)::smallint = ANY (p_item.months))
            AND (p_item.month_days IS NULL OR extract(day FROM p_day)::smallint = ANY (p_item.month_days))
            AND (p_shift IS NULL OR p_item.shifts IS NULL OR p_shift = ANY (p_item.shifts))
    $$;

    -- A caretaker's shift now (from HR): the planned shift of today or yesterday whose time,
    -- from 30 minutes before the start to 2 hours after the end, holds the moment.
    CREATE FUNCTION app.staff_duty(p_employee uuid, p_now timestamptz)
    RETURNS TABLE (work_date date, shift_code text) ROWS 1
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT day.work_date, shift.shift_code
        FROM (VALUES (timezone(app.hr_zone(), p_now)::date),
                     (timezone(app.hr_zone(), p_now)::date - 1)) AS day (work_date)
        CROSS JOIN LATERAL app.hr_shift_on(p_employee, day.work_date) AS shift
        CROSS JOIN LATERAL app.hr_shift_times(shift.shift_code, day.work_date) AS times
        WHERE shift.shift_code IS NOT NULL
          AND p_now >= times.starts_at - interval '30 minutes'
          AND p_now < times.ends_at + interval '2 hours'
        ORDER BY times.starts_at DESC
        LIMIT 1
    $$;

    -- The day of a shift an Authorizer picks: the day whose shift holds the moment, else today.
    CREATE FUNCTION app.staff_shift_day(p_shift text, p_now timestamptz) RETURNS date
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT COALESCE((
            SELECT day.work_date
            FROM (VALUES (timezone(app.hr_zone(), p_now)::date),
                         (timezone(app.hr_zone(), p_now)::date - 1)) AS day (work_date)
            CROSS JOIN LATERAL app.hr_shift_times(p_shift, day.work_date) AS times
            WHERE p_now >= times.starts_at - interval '30 minutes'
              AND p_now < times.ends_at + interval '2 hours'
            ORDER BY times.starts_at DESC
            LIMIT 1), timezone(app.hr_zone(), p_now)::date)
    $$;

    -- When a patrol round of a shift falls (a round before the start is the next morning).
    CREATE FUNCTION app.staff_round_at(p_day date, p_shift text, p_time time) RETURNS timestamptz
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT timezone(app.hr_zone(), p_day + p_time
            + CASE WHEN p_time < shift.starts_at THEN interval '1 day' ELSE interval '0' END)
        FROM app.work_shifts AS shift WHERE shift.code = p_shift
    $$;

    -- What the checklist forms show: each checklist with its tasks due on the day ("sh" lists
    -- the shifts of a caretaker task; the page shows the person's own shift only).
    CREATE FUNCTION app.telegram_staff_checklists(p_day date) RETURNS jsonb
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT COALESCE(jsonb_agg(jsonb_strip_nulls(jsonb_build_object('code', checklist.code,
                'kind', checklist.kind, 'name', checklist.name_km, 'extras', to_jsonb(checklist.extras),
                'patrols', checklist.patrol_times, 'places', checklist.patrol_places,
                'items', COALESCE((SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
                        'k', item.item_key, 's', item.section_number, 'h', item.section_km,
                        't', item.text_km, 'sh', to_jsonb(item.shifts),
                        'f', CASE WHEN item.asks_floor THEN true END)) ORDER BY item.sort_order)
                    FROM app.staff_checklist_items AS item
                    WHERE item.checklist_id = checklist.id AND app.staff_item_due(item, p_day, NULL)),
                    '[]'::jsonb)))
            ORDER BY checklist.sort_order), '[]'::jsonb)
        FROM app.staff_live_checklists() AS checklist
    $$;

    -- One person's checklist state for the forms: the caretaker's shift now with the patrol rounds
    -- already sent, and the checklists already sent today (or this shift).
    CREATE FUNCTION app.telegram_staff_checklist_person(p_employee uuid, p_roles jsonb,
        p_now timestamptz)
    RETURNS jsonb LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT jsonb_strip_nulls(jsonb_build_object(
            'duty', CASE WHEN p_roles ? 'CARETAKER' AND duty.shift_code IS NOT NULL THEN
                jsonb_build_object('shift', duty.shift_code, 'date', duty.work_date,
                    'shift_km', (SELECT shift.name_km FROM app.work_shifts AS shift
                                 WHERE shift.code = duty.shift_code),
                    'rounds', COALESCE((SELECT jsonb_agg(to_char(round.round_time, 'HH24:MI')
                            ORDER BY round.created_at)
                        FROM app.staff_patrol_rounds AS round
                        JOIN app.employees AS employee ON employee.id = p_employee
                        WHERE round.property_id = employee.property_id
                          AND round.work_date = duty.work_date
                          AND round.shift_code = duty.shift_code), '[]'::jsonb)) END,
            'day_off', CASE WHEN (SELECT plan.is_day_off FROM app.hr_shift_on(p_employee,
                    timezone(app.hr_zone(), p_now)::date) AS plan) THEN true END,
            'sent', (SELECT jsonb_agg(DISTINCT checklist.code)
                FROM app.staff_checklist_reports AS report
                JOIN app.staff_checklists AS checklist ON checklist.id = report.checklist_id
                WHERE report.employee_id = p_employee
                  AND CASE WHEN checklist.kind = 'CARETAKER'
                      THEN report.work_date = duty.work_date AND report.shift_code = duty.shift_code
                      ELSE report.work_date = timezone(app.hr_zone(), p_now)::date END)))
        FROM (SELECT 1) AS one
        LEFT JOIN LATERAL app.staff_duty(p_employee, p_now) AS duty ON true
    $$;

    -- Who may open the Staff forms and what they show (replaces step 4c's list): the same
    -- people and choices, with each person's checklist state and the checklists.
    CREATE OR REPLACE FUNCTION app.telegram_staff_form_data(p_property uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_now timestamptz := statement_timestamp();
        v_today date;
        v_users jsonb;
        v_jobs jsonb;
        v_choices jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT timezone(property.timezone_name, v_now)::date INTO v_today
        FROM app.properties AS property WHERE property.id = p_property;
        v_jobs := app.telegram_staff_jobs(p_property);
        SELECT coalesce(jsonb_agg(jsonb_build_object('id', person.telegram_user_id,
                'role', 'STAFF', 'data', jsonb_build_object('name_km', person.name_km,
                    'name_en', person.name_en, 'roles', person.roles,
                    'shift_code', person.shift_code, 'shift_km', person.shift_km)
                    || CASE WHEN person.roles ? 'TECHNICIAN'
                        THEN jsonb_build_object('jobs', v_jobs) ELSE '{}'::jsonb END
                    || app.telegram_staff_checklist_person(person.employee_id, person.roles, v_now))
                ORDER BY person.telegram_user_id), '[]'::jsonb)
        INTO v_users
        FROM (
            SELECT link.telegram_user_id, employee.id AS employee_id, employee.name_km,
                employee.name_en, jsonb_agg(DISTINCT link.report_role) AS roles, job.shift_code,
                (SELECT shift.name_km FROM app.work_shifts AS shift
                 WHERE shift.code = job.shift_code) AS shift_km
            FROM app.employee_telegram_links AS link
            JOIN app.employees AS employee ON employee.id = link.employee_id
            LEFT JOIN LATERAL app.hr_job_on(employee.id, v_today) AS job ON true
            WHERE employee.property_id = p_property AND app.hr_link_live(link.id, v_today)
            GROUP BY link.telegram_user_id, employee.id, employee.name_km, employee.name_en,
                job.shift_code
        ) AS person;
        -- Report a problem uses the same types, places and open Building problems as the Tenant
        -- bot, and any Unit of the Property (Unit numbers only). The Utility reading form
        -- uses the meters (Unit numbers and last readings only, no names). The checklists show
        -- the tasks due today.
        v_choices := (app.telegram_tenant_form_data(p_property, p_actor) -> 'choices')
            || jsonb_build_object('units', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'id', unit.id, 'number', unit.unit_number) ORDER BY unit.unit_number)
                FROM app.units AS unit WHERE unit.property_id = p_property), '[]'::jsonb),
                'meters', app.telegram_staff_meters(p_property, v_today),
                'checklists', app.telegram_staff_checklists(v_today));
        RETURN jsonb_build_object('users', v_users, 'choices', v_choices);
    END $$;

    -- The day and shift a checklist or patrol round of a sender is for, or NULL (no shift).
    CREATE FUNCTION app.staff_form_duty(p_employee uuid, p_roles text[], p_kind text,
        p_form jsonb, p_now timestamptz)
    RETURNS TABLE (work_date date, shift_code text) ROWS 1
    LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
    DECLARE
        v_shift text := p_form ->> 'shift';
    BEGIN
        IF p_kind <> 'CARETAKER' THEN
            RETURN QUERY SELECT timezone(app.hr_zone(), p_now)::date, NULL::text;
            RETURN;
        END IF;
        -- A caretaker's own shift from HR, not one picked in the form.
        IF 'CARETAKER' = ANY (p_roles) THEN
            RETURN QUERY SELECT duty.work_date, duty.shift_code
            FROM app.staff_duty(p_employee, p_now) AS duty;
            IF FOUND THEN
                RETURN;
            END IF;
        END IF;
        -- An Authorizer picks the shift.
        IF 'AUTHORIZER' = ANY (p_roles) AND jsonb_typeof(p_form -> 'shift') = 'string'
            AND EXISTS (SELECT 1 FROM app.work_shifts AS shift WHERE shift.code = v_shift) THEN
            RETURN QUERY SELECT app.staff_shift_day(v_shift, p_now), v_shift;
        END IF;
    END $$;

    -- A short text a form brought: NULL when absent or empty, else trimmed and at most p_max.
    CREATE FUNCTION app.staff_form_text(p_value jsonb, p_max integer) RETURNS text
    LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog AS $$
    BEGIN
        IF p_value IS NULL OR jsonb_typeof(p_value) = 'null' THEN
            RETURN NULL;
        END IF;
        IF jsonb_typeof(p_value) <> 'string' OR length(btrim(p_value #>> '{}')) > p_max THEN
            RAISE EXCEPTION 'text' USING ERRCODE = 'PRS01';
        END IF;
        RETURN NULLIF(btrim(p_value #>> '{}'), '');
    END $$;

    -- 1. A daily checklist (the pulled item ``p_inbound``): every task due that day (and shift)
    -- answered OK or NOT_OK, with an optional note; the extra boxes of the checklist. A check
    -- sent again for the same day is kept as a new row; the newest counts.
    CREATE FUNCTION app.telegram_staff_checklist(p_property uuid, p_inbound uuid,
        p_form jsonb, p_media jsonb, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_now timestamptz := statement_timestamp();
        v_sender record;
        v_found app.staff_checklist_reports%ROWTYPE;
        v_checklist app.staff_checklists%ROWTYPE;
        v_role text;
        v_day date;
        v_shift text;
        v_due text[];
        v_floor_due boolean;
        v_answers jsonb;
        v_notes jsonb;
        v_extras jsonb;
        v_key text;
        v_value jsonb;
        v_note text;
        v_saved jsonb := '{}'::jsonb;
        v_kept jsonb := '{}'::jsonb;
        v_number numeric;
        v_floor text;
        v_done integer := 0;
        v_problems integer := 0;
        v_again boolean;
        v_id uuid := gen_random_uuid();
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT sender.* INTO v_sender FROM app.staff_form_sender(p_property, p_inbound) AS sender;
        SELECT report.* INTO v_found FROM app.staff_checklist_reports AS report
        WHERE report.inbound_event_id = p_inbound;
        IF FOUND THEN
            RETURN jsonb_build_object('result', 'SENT', 'repeated', true,
                'done', v_found.done_count, 'problems', v_found.problem_count,
                'total', v_found.done_count + v_found.problem_count);
        END IF;
        IF v_sender.employee_id IS NULL THEN
            RETURN jsonb_build_object('result', 'NOT_LINKED');
        END IF;
        IF p_form IS NULL OR jsonb_typeof(p_form) <> 'object'
            OR jsonb_typeof(p_form -> 'code') IS DISTINCT FROM 'string' THEN
            RETURN app.staff_form_refused('not_a_form');
        END IF;
        SELECT checklist.* INTO v_checklist FROM app.staff_live_checklists() AS checklist
        WHERE checklist.code = p_form ->> 'code';
        IF NOT FOUND THEN
            RETURN app.staff_form_refused('checklist');
        END IF;
        v_role := CASE v_checklist.kind WHEN 'CLEANING' THEN 'CLEANER'
            WHEN 'CARETAKER' THEN 'CARETAKER' ELSE 'TECHNICIAN' END;
        IF NOT v_sender.roles && ARRAY[v_role, 'AUTHORIZER'] THEN
            RETURN jsonb_build_object('result', 'NOT_ROLE', 'kind', v_checklist.kind);
        END IF;
        -- No photo in a checklist: a broken thing is sent with Report a problem.
        IF p_media IS NULL OR p_media <> '[]'::jsonb THEN
            RETURN app.staff_form_refused('no_photo');
        END IF;
        SELECT duty.work_date, duty.shift_code INTO v_day, v_shift
        FROM app.staff_form_duty(v_sender.employee_id, v_sender.roles, v_checklist.kind, p_form,
            v_now) AS duty;
        IF v_day IS NULL THEN
            RETURN jsonb_build_object('result', 'NO_SHIFT');
        END IF;
        SELECT array_agg(item.item_key ORDER BY item.sort_order), bool_or(item.asks_floor)
        INTO v_due, v_floor_due
        FROM app.staff_checklist_items AS item
        WHERE item.checklist_id = v_checklist.id AND app.staff_item_due(item, v_day, v_shift);
        IF v_due IS NULL THEN
            RETURN jsonb_build_object('result', 'NOTHING_DUE');
        END IF;
        -- Every task due, each once, OK or NOT_OK.
        v_answers := p_form -> 'answers';
        IF jsonb_typeof(v_answers) IS DISTINCT FROM 'object'
            OR (SELECT count(*) FROM jsonb_object_keys(v_answers)) <> cardinality(v_due)
            OR EXISTS (SELECT 1 FROM jsonb_each(v_answers) AS answer
                       WHERE NOT answer.key = ANY (v_due)
                          OR answer.value NOT IN ('"OK"'::jsonb, '"NOT_OK"'::jsonb)) THEN
            RETURN app.staff_form_refused('answers');
        END IF;
        v_notes := COALESCE(p_form -> 'notes', '{}'::jsonb);
        IF jsonb_typeof(v_notes) = 'null' THEN
            v_notes := '{}'::jsonb;
        END IF;
        IF jsonb_typeof(v_notes) <> 'object'
            OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_notes) AS note (key)
                       WHERE NOT note.key = ANY (v_due)) THEN
            RETURN app.staff_form_refused('notes');
        END IF;
        BEGIN
            FOREACH v_key IN ARRAY v_due LOOP
                v_note := app.staff_form_text(v_notes -> v_key, 200);
                v_saved := v_saved || jsonb_build_object(v_key, jsonb_strip_nulls(
                    jsonb_build_object('a', v_answers ->> v_key, 'note', v_note)));
                IF v_answers ->> v_key = 'OK' THEN
                    v_done := v_done + 1;
                ELSE
                    v_problems := v_problems + 1;
                END IF;
            END LOOP;
        EXCEPTION WHEN SQLSTATE 'PRS01' THEN
            RETURN app.staff_form_refused('notes');
        END;
        BEGIN
            v_floor := app.staff_form_text(p_form -> 'floor', 20);
        EXCEPTION WHEN SQLSTATE 'PRS01' THEN
            RETURN app.staff_form_refused('floor');
        END;
        IF v_floor IS NOT NULL AND NOT COALESCE(v_floor_due, false) THEN
            RETURN app.staff_form_refused('floor');
        END IF;
        -- The extra boxes: whole numbers for the market money (riel) and the visitors, short
        -- texts for the rest.
        v_extras := COALESCE(p_form -> 'extras', '{}'::jsonb);
        IF jsonb_typeof(v_extras) = 'null' THEN
            v_extras := '{}'::jsonb;
        END IF;
        IF jsonb_typeof(v_extras) <> 'object' THEN
            RETURN app.staff_form_refused('extras');
        END IF;
        FOR v_key, v_value IN SELECT extra.key, extra.value FROM jsonb_each(v_extras) AS extra LOOP
            IF NOT v_key = ANY (v_checklist.extras) THEN
                RETURN app.staff_form_refused('extras');
            END IF;
            CONTINUE WHEN jsonb_typeof(v_value) = 'null';
            IF v_key IN ('MARKET_RIEL', 'VISITORS') THEN
                IF jsonb_typeof(v_value) <> 'number' THEN
                    RETURN app.staff_form_refused('extras');
                END IF;
                v_number := (v_value #>> '{}')::numeric;
                IF v_number <> trunc(v_number) OR v_number < 0
                    OR v_number > (CASE v_key WHEN 'VISITORS' THEN 1000 ELSE 100000000 END) THEN
                    RETURN app.staff_form_refused('extras');
                END IF;
                v_kept := v_kept || jsonb_build_object(v_key, v_number::bigint);
            ELSE
                BEGIN
                    v_note := app.staff_form_text(v_value, 300);
                EXCEPTION WHEN SQLSTATE 'PRS01' THEN
                    RETURN app.staff_form_refused('extras');
                END;
                IF v_note IS NOT NULL THEN
                    v_kept := v_kept || jsonb_build_object(v_key, v_note);
                END IF;
            END IF;
        END LOOP;
        v_again := EXISTS (SELECT 1 FROM app.staff_checklist_reports AS report
            JOIN app.staff_checklists AS checklist ON checklist.id = report.checklist_id
            WHERE report.employee_id = v_sender.employee_id AND checklist.code = v_checklist.code
              AND report.work_date = v_day AND report.shift_code IS NOT DISTINCT FROM v_shift);
        INSERT INTO app.staff_checklist_reports (id, property_id, inbound_event_id, checklist_id,
            employee_id, telegram_user_id, work_date, shift_code, answers, floor_label, extras,
            done_count, problem_count, created_by)
        VALUES (v_id, p_property, p_inbound, v_checklist.id, v_sender.employee_id,
            v_sender.telegram_user_id, v_day, v_shift, v_saved, v_floor, v_kept, v_done,
            v_problems, p_actor);
        PERFORM app.product_audit(p_property, p_actor, v_day, 'staff.checklist.sent',
            'staff_checklist_report', v_id, 'Daily checklist from the Staff bot', 'telegram.operate',
            NULL, jsonb_build_object('checklist', v_checklist.code, 'version', v_checklist.version,
                'shift', v_shift, 'done', v_done, 'problems', v_problems, 'again', v_again), NULL);
        RETURN jsonb_build_object('result', 'SENT', 'repeated', false, 'again', v_again,
            'done', v_done, 'problems', v_problems, 'total', v_done + v_problems);
    END $$;

    -- 2. A patrol round of the caretaker's shift, with the places walked. A round can be sent
    -- from 30 minutes before its time, once a shift.
    CREATE FUNCTION app.telegram_staff_patrol(p_property uuid, p_inbound uuid,
        p_form jsonb, p_media jsonb, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_now timestamptz := statement_timestamp();
        v_sender record;
        v_found app.staff_patrol_rounds%ROWTYPE;
        v_checklist app.staff_checklists%ROWTYPE;
        v_day date;
        v_shift text;
        v_round text;
        v_time time;
        v_places text[];
        v_id uuid := gen_random_uuid();
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT sender.* INTO v_sender FROM app.staff_form_sender(p_property, p_inbound) AS sender;
        SELECT round.* INTO v_found FROM app.staff_patrol_rounds AS round
        WHERE round.inbound_event_id = p_inbound;
        IF FOUND THEN
            RETURN jsonb_build_object('result', 'SENT', 'repeated', true,
                'round', to_char(v_found.round_time, 'HH24:MI'),
                'at', to_char(timezone(app.hr_zone(), v_found.created_at), 'HH24:MI'));
        END IF;
        IF v_sender.employee_id IS NULL THEN
            RETURN jsonb_build_object('result', 'NOT_LINKED');
        END IF;
        IF NOT v_sender.roles && ARRAY['CARETAKER', 'AUTHORIZER'] THEN
            RETURN jsonb_build_object('result', 'NOT_ROLE', 'kind', 'CARETAKER');
        END IF;
        IF p_media IS NULL OR p_media <> '[]'::jsonb THEN
            RETURN app.staff_form_refused('no_photo');
        END IF;
        IF p_form IS NULL OR jsonb_typeof(p_form) <> 'object'
            OR jsonb_typeof(p_form -> 'round') IS DISTINCT FROM 'string'
            OR jsonb_typeof(p_form -> 'places') IS DISTINCT FROM 'array' THEN
            RETURN app.staff_form_refused('not_a_form');
        END IF;
        SELECT checklist.* INTO v_checklist FROM app.staff_live_checklists() AS checklist
        WHERE checklist.kind = 'CARETAKER' ORDER BY checklist.sort_order LIMIT 1;
        SELECT duty.work_date, duty.shift_code INTO v_day, v_shift
        FROM app.staff_form_duty(v_sender.employee_id, v_sender.roles, 'CARETAKER', p_form,
            v_now) AS duty;
        IF v_day IS NULL OR v_checklist.id IS NULL THEN
            RETURN jsonb_build_object('result', 'NO_SHIFT');
        END IF;
        v_round := p_form ->> 'round';
        IF NOT (v_checklist.patrol_times -> v_shift) ? v_round THEN
            RETURN app.staff_form_refused('round');
        END IF;
        v_time := v_round::time;
        SELECT array_agg(DISTINCT place.value #>> '{}') INTO v_places
        FROM jsonb_array_elements(p_form -> 'places') AS place;
        IF v_places IS NULL OR EXISTS (SELECT 1 FROM unnest(v_places) AS place (code)
                WHERE place.code IS NULL OR NOT EXISTS (
                    SELECT 1 FROM jsonb_array_elements(v_checklist.patrol_places) AS known
                    WHERE known.value ->> 'k' = place.code)) THEN
            RETURN app.staff_form_refused('places');
        END IF;
        IF app.staff_round_at(v_day, v_shift, v_time) > v_now + interval '30 minutes' THEN
            RETURN jsonb_build_object('result', 'TOO_EARLY', 'round', v_round);
        END IF;
        SELECT round.* INTO v_found FROM app.staff_patrol_rounds AS round
        WHERE round.property_id = p_property AND round.work_date = v_day
          AND round.shift_code = v_shift AND round.round_time = v_time;
        IF FOUND THEN
            RETURN jsonb_build_object('result', 'ROUND_DONE', 'round', v_round,
                'at', to_char(timezone(app.hr_zone(), v_found.created_at), 'HH24:MI'));
        END IF;
        INSERT INTO app.staff_patrol_rounds (id, property_id, inbound_event_id, checklist_id,
            employee_id, telegram_user_id, work_date, shift_code, round_time, places, created_by)
        VALUES (v_id, p_property, p_inbound, v_checklist.id, v_sender.employee_id,
            v_sender.telegram_user_id, v_day, v_shift, v_time, v_places, p_actor);
        RETURN jsonb_build_object('result', 'SENT', 'repeated', false, 'round', v_round,
            'at', to_char(timezone(app.hr_zone(), v_now), 'HH24:MI'));
    END $$;

    -- 3. The 18:00 summary for the Authorizers, once a day (the Telegram jobs, every minute).
    -- Cleaning and Technical: who sent today's check (people not on a day off), and the tasks
    -- not done. Caretakers: the shifts of the last 24 hours, the patrol rounds due by now and
    -- the shift checks of the shifts that ended, the tasks with a problem and the incidents.
    CREATE FUNCTION app.staff_daily_summary_at(p_property uuid, p_now timestamptz, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    DECLARE
        v_zone text;
        v_day date;
        v_since timestamptz := p_now - interval '24 hours';
        v_line text;
        v_lines text[] := '{}';
        v_kind record;
        v_sent integer;
        v_expected integer;
        v_missing text;
        v_bad text;
        v_shifts record;
        v_details jsonb;
        v_messages integer := 0;
    BEGIN
        SELECT property.timezone_name INTO v_zone FROM app.properties AS property
        WHERE property.id = p_property;
        IF v_zone IS NULL OR timezone(v_zone, p_now)::time < time '18:00' THEN
            RETURN 0;
        END IF;
        v_day := timezone(v_zone, p_now)::date;
        IF EXISTS (SELECT 1 FROM app.staff_summary_runs AS run
                   WHERE run.property_id = p_property AND run.work_date = v_day) THEN
            RETURN 0;
        END IF;
        -- Cleaning and Technical.
        FOR v_kind IN SELECT * FROM (VALUES ('CLEANING', 'CLEANER', '🧹 សម្អាត'),
                ('TECHNICAL', 'TECHNICIAN', '🔧 បច្ចេកទេស')) AS kind (kind, role, title) LOOP
            WITH people AS (
                SELECT DISTINCT employee.id, COALESCE(NULLIF(employee.name_km, ''), employee.name_en) AS name
                FROM app.employee_telegram_links AS link
                JOIN app.employees AS employee ON employee.id = link.employee_id
                CROSS JOIN LATERAL app.hr_shift_on(employee.id, v_day) AS plan
                WHERE employee.property_id = p_property AND link.report_role = v_kind.role
                  AND app.hr_link_live(link.id, v_day) AND NOT COALESCE(plan.is_day_off, false)
            ), latest AS (
                SELECT DISTINCT ON (report.employee_id, checklist.code) report.*
                FROM app.staff_checklist_reports AS report
                JOIN app.staff_checklists AS checklist ON checklist.id = report.checklist_id
                WHERE report.property_id = p_property AND report.work_date = v_day
                  AND checklist.kind = v_kind.kind
                ORDER BY report.employee_id, checklist.code, report.created_at DESC
            )
            SELECT (SELECT count(DISTINCT latest.employee_id) FROM latest),
                (SELECT count(*) FROM people),
                (SELECT string_agg(people.name, ', ' ORDER BY people.name) FROM people
                 WHERE NOT EXISTS (SELECT 1 FROM latest WHERE latest.employee_id = people.id)),
                (SELECT string_agg(item.text_km || COALESCE(' (' || (answer.value ->> 'note') || ')', ''),
                        '; ' ORDER BY item.sort_order)
                 FROM latest
                 CROSS JOIN LATERAL jsonb_each(latest.answers) AS answer
                 JOIN app.staff_checklist_items AS item
                   ON item.checklist_id = latest.checklist_id AND item.item_key = answer.key
                 WHERE answer.value ->> 'a' = 'NOT_OK')
            INTO v_sent, v_expected, v_missing, v_bad;
            CONTINUE WHEN v_sent = 0 AND v_expected = 0;
            v_line := v_kind.title || '៖ ផ្ញើ ' || v_sent || '/' || v_expected || ' នាក់';
            IF v_missing IS NOT NULL THEN
                v_line := v_line || E'\\n   មិនទាន់ផ្ញើ៖ ' || left(v_missing, 300);
            END IF;
            IF v_bad IS NOT NULL THEN
                v_line := v_line || E'\\n   ' || CASE v_kind.kind WHEN 'CLEANING' THEN 'មិនបានធ្វើ'
                    ELSE 'ត្រូវជួសជុល' END || '៖ ' || left(v_bad, 600);
            END IF;
            v_lines := v_lines || v_line;
        END LOOP;
        -- Caretakers: the shifts of the last 24 hours.
        WITH shifts AS (
            SELECT DISTINCT day.work_date, plan.shift_code, times.starts_at, times.ends_at
            FROM app.employee_telegram_links AS link
            JOIN app.employees AS employee ON employee.id = link.employee_id
            CROSS JOIN (VALUES (v_day - 1), (v_day)) AS day (work_date)
            CROSS JOIN LATERAL app.hr_shift_on(employee.id, day.work_date) AS plan
            CROSS JOIN LATERAL app.hr_shift_times(plan.shift_code, day.work_date) AS times
            WHERE employee.property_id = p_property AND link.report_role = 'CARETAKER'
              AND app.hr_link_live(link.id, day.work_date) AND plan.shift_code IS NOT NULL
              AND times.starts_at < p_now AND times.ends_at > v_since
        ), checklist AS (
            SELECT * FROM app.staff_live_checklists() AS checklist WHERE checklist.kind = 'CARETAKER'
            ORDER BY checklist.sort_order LIMIT 1
        ), rounds AS (
            SELECT shifts.work_date, shifts.shift_code, round.value #>> '{}' AS round_time,
                EXISTS (SELECT 1 FROM app.staff_patrol_rounds AS sent
                        WHERE sent.property_id = p_property AND sent.work_date = shifts.work_date
                          AND sent.shift_code = shifts.shift_code
                          AND sent.round_time = (round.value #>> '{}')::time) AS done
            FROM shifts CROSS JOIN checklist
            CROSS JOIN LATERAL jsonb_array_elements(checklist.patrol_times -> shifts.shift_code) AS round
            WHERE app.staff_round_at(shifts.work_date, shifts.shift_code, (round.value #>> '{}')::time)
                BETWEEN v_since AND p_now
        ), reports AS (
            SELECT DISTINCT ON (report.work_date, report.shift_code) report.*
            FROM app.staff_checklist_reports AS report
            JOIN shifts ON shifts.work_date = report.work_date AND shifts.shift_code = report.shift_code
            JOIN app.staff_checklists AS kind ON kind.id = report.checklist_id AND kind.kind = 'CARETAKER'
            WHERE report.property_id = p_property
            ORDER BY report.work_date, report.shift_code, report.created_at DESC
        )
        SELECT (SELECT count(*) FROM rounds) AS planned,
            (SELECT count(*) FROM rounds WHERE rounds.done) AS walked,
            (SELECT string_agg(shift.name_km || ' ' || rounds.round_time
                    || CASE WHEN rounds.work_date <> v_day
                        THEN ' (' || to_char(rounds.work_date, 'DD/MM') || ')' ELSE '' END, ', '
                    ORDER BY rounds.work_date, shift.sort_order, rounds.round_time)
             FROM rounds JOIN app.work_shifts AS shift ON shift.code = rounds.shift_code
             WHERE NOT rounds.done) AS missed,
            (SELECT count(*) FROM shifts WHERE shifts.ends_at <= p_now) AS ended,
            (SELECT count(*) FROM shifts WHERE shifts.ends_at <= p_now AND EXISTS (
                SELECT 1 FROM reports WHERE reports.work_date = shifts.work_date
                  AND reports.shift_code = shifts.shift_code)) AS checked,
            (SELECT string_agg(item.text_km || COALESCE(' (' || (answer.value ->> 'note') || ')', ''),
                    '; ' ORDER BY reports.work_date, reports.shift_code, item.sort_order)
             FROM reports
             CROSS JOIN LATERAL jsonb_each(reports.answers) AS answer
             JOIN app.staff_checklist_items AS item
               ON item.checklist_id = reports.checklist_id AND item.item_key = answer.key
             WHERE answer.value ->> 'a' = 'NOT_OK') AS problems,
            (SELECT string_agg(shift.name_km || '៖ ' || (reports.extras ->> 'INCIDENT'), '; '
                    ORDER BY reports.work_date, shift.sort_order)
             FROM reports JOIN app.work_shifts AS shift ON shift.code = reports.shift_code
             WHERE reports.extras ? 'INCIDENT') AS incidents
        INTO v_shifts;
        IF v_shifts.planned > 0 OR v_shifts.ended > 0 THEN
            v_line := '🛡 អ្នកថែរក្សាអគារ៖ ល្បាត ' || v_shifts.walked || '/' || v_shifts.planned
                || ' · របាយការណ៍វេន ' || v_shifts.checked || '/' || v_shifts.ended;
            IF v_shifts.missed IS NOT NULL THEN
                v_line := v_line || E'\\n   ល្បាតខកខាន៖ ' || left(v_shifts.missed, 300);
            END IF;
            IF v_shifts.problems IS NOT NULL THEN
                v_line := v_line || E'\\n   មានបញ្ហា៖ ' || left(v_shifts.problems, 600);
            END IF;
            IF v_shifts.incidents IS NOT NULL THEN
                v_line := v_line || E'\\n   ⚠ ឧប្បត្តិហេតុ៖ ' || left(v_shifts.incidents, 600);
            END IF;
            v_lines := v_lines || v_line;
        END IF;
        IF cardinality(v_lines) = 0 THEN
            v_lines := ARRAY['គ្មានរបាយការណ៍ ឬបុគ្គលិកដែលត្រូវផ្ញើថ្ងៃនេះទេ។'];
        END IF;
        v_details := jsonb_build_object('date', to_char(v_day, 'DD/MM/YYYY'),
            'list', left(array_to_string(v_lines, E'\\n\\n'), 3000));
        INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language,
            details, keyboard, created_by)
        SELECT p_property, 'STAFF', person.telegram_user_id, 'staff.daily_summary', 'km',
            v_details, NULL, p_actor
        FROM (
            SELECT DISTINCT link.telegram_user_id
            FROM app.employee_telegram_links AS link
            JOIN app.employees AS employee ON employee.id = link.employee_id
            WHERE employee.property_id = p_property AND link.report_role = 'AUTHORIZER'
              AND app.hr_link_live(link.id, v_day)
        ) AS person;
        GET DIAGNOSTICS v_messages = ROW_COUNT;
        INSERT INTO app.staff_summary_runs (property_id, work_date, details, messages, created_by)
        VALUES (p_property, v_day, v_details, v_messages, p_actor);
        RETURN v_messages;
    END $$;

    CREATE FUNCTION app.telegram_staff_daily_summary(p_property uuid, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        -- One job at a time: a second run waits, then finds the day's summary.
        PERFORM pg_advisory_xact_lock(hashtextextended('staff_daily_summary:' || p_property::text, 0));
        RETURN app.staff_daily_summary_at(p_property, clock_timestamp(), p_actor);
    END $$;
"""

RUNTIME = (
    "app.telegram_staff_checklist(uuid, uuid, jsonb, jsonb, uuid)",
    "app.telegram_staff_patrol(uuid, uuid, jsonb, jsonb, uuid)",
    "app.telegram_staff_daily_summary(uuid, uuid)",
)
INTERNAL = (
    "app.staff_live_checklists()",
    "app.staff_item_due(app.staff_checklist_items, date, text)",
    "app.staff_duty(uuid, timestamptz)",
    "app.staff_shift_day(text, timestamptz)",
    "app.staff_round_at(date, text, time)",
    "app.telegram_staff_checklists(date)",
    "app.telegram_staff_checklist_person(uuid, jsonb, timestamptz)",
    "app.staff_form_duty(uuid, text[], text, jsonb, timestamptz)",
    "app.staff_form_text(jsonb, integer)",
    "app.staff_daily_summary_at(uuid, timestamptz, uuid)",
)
TABLE_NAMES = (
    "app.staff_checklists, app.staff_checklist_items, app.staff_checklist_reports, "
    "app.staff_patrol_rounds, app.staff_summary_runs"
)


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(_seed())
    op.execute(TRIGGERS)
    op.execute(FUNCTIONS)
    op.execute(f"REVOKE ALL ON TABLE {TABLE_NAMES} FROM PUBLIC, prm_runtime, prm_bootstrap")
    for signature in RUNTIME + INTERNAL:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Staff bot checklists migration is forward-only")
