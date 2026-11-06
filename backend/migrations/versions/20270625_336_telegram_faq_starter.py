# ruff: noqa: E501
"""Telegram bots: the 15 starter FAQ questions, waiting for the Owner (DL-179).

Owner rules: the FAQ draft of 2 Nov 2026 (version 2, with the owner's corrections) has 15
questions in English and Khmer; on 5 Nov 2026 the owner said OK to load them, ready for the Owner
to approve (DL-170 (C): "the 15 questions of the FAQ doc can be loaded as versions waiting for the
Owner").

1. Office › Telegram › FAQ offers "Load the 15 starter questions" while the FAQ is empty. Anyone
   with ``telegram.faq`` (the Owner or a Manager) can load them.
2. Each question is saved as question 1 to 15 with one version that waits for the Owner, even
   when the Owner loads them: no bot shows a question until the Owner approves it, as with a
   Manager's change.
3. Who sees each one follows the draft: questions 1 to 5 and 7 to 10 are for the Customer bot,
   12 to 14 for the Tenant bot, and 6, 11 and 15 for both bots.
4. Loading is refused once the FAQ has any question, so the starter questions never come twice.

The words are kept here as they were in the draft, except (owner 06/11 17:32) question 1 links to
Google Maps and question 3 sends the reader to the website for prices; the Owner can change any
of them before or after approving. Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

import json
from collections.abc import Sequence

from alembic import op

revision: str = "20270625_336"
down_revision: str | None = "20270624_335"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (who sees it, English question, English answer, Khmer question, Khmer answer), in FAQ order.
STARTER: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "CUSTOMER",
        "Where is CHETANA Residence located?",
        "CHETANA Residence is located at No. 39JZ, Street 598, Sangkat Tuol Sangke 1, Khan Russey Keo, Phnom Penh, near Camko Roundabout. Open the map in Google Maps: https://maps.app.goo.gl/S5k67Jj44EARjabP8",
        "លំនៅដ្ឋាន ចេតនា ស្ថិតនៅទីណា?",
        "លំនៅដ្ឋាន ចេតនា ស្ថិតនៅផ្ទះលេខ 39JZ ផ្លូវលេខ 598 សង្កាត់ទួលសង្កែ១ ខណ្ឌឫស្សីកែវ រាជធានីភ្នំពេញ ក្បែររង្វង់មូលកាំកូ (Camko)។ បើកផែនទីក្នុង Google Maps៖ https://maps.app.goo.gl/S5k67Jj44EARjabP8",
    ),
    (
        "CUSTOMER",
        "What types of rooms are available?",
        "We offer Studio, One-Bedroom, Two-Bedroom and Three-Bedroom residences.",
        "មានបន្ទប់ប្រភេទណាខ្លះ?",
        "យើងមានបន្ទប់ប្រភេទ ស្ទូឌីយោ បន្ទប់គេង១ បន្ទប់គេង២ និងបន្ទប់គេង៣។",
    ),
    (
        "CUSTOMER",
        "How much is the monthly rent?",
        "Please see the latest monthly rent for each room type on our website: [website link]. The final price depends on the specific room.",
        "ថ្លៃជួលប្រចាំខែប៉ុន្មាន?",
        "សូមមើលថ្លៃជួលប្រចាំខែចុងក្រោយសម្រាប់បន្ទប់នីមួយៗ នៅលើគេហទំព័ររបស់យើង៖ [website link]។ តម្លៃជាក់ស្តែងអាស្រ័យលើបន្ទប់នីមួយៗ។",
    ),
    (
        "CUSTOMER",
        "Are any rooms available now?",
        "Please send an inquiry, and our team will let you know which rooms are available.",
        "តើមានបន្ទប់ទំនេរឥឡូវនេះទេ?",
        "សូមផ្ញើការសាកសួរ ក្រុមការងាររបស់យើងនឹងជូនដំណឹងលោកអ្នកអំពីបន្ទប់ដែលនៅទំនេរ។",
    ),
    (
        "CUSTOMER",
        "How do I send an inquiry?",
        "Tap \"Send an inquiry\", then fill in your contact details, the room type you are interested in and, if you wish, a preferred visit date (2 to 30 days ahead, morning or afternoon). Our team will contact you shortly.",
        "តើធ្វើដូចម្តេចដើម្បីផ្ញើការសាកសួរ?",
        "សូមចុច «ផ្ញើការសាកសួរ» រួចបំពេញព័ត៌មានទំនាក់ទំនង ប្រភេទបន្ទប់ដែលលោកអ្នកចាប់អារម្មណ៍ និងថ្ងៃមកទស្សនាដែលលោកអ្នកចង់បាន (បើមាន ពី ២ ដល់ ៣០ ថ្ងៃខាងមុខ ពេលព្រឹក ឬពេលរសៀល)។ ក្រុមការងាររបស់យើងនឹងទាក់ទងលោកអ្នកឆាប់ៗនេះ។",
    ),
    (
        "BOTH",
        "What are your office hours?",
        "Our office is open Monday to Saturday, 07:00 to 17:00. Messages received outside these hours will be answered from 07:00 on the next working day.",
        "ការិយាល័យបើកម៉ោងប៉ុន្មាន?",
        "ការិយាល័យបើកពីថ្ងៃច័ន្ទ ដល់ថ្ងៃសៅរ៍ ម៉ោង ០៧:០០ ដល់ ១៧:០០។ សារដែលទទួលបានក្រៅម៉ោងធ្វើការ នឹងត្រូវឆ្លើយតបចាប់ពីម៉ោង ០៧:០០ នៃថ្ងៃធ្វើការបន្ទាប់។",
    ),
    (
        "CUSTOMER",
        "Is the building secure?",
        "Yes. Our building caretakers work in three shifts and patrol the building day and night on a fixed schedule. Security cameras operate 24 hours a day, 7 days a week.",
        "តើអគារមានសុវត្ថិភាពដែរឬទេ?",
        "បាទ/ចាស។ អ្នកថែរក្សាអគាររបស់យើងធ្វើការ ៣ វេន និងល្បាតត្រួតពិនិត្យអគារទាំងថ្ងៃ និងយប់ តាមម៉ោងកំណត់។ កាមេរ៉ាសុវត្ថិភាពដំណើរការ ២៤ ម៉ោង ៧ ថ្ងៃក្នុងមួយសប្តាហ៍។",
    ),
    (
        "CUSTOMER",
        "Is parking available? Are pets allowed?",
        "Yes, parking is available on site. Pets are welcome with a Pet Deposit.",
        "តើមានចំណតយានយន្តទេ? តើអាចចិញ្ចឹមសត្វបានទេ?",
        "បាទ/ចាស យើងមានចំណតយានយន្ត។ លោកអ្នកអាចចិញ្ចឹមសត្វបាន ដោយបង់ប្រាក់កក់សត្វចិញ្ចឹម។",
    ),
    (
        "CUSTOMER",
        "What do I need to rent a room?",
        "Please bring your national ID card or passport. Before signing the Lease, the first month's rent and the Security Deposit must be paid in full.",
        "តើត្រូវការឯកសារអ្វីខ្លះដើម្បីជួលបន្ទប់?",
        "សូមយកអត្តសញ្ញាណប័ណ្ណ ឬលិខិតឆ្លងដែនមកជាមួយ។ មុនពេលចុះហត្ថលេខាលើកិច្ចសន្យា លោកអ្នកត្រូវបង់ថ្លៃជួលខែដំបូង និងប្រាក់កក់ធានាឱ្យបានគ្រប់ចំនួន។",
    ),
    (
        "CUSTOMER",
        "What is the minimum lease term?",
        "The minimum lease term is one month. Leases do not renew automatically. If you wish to extend, please inform us at least 30 days before your End Date.",
        "កិច្ចសន្យាជួលអប្បបរមារយៈពេលប៉ុន្មាន?",
        "រយៈពេលជួលអប្បបរមាគឺ ១ ខែ។ កិច្ចសន្យាមិនបន្តដោយស្វ័យប្រវត្តិទេ។ ប្រសិនបើលោកអ្នកចង់ជួលបន្ត សូមជូនដំណឹងមកយើងយ៉ាងហោចណាស់ ៣០ ថ្ងៃ មុនថ្ងៃផុតកំណត់កិច្ចសន្យា។",
    ),
    (
        "BOTH",
        "How much are electricity and water?",
        "Each room has its own meters. Electricity is $0.25 per kWh and clean water is $0.45 per m³.",
        "តើថ្លៃអគ្គិសនី និងទឹកស្អាតប៉ុន្មាន?",
        "បន្ទប់នីមួយៗមាននាឡិកាស្ទង់ផ្ទាល់ខ្លួន។ អគ្គិសនីតម្លៃ $0.25 ក្នុងមួយ kWh និងទឹកស្អាតតម្លៃ $0.45 ក្នុងមួយ m³។",
    ),
    (
        "TENANT",
        "How can I pay my rent?",
        "Rent can be paid in cash at our office, by ABA transfer or by KHQR code.",
        "តើអាចបង់ថ្លៃជួលតាមរបៀបណាខ្លះ?",
        "លោកអ្នកអាចបង់ជាសាច់ប្រាក់នៅការិយាល័យ តាមរយៈ ABA ឬស្កេន KHQR។",
    ),
    (
        "TENANT",
        "What happens if I pay late?",
        "Rent is due on the 5th of each month. Late payments incur a 10% late fee, as stated in your Lease.",
        "ប្រសិនបើបង់យឺត នឹងមានអ្វីកើតឡើង?",
        "ថ្លៃជួលត្រូវបង់នៅថ្ងៃទី ០៥ នៃខែនីមួយៗ។ ការបង់យឺតនឹងត្រូវពិន័យ ១០% ដូចមានចែងក្នុងកិច្ចសន្យា។",
    ),
    (
        "TENANT",
        "When will my Security Deposit be refunded?",
        "Your Security Deposit is refunded within 7 days after the final room inspection and the final utility invoice, following your End Date.",
        "តើប្រាក់កក់ធានានឹងត្រូវប្រគល់ជូនវិញនៅពេលណា?",
        "ប្រាក់កក់ធានានឹងត្រូវប្រគល់ជូនវិញក្នុងរយៈពេល ៧ ថ្ងៃ បន្ទាប់ពីការត្រួតពិនិត្យបន្ទប់ចុងក្រោយ និងវិក្កយបត្រទឹកភ្លើងចុងក្រោយ បន្ទាប់ពីថ្ងៃផុតកំណត់កិច្ចសន្យា។",
    ),
    (
        "BOTH",
        "Can I speak with customer service?",
        "Certainly. Tap \"Contact office\", share your phone number and write your message. Our customer service team will reply Monday to Saturday, 07:00 to 17:00.",
        "តើអាចទាក់ទងផ្នែកបម្រើអតិថិជនបានទេ?",
        "បាទ/ចាស។ សូមចុច «ទាក់ទងការិយាល័យ» ចែករំលែកលេខទូរស័ព្ទ ហើយសរសេរសាររបស់លោកអ្នក។ ផ្នែកបម្រើអតិថិជនរបស់យើងនឹងឆ្លើយតបពីថ្ងៃច័ន្ទ ដល់ថ្ងៃសៅរ៍ ម៉ោង ០៧:០០ ដល់ ១៧:០០។",
    ),
)

STARTER_JSON = json.dumps(
    [
        {
            "for_bots": who,
            "question_en": question_en,
            "answer_en": answer_en,
            "question_km": question_km,
            "answer_km": answer_km,
        }
        for who, question_en, answer_en, question_km, answer_km in STARTER
    ],
    ensure_ascii=False,
)
if "$starter$" in STARTER_JSON:  # pragma: no cover - the words above never hold the quote mark
    raise RuntimeError("the starter FAQ words hold the dollar quote")

FUNCTIONS = f"""
    -- The starter questions, in FAQ order (internal).
    CREATE FUNCTION app.telegram_faq_starter()
    RETURNS jsonb LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT $starter${STARTER_JSON}$starter$::jsonb
    $$;

    -- Load the starter questions into an empty FAQ: each waits for the Owner.
    CREATE FUNCTION app.telegram_faq_load_starter(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_item jsonb;
        v_number bigint;
        v_question uuid;
        v_count integer := 0;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.faq', p_property);
        PERFORM 1 FROM app.properties AS property WHERE property.id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the Property does not exist' USING ERRCODE = '22023';
        END IF;
        IF EXISTS (SELECT 1 FROM app.telegram_faq_questions AS question
                   WHERE question.property_id = p_property) THEN
            RAISE EXCEPTION 'The FAQ already has questions' USING ERRCODE = '55000';
        END IF;
        FOR v_item, v_number IN
            SELECT starter.value, starter.ordinality
            FROM jsonb_array_elements(app.telegram_faq_starter()) WITH ORDINALITY AS starter
        LOOP
            INSERT INTO app.telegram_faq_questions (property_id, question_number, created_by)
            VALUES (p_property, v_number::integer, p_actor) RETURNING id INTO v_question;
            INSERT INTO app.telegram_faq_versions (question_id, for_bots, question_en, answer_en,
                question_km, answer_km, proposed_by)
            VALUES (v_question, v_item ->> 'for_bots', v_item ->> 'question_en',
                v_item ->> 'answer_en', v_item ->> 'question_km', v_item ->> 'answer_km', p_actor);
            v_count := v_count + 1;
        END LOOP;
        RETURN jsonb_build_object('loaded', v_count);
    END $$;
"""

INTERNAL = ("app.telegram_faq_starter()",)
RUNTIME = ("app.telegram_faq_load_starter(uuid, uuid)",)


def upgrade() -> None:
    op.execute(FUNCTIONS)
    for signature in RUNTIME + INTERNAL:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
