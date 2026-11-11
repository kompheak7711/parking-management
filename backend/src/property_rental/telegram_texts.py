"""The fixed texts the bots send, in Khmer and English (bots plan: "The bot replies ... are fixed
texts"). A message in the outbox names a text code and its details; the send job puts them
together here. Only the named fields of a text are filled in; nothing else from the details is
ever sent. Staff texts are Khmer only (owner rule); for them the English is the same Khmer text.
"""

from __future__ import annotations

import string
from collections.abc import Mapping
from typing import Final

MAX_FIELD_CHARACTERS: Final = 300
# A field the bot builds itself from fixed texts (My requests), or a long answer or note, may
# be longer.
LONG_FIELDS: Final = {"list": 3000, "text": 600, "answer": 800, "note": 500, "notice": 1500}
# A keyboard whose buttons the bot builds (FAQ questions, Unit Types, days, months): at most
# this many, each this long.
MAX_CHOICES: Final = 30
MAX_CHOICE_CHARACTERS: Final = 60
MAX_MESSAGE_CHARACTERS: Final = 4000

TEXTS: Final[dict[str, dict[str, str]]] = {
    # Step 1: the test the owner runs after setup ("a test message goes from a test bot into
    # the app and back").
    "base.ping_reply": {
        "km": "✅ ប្រព័ន្ធបានទទួលសាររបស់អ្នក ({bot})។ ការភ្ជាប់ដំណើរការល្អ។",
        "en": "✅ The office app got your message ({bot}). The connection works.",
    },
    # Step 2a: the Tenant bot, Start, language and linking (owner rules of 2 and 3 Nov 2026;
    # tenant mock-up v15). The Khmer waits for the native-speaker check.
    "tenant.welcome": {
        "km": (
            "សូមស្វាគមន៍មកកាន់ CHETANA Residence support។\n"
            "Welcome to CHETANA Residence support.\n\n"
            "សូមជ្រើសរើសភាសា។ Please choose your language."
        ),
        "en": (
            "សូមស្វាគមន៍មកកាន់ CHETANA Residence support។\n"
            "Welcome to CHETANA Residence support.\n\n"
            "សូមជ្រើសរើសភាសា។ Please choose your language."
        ),
    },
    "tenant.hello": {
        "km": (
            "សង្ឃឹមថាលោកអ្នកសុខសប្បាយជាទេ។\nតើយើងអាចជួយអ្វីលោកអ្នកបានថ្ងៃនេះ?\n"
            "សូមភ្ជាប់កិច្ចសន្យាជួលរបស់លោកអ្នកជាមុនសិន។"
        ),
        "en": (
            "I hope you are doing well.\nHow can we help you today?\nPlease link your Lease first."
        ),
    },
    "tenant.hello_linked": {
        "km": "សូមស្វាគមន៍ {name}។ លោកអ្នកបានភ្ជាប់ជាមួយបន្ទប់ {unit}។ តើលោកអ្នកត្រូវការអ្វី?",
        "en": "Welcome, {name}. You are linked to Unit {unit}. What do you need?",
    },
    "tenant.ask_phone": {
        "km": ("សូមចុច «ចែករំលែកលេខទូរស័ព្ទ» ខាងក្រោម។ បន្ទាប់មក សូមសរសេរឈ្មោះ និងលេខបន្ទប់របស់លោកអ្នក។"),
        "en": ("Please tap “Share my phone number” below. Then type your name and your Unit."),
    },
    "tenant.ask_phone_again": {
        "km": "សូមចុច «ចែករំលែកលេខទូរស័ព្ទ» ខាងក្រោម។ មានតែលេខរបស់លោកអ្នកផ្ទាល់ទេ ដែលអាចភ្ជាប់បាន។",
        "en": "Please tap “Share my phone number” below. Only your own number can link.",
    },
    "tenant.ask_name": {
        "km": "សូមអរគុណ។ សូមសរសេរឈ្មោះពេញរបស់លោកអ្នក ដូចក្នុងកិច្ចសន្យាជួល។",
        "en": "Thank you. Please type your full name as written on your Lease.",
    },
    "tenant.ask_unit": {
        "km": "សូមអរគុណ។ សូមសរសេរលេខបន្ទប់របស់លោកអ្នក ឧទាហរណ៍ 305។",
        "en": "Thank you. Please type your Unit number, for example 305.",
    },
    "tenant.linked": {
        "km": (
            "សូមស្វាគមន៍ {name}។ លោកអ្នកបានភ្ជាប់ជាមួយបន្ទប់ {unit}។ តើលោកអ្នកត្រូវការអ្វី?\n\n"
            "យើងប្រើលេខទូរស័ព្ទ ឈ្មោះ និងលេខបន្ទប់របស់លោកអ្នក "
            "តែដើម្បីស្វែងរកកិច្ចសន្យាជួល និងឆ្លើយតបសំណើរបស់លោកអ្នកប៉ុណ្ណោះ។"
        ),
        "en": (
            "Welcome, {name}. You are linked to Unit {unit}. What do you need?\n\n"
            "We use your phone, name and Unit only to find your Lease and answer your requests."
        ),
    },
    "tenant.no_match": {
        "km": (
            "យើងរកមិនឃើញអ្នកជួលដែលមានលេខទូរស័ព្ទ ឈ្មោះ និងបន្ទប់នេះទេ។ សូមពិនិត្យ៖\n"
            "• ឈ្មោះពេញរបស់លោកអ្នក ដូចក្នុងកិច្ចសន្យាជួល (លំដាប់ណាក៏បាន)\n"
            "• លេខបន្ទប់របស់លោកអ្នក ឧទាហរណ៍ 305\n"
            "លោកអ្នកនៅសល់ {tries_left} ដងទៀត។"
        ),
        "en": (
            "We cannot find a tenant with this phone, name and Unit. Please check:\n"
            "• Your full name as written on your Lease (any order is fine)\n"
            "• Your Unit number, for example 305\n"
            "You have {tries_left} tries left."
        ),
    },
    "tenant.blocked": {
        "km": ("ការភ្ជាប់ត្រូវបានបិទ 24 ម៉ោង បន្ទាប់ពីព្យាយាមខុស 5 ដង។ សូមទាក់ទងការិយាល័យ។"),
        "en": ("Linking is blocked for 24 hours after 5 failed tries. Please contact the office."),
    },
    "tenant.link_first": {
        "km": "សូមភ្ជាប់កិច្ចសន្យាជួលរបស់លោកអ្នកជាមុនសិន។",
        "en": "Please link your Lease first.",
    },
    # DL-214 (owner 11/11/2026): the one-time QR staff show at Lease signing or guest check-in.
    "tenant.linked_code": {
        "km": "សូមស្វាគមន៍ {name}។ លោកអ្នកបានភ្ជាប់ជាមួយបន្ទប់ {unit}។ តើលោកអ្នកត្រូវការអ្វី?",
        "en": "Welcome, {name}. You are linked to Unit {unit}. What do you need?",
    },
    "tenant.code_bad": {
        "km": "QR នេះមិនដំណើរការទៀតទេ។ សូមសុំ QR ថ្មីពីការិយាល័យ។",
        "en": "This QR code does not work any more. Please ask the office for a new one.",
    },
    "tenant.code_ended": {
        "km": "កិច្ចសន្យាជួល ឬការស្នាក់នៅរបស់លោកអ្នកបានបញ្ចប់ហើយ។ សូមទាក់ទងការិយាល័យ។",
        "en": "Your Lease or stay has ended. Please contact the office.",
    },
    # DL-210: what the relay says while the office app is closed (owner 07/11/2026). The relay
    # cannot say the person's name, so "linked" names only the Unit.
    "tenant.linked_offline": {
        "km": ("សូមអរគុណ។ លោកអ្នកបានភ្ជាប់ជាមួយបន្ទប់ {unit} ហើយ។ ប្រសិនបើមានបញ្ហា សូមចុច «រាយការណ៍បញ្ហា»។"),
        "en": (
            "Thank you. You are linked to Unit {unit}. If you have a problem, tap Problem report."
        ),
    },
    "tenant.report_sent_offline": {
        "km": (
            "យើងបានទទួលរបាយការណ៍របស់លោកអ្នកហើយ។ ការិយាល័យរបស់យើងនឹងពិនិត្យមើល។ "
            "លោកអ្នកនឹងទទួលបានលេខរបាយការណ៍ឆាប់ៗនេះ។"
        ),
        "en": (
            "We got your report. Our office will check it. You will get the report number soon."
        ),
    },
    "tenant.report_sent_offline_urgent": {
        "km": (
            "យើងបានទទួលរបាយការណ៍បន្ទាន់របស់លោកអ្នកហើយ។ "
            "យើងបានប្រាប់អ្នកថែទាំដែលកំពុងប្រចាំការភ្លាមៗ។ "
            "ភ្លើងឆេះ ឬគ្រោះថ្នាក់៖ សូមទូរស័ព្ទ 118 ឬ 117 ជាមុនសិន។"
        ),
        "en": (
            "We got your urgent report. We told the caretaker on shift at once. "
            "Fire or danger: call 118 or 117 first."
        ),
    },
    # Invoices on Telegram (DL-211, owner 8 Nov 2026): each issued Invoice and one reminder 3 days
    # before the due date while it is not fully paid. The Khmer waits for the native check.
    "tenant.invoice": {
        "km": (
            "🧾 វិក្កយបត្រថ្មី {number}\n{unit}\n\n{list}\n\n"
            "សរុប៖ {total}\nត្រូវបង់៖ {to_pay}\nកាលបរិច្ឆេទកំណត់បង់៖ {due}\n\n"
            "សូមបង់ប្រាក់មុនកាលបរិច្ឆេទកំណត់។ សូមអរគុណ។"
        ),
        "en": (
            "🧾 New Invoice {number}\n{unit}\n\n{list}\n\n"
            "Total: {total}\nTo pay: {to_pay}\nDue date: {due}\n\n"
            "Please pay by the due date. Thank you."
        ),
    },
    "tenant.invoice_paid": {
        "km": ("🧾 វិក្កយបត្រ {number}\n{unit}\n\n{list}\n\nសរុប៖ {total}\nបានបង់រួចរាល់ហើយ។ សូមអរគុណ។"),
        "en": (
            "🧾 Invoice {number}\n{unit}\n\n{list}\n\n"
            "Total: {total}\nAlready paid in full. Thank you."
        ),
    },
    "tenant.invoice_reminder": {
        "km": (
            "⏰ សូមរំលឹក៖ វិក្កយបត្រ {number} សម្រាប់ {unit} ដល់កាលកំណត់បង់នៅថ្ងៃ {due}។\n"
            "នៅត្រូវបង់៖ {to_pay}\n\n"
            "ប្រសិនបើលោកអ្នកបានបង់រួចហើយ សូមអរគុណ ហើយមិនបាច់ខ្វល់នឹងសារនេះទេ។"
        ),
        "en": (
            "⏰ Reminder: Invoice {number} for {unit} is due on {due}.\n"
            "Still to pay: {to_pay}\n\n"
            "If you have already paid, thank you, and please ignore this message."
        ),
    },
    # DL-215: the Receipt of a Payment. Khmer is new and needs the native check.
    "tenant.receipt": {
        "km": (
            "✅ បង្កាន់ដៃ {number}\n{unit}\n"
            "កាលបរិច្ឆេទ៖ {date}\nបានទទួល៖ {amount} ({method})\n\n{list}\n\n"
            "សូមអរគុណសម្រាប់ការបង់ប្រាក់។"
        ),
        "en": (
            "✅ Receipt {number}\n{unit}\n"
            "Date: {date}\nReceived: {amount} ({method})\n\n{list}\n\n"
            "Thank you for your payment."
        ),
    },
    # DL-216: a notice from the office (water cut, building work). Khmer is new: native check.
    "tenant.notice": {
        "km": "📢 សេចក្តីជូនដំណឹងពីការិយាល័យ\n\n{notice}",
        "en": "📢 Notice from the office\n\n{notice}",
    },
    # DL-217 (owner card 11 Nov 2026 "When staff record it"): the late Rent letters and the Lease
    # warning, sent when staff record them. Khmer is new and needs the native check.
    "tenant.rent_warning": {
        "km": (
            "⚠️ មិនទាន់បង់ថ្លៃឈ្នួល៖ ២០ ថ្ងៃ\n{unit}\n"
            "វិក្កយបត្រ {invoice} ដល់កាលកំណត់បង់នៅថ្ងៃ {due}។\n"
            "ថ្លៃឈ្នួលនៅត្រូវបង់៖ {amount}\n\n"
            "សូមបង់ឱ្យបានឆាប់តាមដែលអាចធ្វើបាន ឬទាក់ទងការិយាល័យ ប្រសិនបើមានបញ្ហា។\n"
            "លិខិតក្រដាសពីការិយាល័យ ថ្ងៃ {date} គឺជាច្បាប់ផ្លូវការ។"
        ),
        "en": (
            "⚠️ Rent not paid: 20 days\n{unit}\n"
            "Invoice {invoice} was due on {due}.\n"
            "Rent still to pay: {amount}\n\n"
            "Please pay as soon as you can, or contact the office if there is a problem.\n"
            "The office's paper letter of {date} is the official copy."
        ),
    },
    "tenant.rent_default": {
        "km": (
            "🔴 មិនទាន់បង់ថ្លៃឈ្នួល៖ ៣០ ថ្ងៃ\n{unit}\n"
            "វិក្កយបត្រ {invoice} ដល់កាលកំណត់បង់នៅថ្ងៃ {due}។\n"
            "ថ្លៃឈ្នួលនៅត្រូវបង់៖ {amount}\n\n"
            "យោងតាមកិច្ចសន្យាជួលរបស់លោកអ្នក នេះជាការមិនបង់ថ្លៃឈ្នួលធ្ងន់ធ្ងរ។ "
            "សូមបង់ ឬទាក់ទងការិយាល័យនៅថ្ងៃនេះ។\n"
            "លិខិតក្រដាសពីការិយាល័យ ថ្ងៃ {date} គឺជាច្បាប់ផ្លូវការ។"
        ),
        "en": (
            "🔴 Rent not paid: 30 days\n{unit}\n"
            "Invoice {invoice} was due on {due}.\n"
            "Rent still to pay: {amount}\n\n"
            "Under your Lease this is now a serious nonpayment. "
            "Please pay or contact the office today.\n"
            "The office's paper letter of {date} is the official copy."
        ),
    },
    "tenant.lease_warning": {
        "km": (
            "⚠️ ការព្រមានតាមកិច្ចសន្យាជួល លើកទី {sequence}\n{unit}\n"
            "កាលបរិច្ឆេទ៖ {date}\n\n"
            "អ្វីដែលបានកើតឡើង ({when})៖ {text}\n"
            "ប្រការក្នុងកិច្ចសន្យា៖ {rule}\n\n"
            "សូមទាក់ទងការិយាល័យ ប្រសិនបើលោកអ្នកមានសំណួរ។\n"
            "លិខិតក្រដាសពីការិយាល័យ គឺជាច្បាប់ផ្លូវការ។"
        ),
        "en": (
            "⚠️ Lease warning {sequence}\n{unit}\n"
            "Date: {date}\n\n"
            "What happened ({when}): {text}\n"
            "Lease rule: {rule}\n\n"
            "Please contact the office if you have a question.\n"
            "The office's paper letter is the official copy."
        ),
    },
    "tenant.menu": {
        "km": "តើយើងអាចជួយអ្វីលោកអ្នកបាន?",
        "en": "How can we help you?",
    },
    # Step 2d part 2 (DL-170): Contact office and FAQ (tenant mock-up v15; app screens round 29).
    "tenant.contact_ask": {
        "km": ("សូមសរសេរសាររបស់លោកអ្នក។ ក្រុមការងាររបស់យើងឆ្លើយតបពីថ្ងៃច័ន្ទ ដល់ថ្ងៃសៅរ៍ ម៉ោង ០៧:០០ ដល់ ១៧:០០។"),
        "en": ("Please write your message. Our team replies Monday to Saturday, 07:00 to 17:00."),
    },
    "tenant.contact_text_only": {
        "km": "សូមសរសេរសាររបស់លោកអ្នកជាអក្សរ។",
        "en": "Please write your message as text.",
    },
    "tenant.contact_saved": {
        "km": (
            "សូមអរគុណ។ យើងបានទទួលសាររបស់លោកអ្នក ហើយក្រុមការងារនឹងឆ្លើយតបនៅទីនេះ "
            "ពីថ្ងៃច័ន្ទ ដល់ថ្ងៃសៅរ៍ ម៉ោង ០៧:០០ ដល់ ១៧:០០។"
        ),
        "en": (
            "Thank you. We got your message. Our team will reply here, Monday to Saturday, "
            "07:00 to 17:00."
        ),
    },
    "contact.reply": {
        "km": "ការឆ្លើយតបពីការិយាល័យ៖\n\n{text}",
        "en": "Reply from the office:\n\n{text}",
    },
    "tenant.faq_list": {
        "km": "សំណួរដែលសួរញឹកញាប់។ សូមចុចលើសំណួរមួយ។",
        "en": "Frequently asked questions. Tap a question.",
    },
    "tenant.faq_answer": {
        "km": "{question}\n\n{answer}\n\nមានសំណួរផ្សេងទៀតទេ?",
        "en": "{question}\n\n{answer}\n\nAny other question?",
    },
    "tenant.faq_none": {
        "km": "មិនទាន់មានសំណួរនៅឡើយទេ។ សូមចុច «ទាក់ទងការិយាល័យ» ដើម្បីសួរយើង។",
        "en": "There are no questions here yet. Please tap Contact office to ask us.",
    },
    # Step 2b: Problem report (owner rules of 3 Nov 2026, Problem report Part B; tenant
    # mock-up v15). The form itself is the Mini App page in relay/src/tenant_app.ts.
    "tenant.report_kind": {
        "km": (
            "តើជាបញ្ហាប្រភេទណា?\n"
            "• បញ្ហាក្នុងបន្ទប់៖ អ្វីមួយនៅក្នុងបន្ទប់របស់លោកអ្នក។ លោកអ្នកអាចសម្គាល់ថាបន្ទាន់។\n"
            "• បញ្ហាអគារ៖ កន្លែងរួម ឧទាហរណ៍ ជណ្ដើរ ចំណតយានយន្ត ជណ្ដើរយន្ត ឬទ្វារធំ។\n"
            "ភ្លើងឆេះ ឬគ្រោះថ្នាក់ឥឡូវនេះ៖ សូមទូរស័ព្ទ 118 (ពន្លត់អគ្គិភ័យ) ឬ 117 (ប៉ូលិស) ជាមុនសិន។"
        ),
        "en": (
            "What kind of problem?\n"
            "• Unit Problem: something inside your Unit. You can mark it urgent.\n"
            "• Building problem: a shared place, for example stairs, parking, lift or gate.\n"
            "Fire or danger now: call 118 (fire) or 117 (police) first."
        ),
    },
    "tenant.report_received": {
        "km": "យើងបានទទួលរបាយការណ៍ {number} របស់លោកអ្នក។ ស្ថានភាព៖ បានទទួល។\n"
        "យើងនឹងរៀបចំការមកពិនិត្យក្នុងរយៈពេល 1 ថ្ងៃធ្វើការ។",
        "en": "We got your report {number}. Status: Received.\n"
        "We will plan a visit within 1 working day.",
    },
    "tenant.report_received_days": {
        "km": "យើងបានទទួលរបាយការណ៍ {number} របស់លោកអ្នក។ ស្ថានភាព៖ បានទទួល។\n"
        "យើងនឹងរៀបចំការមកពិនិត្យក្នុងរយៈពេល {days} ថ្ងៃធ្វើការ។",
        "en": "We got your report {number}. Status: Received.\n"
        "We will plan a visit within {days} working days.",
    },
    "tenant.report_urgent": {
        "km": "យើងបានទទួលរបាយការណ៍ {number} របស់លោកអ្នក។ ស្ថានភាព៖ បានទទួល។\n"
        "នេះជារឿងបន្ទាន់៖ ក្រុមការងាររបស់យើងនឹងទាក់ទងលោកអ្នកក្នុងរយៈពេល 1 ម៉ោង។",
        "en": "We got your report {number}. Status: Received.\n"
        "This is urgent: our team will contact you within 1 hour.",
    },
    "tenant.report_urgent_hours": {
        "km": "យើងបានទទួលរបាយការណ៍ {number} របស់លោកអ្នក។ ស្ថានភាព៖ បានទទួល។\n"
        "នេះជារឿងបន្ទាន់៖ ក្រុមការងាររបស់យើងនឹងទាក់ទងលោកអ្នកក្នុងរយៈពេល {hours} ម៉ោង។",
        "en": "We got your report {number}. Status: Received.\n"
        "This is urgent: our team will contact you within {hours} hours.",
    },
    "tenant.report_building": {
        "km": "សូមអរគុណ។ យើងបានទទួលរបាយការណ៍ {number} របស់លោកអ្នក។ អ្នកគ្រប់គ្រងនឹងពិនិត្យវា។",
        "en": "Thank you. We got your report {number}. The Manager will check it.",
    },
    "tenant.report_building_urgent": {
        "km": "សូមអរគុណ។ យើងបានទទួលរបាយការណ៍ {number} របស់លោកអ្នក។ "
        "នេះជារឿងបន្ទាន់៖ អ្នកថែទាំដែលកំពុងប្រចាំការនឹងមក។",
        "en": "Thank you. We got your report {number}. "
        "This is urgent: the caretaker on shift is coming.",
    },
    "tenant.report_joined": {
        "km": "សូមអរគុណ។ យើងបានទទួលរបាយការណ៍ {number} របស់លោកអ្នក។ "
        "វាជាបញ្ហាដូចគ្នានឹង {main} ដែលយើងកំពុងដោះស្រាយរួចហើយ។",
        "en": "Thank you. We got your report {number}. "
        "It is the same problem as {main}, which we are already working on.",
    },
    "tenant.report_not_linked": {
        "km": "កិច្ចសន្យាជួលរបស់លោកអ្នកមិនបានភ្ជាប់ទៀតទេ ដូច្នេះយើងមិនអាចរក្សាទុករបាយការណ៍នេះបានទេ។ "
        "សូមភ្ជាប់ម្ដងទៀត ឬទូរស័ព្ទមកការិយាល័យ។",
        "en": "Your Lease is not linked any more, so we could not save this report. "
        "Please link again, or call the office.",
    },
    "tenant.report_invalid": {
        "km": "យើងមិនអាចរក្សាទុករបាយការណ៍នេះបានទេ។ សូមបើកទម្រង់ម្ដងទៀត ហើយព្យាយាមម្ដងទៀត។",
        "en": "We could not save this report. Please open the form and try again.",
    },
    # Step 2d part 1 (DL-129): the tenant hears each step of a report and checks the repair
    # (tenant mock-up v15). The Khmer waits for the native-speaker check.
    "tenant.step_received": {
        "km": "យើងបានទទួលរបាយការណ៍ {number} របស់លោកអ្នក។ ស្ថានភាព៖ បានទទួល។",
        "en": "We got your report {number}. Status: Received.",
    },
    "tenant.step_on_way": {
        "km": "{number}៖ ក្រុមការងាររបស់យើងកំពុងធ្វើដំណើរមក។",
        "en": "{number}: our team is on the way.",
    },
    "tenant.step_planned": {
        "km": "{number}៖ {technician} នឹងមកពិនិត្យនៅថ្ងៃ {day} ម៉ោង {time}។",
        "en": "{number}: {technician} will come to check on {day} at {time}.",
    },
    "tenant.step_checked": {
        "km": "{number}៖ អ្នកបច្ចេកទេសរបស់យើងបានពិនិត្យរកមូលហេតុ។ យើងនឹងប្រាប់លោកអ្នកពីជំហានបន្ទាប់ឆាប់ៗនេះ។",
        "en": "{number}: our technician checked the cause. We will tell you the next step soon.",
    },
    "tenant.step_checked_fixed": {
        "km": "{number}៖ អ្នកបច្ចេកទេសរបស់យើងបានជួសជុលបញ្ហាបន្ទាន់ ហើយបានពិនិត្យរកមូលហេតុ។ "
        "យើងនឹងប្រាប់លោកអ្នកពីជំហានបន្ទាប់ឆាប់ៗនេះ។",
        "en": "{number}: our technician fixed the urgent problem and checked the cause. "
        "We will tell you the next step soon.",
    },
    "tenant.step_owner_pays": {
        "km": "{number}៖ អ្នកបច្ចេកទេសរបស់យើងបានពិនិត្យហើយ។ យើងនឹងជួសជុលដោយមិនគិតថ្លៃលោកអ្នកទេ។ "
        "{technician} នឹងធ្វើការជួសជុល។",
        "en": "{number}: our technician checked. We will fix it at no cost to you. "
        "{technician} will do the repair.",
    },
    "tenant.step_parts": {
        "km": "{number}៖ យើងកំពុងរង់ចាំគ្រឿងបន្លាស់។ យើងនឹងប្រាប់លោកអ្នកបន្ត។",
        "en": "{number}: we are waiting for parts. We will update you.",
    },
    "tenant.step_parts_arrived": {
        "km": "{number}៖ គ្រឿងបន្លាស់បានមកដល់ហើយ។ {technician} នឹងធ្វើការជួសជុល។",
        "en": "{number}: the parts arrived. {technician} will do the repair.",
    },
    "tenant.step_done_check": {
        "km": "{number}៖ ជួសជុលរួចរាល់ហើយ។ សូមពិនិត្យ ហើយចុច «ជួសជុលរួច» ឬ «មិនទាន់រួច»។ "
        "បើគ្មានការឆ្លើយតបក្នុងរយៈពេល {days} ថ្ងៃ វានឹងបិទដោយខ្លួនឯង។",
        "en": "{number}: done. Please check and tap Fixed or Not fixed. "
        "If there is no reply in {days} days, it closes by itself.",
    },
    "tenant.step_done": {
        "km": "{number}៖ ការជួសជុលបានរួចរាល់។ សូមអរគុណ។",
        "en": "{number}: the repair is done. Thank you.",
    },
    "tenant.step_repair_job": {
        "km": "{number}៖ សូមអរគុណ។ យើងបានរៀបចំការជួសជុល។",
        "en": "{number}: thank you. We have planned a repair.",
    },
    "tenant.step_cleaning": {
        "km": "{number}៖ សូមអរគុណ។ ក្រុមសម្អាតរបស់យើងបានដោះស្រាយរួចហើយ។",
        "en": "{number}: thank you. Our cleaning team has handled it.",
    },
    "tenant.step_handled": {
        "km": "{number}៖ សូមអរគុណ។ អ្នកគ្រប់គ្រងបានដោះស្រាយរួចហើយ។",
        "en": "{number}: thank you. The Manager has handled it.",
    },
    "tenant.step_not_accepted": {
        "km": "{number}៖ យើងបានបិទរបាយការណ៍នេះ ព្រោះវាមិនមែនជាការជួសជុលទេ។ បើមានសំណួរ សូមទាក់ទងការិយាល័យ។",
        "en": "{number}: we closed this report because it is not a repair. "
        "Please contact the office if you have a question.",
    },
    "tenant.step_closed": {
        "km": "{number} បានបិទហើយ។ សូមអរគុណ។",
        "en": "{number} is closed. Thank you.",
    },
    "tenant.step_reopened": {
        "km": "{number} បានបើកម្ដងទៀត។ អ្នកបច្ចេកទេសរបស់យើងនឹងមកម្ដងទៀត។",
        "en": "{number} is open again. Our technician will come back.",
    },
    "tenant.step_joined": {
        "km": "របាយការណ៍ {number} របស់លោកអ្នកត្រូវបានភ្ជាប់ទៅ {main} ដែលជាបញ្ហាដូចគ្នា។ "
        "លោកអ្នកនឹងទទួលបានព័ត៌មានថ្មីៗរបស់វា។",
        "en": "Your report {number} is joined to {main}, the same problem. "
        "You will get its updates.",
    },
    "tenant.check_fixed": {
        "km": "សូមអរគុណ។ {number} បានបិទហើយ។",
        "en": "Thank you. {number} is closed.",
    },
    "tenant.check_not_fixed": {
        "km": "សូមទោស។ {number} បានបើកម្ដងទៀត។ អ្នកបច្ចេកទេសរបស់យើងនឹងមកម្ដងទៀត។",
        "en": "Sorry. {number} is open again. Our technician will come back.",
    },
    "tenant.check_nothing": {
        "km": "ឥឡូវនេះ គ្មានការជួសជុលណាមួយរង់ចាំការពិនិត្យរបស់លោកអ្នកទេ។",
        "en": "No repair is waiting for your check now.",
    },
    "tenant.my_requests": {
        "km": "សំណើរបស់លោកអ្នក (បន្ទប់ {unit})៖\n\n{list}",
        "en": "Your requests (Unit {unit}):\n\n{list}",
    },
    "tenant.my_none": {
        "km": "លោកអ្នកមិនមានសំណើដែលកំពុងបើកទេឥឡូវនេះ។",
        "en": "You have no open requests now.",
    },
    "tenant.my_line": {
        "km": "{number} · {type}៖ {status}",
        "en": "{number} · {type}: {status}",
    },
    "tenant.my_visit": {
        "km": "   មកពិនិត្យ៖ {day} ម៉ោង {time}, {technician}",
        "en": "   Visit: {day} at {time}, {technician}",
    },
    "tenant.my_joined": {
        "km": "{number} · {type}៖ ភ្ជាប់ទៅ {main}",
        "en": "{number} · {type}: joined to {main}",
    },
    # Step 3a (DL-171): the Customer bot, from the owner-approved CRM mock-up (customer bot view)
    # and the FAQ document. Texts marked "new" are not in the mock-up and need the Khmer check.
    "customer.welcome": {
        "km": (
            "សូមស្វាគមន៍មកកាន់ CHETANA Residence។\n"
            "Welcome to CHETANA Residence.\n\n"
            "សូមជ្រើសរើសភាសា។ Please choose a language."
        ),
        "en": (
            "សូមស្វាគមន៍មកកាន់ CHETANA Residence។\n"
            "Welcome to CHETANA Residence.\n\n"
            "សូមជ្រើសរើសភាសា។ Please choose a language."
        ),
    },
    "customer.menu": {
        "km": "តើយើងអាចជួយអ្វីលោកអ្នកបាន?",
        "en": "How can we help you today?",
    },
    "customer.contact_phone": {
        "km": "សូមចែករំលែកលេខទូរស័ព្ទ ដើម្បីឱ្យផ្នែកបម្រើអតិថិជនរបស់យើងអាចទាក់ទងលោកអ្នកបាន។",
        "en": "Please share your phone number so our customer service team can reach you.",
    },
    "customer.contact_ask": {
        "km": "សូមសរសេរសាររបស់លោកអ្នក។",
        "en": "Please write your message.",
    },
    "customer.contact_saved": {
        "km": ("សូមអរគុណ។ ផ្នែកបម្រើអតិថិជនរបស់យើងនឹងឆ្លើយតបពីថ្ងៃច័ន្ទ ដល់ថ្ងៃសៅរ៍ ម៉ោង ០៧:០០ ដល់ ១៧:០០។"),
        "en": (
            "Thank you. Our customer service team will reply Monday to Saturday, 07:00 to 17:00."
        ),
    },
    "customer.ask_how": {
        "km": "តើយើងគួរទាក់ទងអ្នកតាមរបៀបណា?",
        "en": "How should we contact you?",
    },
    "customer.ask_phone": {
        "km": "សូមចែករំលែកលេខទូរស័ព្ទរបស់អ្នក។ បុគ្គលិកនឹងប្រើវាដើម្បីហៅទៅអ្នក។",
        "en": "Please share your phone number. Staff will use it to call you.",
    },
    # new
    "customer.phone_again": {
        "km": "សូមចុច «ចែករំលែកលេខទូរស័ព្ទ» ខាងក្រោម។ យើងត្រូវការលេខរបស់លោកអ្នកផ្ទាល់។",
        "en": "Please tap “Share my phone number” below. We need your own number.",
    },
    "customer.ask_email": {
        "km": "សូមសរសេរអាសយដ្ឋានអ៊ីមែលរបស់អ្នក។",
        "en": "Please type your email address.",
    },
    # new
    "customer.email_again": {
        "km": "អាសយដ្ឋានអ៊ីមែលនេះមិនត្រឹមត្រូវ។ សូមសរសេរម្ដងទៀត ឧទាហរណ៍ name@example.com។",
        "en": "This email address does not look right. Please type it again, "
        "for example name@example.com.",
    },
    "customer.ask_name": {
        "km": "តើអ្នកឈ្មោះអ្វី?",
        "en": "What is your name?",
    },
    "customer.ask_type": {
        "km": "តើអ្នកចង់បានប្រភេទបន្ទប់មួយណា?",
        "en": "Which Unit Type do you want?",
    },
    # new
    "customer.type_again": {
        "km": "សូមចុចលើប្រភេទបន្ទប់មួយខាងក្រោម។",
        "en": "Please tap one of the Unit Types below.",
    },
    "customer.ask_day": {
        "km": "តើអ្នកចង់មកមើលនៅថ្ងៃណា?",
        "en": "Which day would you like to visit?",
    },
    # new
    "customer.day_again": {
        "km": (
            "សូមជ្រើសរើសថ្ងៃខាងក្រោម ឬសរសេរថ្ងៃ ឧទាហរណ៍ 12/11។ "
            "ថ្ងៃមកមើលគឺពី ២ ដល់ ៣០ ថ្ងៃខាងមុខ ពីថ្ងៃច័ន្ទ ដល់ថ្ងៃសៅរ៍។"
        ),
        "en": (
            "Please choose a day below or type one, for example 12/11. "
            "A visit is 2 to 30 days from today, Monday to Saturday."
        ),
    },
    "customer.ask_part": {
        "km": "ពេលព្រឹក ឬពេលរសៀល?",
        "en": "Morning or afternoon?",
    },
    "customer.ask_move": {
        "km": "តើអ្នកចង់ចូលស្នាក់នៅពេលណា?",
        "en": "When do you want to move in?",
    },
    "customer.ask_note": {
        "km": "មានអ្វីផ្សេងទៀតដែលយើងគួរដឹងទេ? អ្នកអាចរំលងបាន។",
        "en": "Anything else we should know? You can skip this.",
    },
    "customer.check": {
        "km": (
            "សូមពិនិត្យសំណើរបស់អ្នក។\n\n"
            "ឈ្មោះ៖ {name}\nទូរស័ព្ទ៖ {phone}\nទាក់ទងតាម៖ {contact}\n"
            "ប្រភេទបន្ទប់៖ {type}\nមកមើល៖ {visit}\nចូលស្នាក់នៅ៖ {move}\nកំណត់សម្គាល់៖ {note}"
        ),
        "en": (
            "Please check your request.\n\n"
            "Name: {name}\nPhone: {phone}\nContact by: {contact}\n"
            "Unit Type: {type}\nVisit: {visit}\nMove in: {move}\nNote: {note}"
        ),
    },
    # new
    "customer.no_day": {"km": "មិនទាន់កំណត់", "en": "No day yet"},
    "customer.request_received": {
        "km": (
            "យើងបានទទួលសំណើរបស់អ្នក។ លេខ៖ {number}។\n"
            "បុគ្គលិកនឹងហៅទៅអ្នកក្នុងរយៈពេល 2 ម៉ោងធ្វើការ។\n"
            "ម៉ោងធ្វើការ៖ ថ្ងៃច័ន្ទ ដល់ថ្ងៃសៅរ៍ ម៉ោង 07:00 ដល់ 17:00។"
        ),
        "en": (
            "We received your request. Number: {number}.\n"
            "Staff will call you within 2 working hours.\n"
            "Working hours: Monday to Saturday, 07:00 to 17:00."
        ),
    },
    # new
    "customer.request_joined": {
        "km": (
            "យើងមានសំណើរបស់អ្នករួចហើយ ({main})។ យើងបានបន្ថែមព័ត៌មាននេះទៅវា (លេខ៖ {number})។\n"
            "បុគ្គលិកនឹងហៅទៅអ្នកក្នុងរយៈពេល 2 ម៉ោងធ្វើការ។\n"
            "ម៉ោងធ្វើការ៖ ថ្ងៃច័ន្ទ ដល់ថ្ងៃសៅរ៍ ម៉ោង 07:00 ដល់ 17:00។"
        ),
        "en": (
            "We already have your request ({main}). We added these details to it "
            "(number {number}).\n"
            "Staff will call you within 2 working hours.\n"
            "Working hours: Monday to Saturday, 07:00 to 17:00."
        ),
    },
    # DL-213: what the relay says while the office app is closed.
    "customer.inquiry_offline": {
        "km": (
            "សូមអរគុណ។ យើងបានទទួលសំណើរបស់អ្នក។ ការិយាល័យរបស់យើងបិទនៅពេលនេះ។ "
            "យើងនឹងផ្ញើលេខសំណើទៅអ្នក ហើយហៅទៅអ្នកនៅពេលការិយាល័យបើក។\n"
            "ម៉ោងធ្វើការ៖ ថ្ងៃច័ន្ទ ដល់ថ្ងៃសៅរ៍ ម៉ោង 07:00 ដល់ 17:00។"
        ),
        "en": (
            "Thank you. We received your request. Our office is closed now. "
            "We will send you the request number and call you when the office opens.\n"
            "Working hours: Monday to Saturday, 07:00 to 17:00."
        ),
    },
    "customer.blocked": {
        "km": "យើងមិនអាចទទួលសំណើពីគណនីនេះបានទេ។ សូមមកការិយាល័យ ឬទូរស័ព្ទមកយើង។",
        "en": "We cannot take requests from this account. Please visit or call the office.",
    },
    "customer.visit_booked": {
        "km": (
            "ការមកមើលរបស់អ្នកត្រូវបានកក់។\n"
            "ថ្ងៃ៖ {day} ម៉ោង {time}\n"
            "អាសយដ្ឋាន៖ {address}\n"
            "បុគ្គលិក៖ {staff}\n"
            "បើចង់ប្ដូរម៉ោង សូមចុច «ទាក់ទងការិយាល័យ»។"
        ),
        "en": (
            "Your visit is booked.\n"
            "Date: {day} at {time}\n"
            "Address: {address}\n"
            "Staff: {staff}\n"
            "To change the time, tap Contact office."
        ),
    },
    "customer.visit_moved": {
        "km": (
            "ការមកមើលរបស់អ្នកត្រូវបានប្ដូរ។\n"
            "ថ្ងៃថ្មី៖ {day} ម៉ោង {time}\n"
            "អាសយដ្ឋាន៖ {address}\n"
            "បុគ្គលិក៖ {staff}\n"
            "បើចង់ប្ដូរម៉ោង សូមចុច «ទាក់ទងការិយាល័យ»។"
        ),
        "en": (
            "Your visit has moved.\n"
            "New date: {day} at {time}\n"
            "Address: {address}\n"
            "Staff: {staff}\n"
            "To change the time, tap Contact office."
        ),
    },
    "customer.visit_reminder": {
        "km": ("រំលឹក៖ ការមកមើល CHETANA Residence របស់អ្នកគឺនៅថ្ងៃស្អែក {day} ម៉ោង {time}។ ជួបគ្នាឆាប់ៗ។"),
        "en": (
            "Reminder: your visit to CHETANA Residence is tomorrow, {day} at {time}. See you soon."
        ),
    },
    # Step 4a: the Staff bot (Khmer only, owner rule; the English is the same Khmer text).
    # The Khmer waits for the native-speaker check.
    "staff.ask_phone": {
        "km": (
            "សួស្តី! នេះជាបូតបុគ្គលិក CHETANA។\n"
            "សូមចុច «ចែករំលែកលេខទូរស័ព្ទ» ខាងក្រោម ដើម្បីស្នើសុំចូលប្រើ។ ម្ចាស់ ឬអ្នកគ្រប់គ្រងនឹងអនុម័ត។"
        ),
        "en": (
            "សួស្តី! នេះជាបូតបុគ្គលិក CHETANA។\n"
            "សូមចុច «ចែករំលែកលេខទូរស័ព្ទ» ខាងក្រោម ដើម្បីស្នើសុំចូលប្រើ។ ម្ចាស់ ឬអ្នកគ្រប់គ្រងនឹងអនុម័ត។"
        ),
    },
    "staff.waiting": {
        "km": "សូមអរគុណ។ សំណើរបស់អ្នកបានផ្ញើហើយ។ អ្នកនឹងទទួលបានសារ នៅពេលម្ចាស់ ឬអ្នកគ្រប់គ្រងអនុម័ត។",
        "en": "សូមអរគុណ។ សំណើរបស់អ្នកបានផ្ញើហើយ។ អ្នកនឹងទទួលបានសារ នៅពេលម្ចាស់ ឬអ្នកគ្រប់គ្រងអនុម័ត។",
    },
    "staff.hello": {
        "km": "សួស្តី {name}។ សូមចុច «របាយការណ៍» ដើម្បីចូលធ្វើការ ចេញពីការងារ ឬបំពេញទម្រង់។",
        "en": "សួស្តី {name}។ សូមចុច «របាយការណ៍» ដើម្បីចូលធ្វើការ ចេញពីការងារ ឬបំពេញទម្រង់។",
    },
    "staff.approved": {
        "km": "អ្នកត្រូវបានអនុម័តហើយ។ សូមចុច «របាយការណ៍» ដើម្បីចាប់ផ្តើម។",
        "en": "អ្នកត្រូវបានអនុម័តហើយ។ សូមចុច «របាយការណ៍» ដើម្បីចាប់ផ្តើម។",
    },
    "staff.refused": {
        "km": "សំណើរបស់អ្នកមិនត្រូវបានអនុម័តទេ។ សូមសួរអ្នកគ្រប់គ្រង។",
        "en": "សំណើរបស់អ្នកមិនត្រូវបានអនុម័តទេ។ សូមសួរអ្នកគ្រប់គ្រង។",
    },
    "staff.not_ready": {
        "km": "បូតបុគ្គលិកមិនទាន់រៀបចំរួចនៅឡើយទេ។ សូមសួរអ្នកគ្រប់គ្រង។",
        "en": "បូតបុគ្គលិកមិនទាន់រៀបចំរួចនៅឡើយទេ។ សូមសួរអ្នកគ្រប់គ្រង។",
    },
    "staff.check_in_ok": {
        "km": "✅ បានចូលធ្វើការ ម៉ោង {time} នៅ {place}។",
        "en": "✅ បានចូលធ្វើការ ម៉ោង {time} នៅ {place}។",
    },
    "staff.check_in_late": {
        "km": "✅ បានចូលធ្វើការ ម៉ោង {time}។ យឺត {minutes} នាទី។",
        "en": "✅ បានចូលធ្វើការ ម៉ោង {time}។ យឺត {minutes} នាទី។",
    },
    "staff.check_in_needs_check": {
        "km": "✅ បានចូលធ្វើការ ម៉ោង {time}។ អ្នកគ្រប់គ្រងនឹងពិនិត្យទីតាំងរបស់អ្នក។",
        "en": "✅ បានចូលធ្វើការ ម៉ោង {time}។ អ្នកគ្រប់គ្រងនឹងពិនិត្យទីតាំងរបស់អ្នក។",
    },
    "staff.check_out_ok": {
        "km": "✅ បានចេញពីការងារ ម៉ោង {time}។ អរគុណ!",
        "en": "✅ បានចេញពីការងារ ម៉ោង {time}។ អរគុណ!",
    },
    "staff.card_in_ok": {
        "km": "✅ បានកត់ត្រាការចូលធ្វើការរបស់ {name} ម៉ោង {time}។",
        "en": "✅ បានកត់ត្រាការចូលធ្វើការរបស់ {name} ម៉ោង {time}។",
    },
    "staff.card_out_ok": {
        "km": "✅ បានកត់ត្រាការចេញពីការងាររបស់ {name} ម៉ោង {time}។",
        "en": "✅ បានកត់ត្រាការចេញពីការងាររបស់ {name} ម៉ោង {time}។",
    },
    "staff.card_not_ready": {
        "km": "❌ ការស្កេនកាតមិនទាន់រៀបចំរួចនៅឡើយទេ។ សូមសួរអ្នកគ្រប់គ្រង។",
        "en": "❌ ការស្កេនកាតមិនទាន់រៀបចំរួចនៅឡើយទេ។ សូមសួរអ្នកគ្រប់គ្រង។",
    },
    "staff.refused_other": {
        "km": "❌ មិនអាចកត់ត្រាបានទេ។ សូមសួរអ្នកគ្រប់គ្រង។",
        "en": "❌ មិនអាចកត់ត្រាបានទេ។ សូមសួរអ្នកគ្រប់គ្រង។",
    },
    "staff.check_refused_bad_scan": {
        "km": "❌ មិនអាចអាន QR បានទេ។ សូមស្កេនម្តងទៀត។",
        "en": "❌ មិនអាចអាន QR បានទេ។ សូមស្កេនម្តងទៀត។",
    },
    "staff.check_refused_not_linked": {
        "km": "❌ គណនីរបស់អ្នកមិនទាន់បានភ្ជាប់ទេ។ សូមសួរអ្នកគ្រប់គ្រង។",
        "en": "❌ គណនីរបស់អ្នកមិនទាន់បានភ្ជាប់ទេ។ សូមសួរអ្នកគ្រប់គ្រង។",
    },
    "staff.check_refused_location_off": {
        "km": "❌ សូមបើក Location នៅលើទូរស័ព្ទ ហើយស្កេនម្តងទៀត។",
        "en": "❌ សូមបើក Location នៅលើទូរស័ព្ទ ហើយស្កេនម្តងទៀត។",
    },
    "staff.check_refused_qr_unknown": {
        "km": "❌ QR នេះមិនមែនជា QR ចូលធ្វើការរបស់ CHETANA ទេ។",
        "en": "❌ QR នេះមិនមែនជា QR ចូលធ្វើការរបស់ CHETANA ទេ។",
    },
    "staff.check_refused_qr_replaced": {
        "km": "❌ QR នេះចាស់ហើយ។ សូមស្កេន QR ថ្មីនៅទីតាំង។",
        "en": "❌ QR នេះចាស់ហើយ។ សូមស្កេន QR ថ្មីនៅទីតាំង។",
    },
    "staff.check_refused_not_working": {
        "km": "❌ ថ្ងៃនេះអ្នកមិនមានវេនធ្វើការទេ។ សូមសួរអ្នកគ្រប់គ្រង។",
        "en": "❌ ថ្ងៃនេះអ្នកមិនមានវេនធ្វើការទេ។ សូមសួរអ្នកគ្រប់គ្រង។",
    },
    "staff.check_refused_already_in": {
        "km": "❌ អ្នកបានចូលធ្វើការរួចហើយ។",
        "en": "❌ អ្នកបានចូលធ្វើការរួចហើយ។",
    },
    "staff.check_refused_too_early": {
        "km": "❌ ឆាប់ពេក។ វេនរបស់អ្នកចាប់ផ្តើមម៉ោង {starts}។ សូមស្កេនម្តងទៀតជិតម៉ោងចាប់ផ្តើម។",
        "en": "❌ ឆាប់ពេក។ វេនរបស់អ្នកចាប់ផ្តើមម៉ោង {starts}។ សូមស្កេនម្តងទៀតជិតម៉ោងចាប់ផ្តើម។",
    },
    "staff.check_refused_not_checked_in": {
        "km": "❌ អ្នកមិនទាន់បានចូលធ្វើការទេ ដូច្នេះមិនអាចចេញបានទេ។",
        "en": "❌ អ្នកមិនទាន់បានចូលធ្វើការទេ ដូច្នេះមិនអាចចេញបានទេ។",
    },
    "staff.check_refused_month_locked": {
        "km": "❌ ខែនេះបានបិទសម្រាប់ប្រាក់ខែហើយ។ សូមសួរអ្នកគ្រប់គ្រង។",
        "en": "❌ ខែនេះបានបិទសម្រាប់ប្រាក់ខែហើយ។ សូមសួរអ្នកគ្រប់គ្រង។",
    },
    "staff.check_refused_not_caretaker": {
        "km": "❌ មានតែអ្នកថែរក្សាអគារ ឬអ្នកអនុម័តទេ ដែលអាចស្កេនកាតបាន។",
        "en": "❌ មានតែអ្នកថែរក្សាអគារ ឬអ្នកអនុម័តទេ ដែលអាចស្កេនកាតបាន។",
    },
    "staff.check_refused_card_unknown": {"km": "❌ កាតនេះមិនស្គាល់ទេ។", "en": "❌ កាតនេះមិនស្គាល់ទេ។"},
    "staff.check_refused_card_stopped": {
        "km": "❌ កាតនេះត្រូវបានប្តូរហើយ។ សូមប្រើកាតថ្មី។",
        "en": "❌ កាតនេះត្រូវបានប្តូរហើយ។ សូមប្រើកាតថ្មី។",
    },
    "staff.check_refused_own_card": {
        "km": "❌ អ្នកមិនអាចស្កេនកាតរបស់ខ្លួនឯងបានទេ។ សូមប្រើ «ចូល» ឬ «ចេញ» នៅលើទូរស័ព្ទរបស់អ្នក។",
        "en": "❌ អ្នកមិនអាចស្កេនកាតរបស់ខ្លួនឯងបានទេ។ សូមប្រើ «ចូល» ឬ «ចេញ» នៅលើទូរស័ព្ទរបស់អ្នក។",
    },
    "staff.check_refused_need_reason": {"km": "❌ សូមជ្រើសរើសមូលហេតុ។", "en": "❌ សូមជ្រើសរើសមូលហេតុ។"},
    "staff.check_refused_need_photo": {"km": "❌ សូមថតរូបបុគ្គលិក។", "en": "❌ សូមថតរូបបុគ្គលិក។"},
    # DL-213: what the relay says while the office app is closed.
    "staff.check_offline": {
        "km": (
            "✅ បានទទួលការស្កេនរបស់អ្នក។ ការិយាល័យបិទនៅពេលនេះ។ "
            "ម៉ោងស្កេនត្រូវបានរក្សាទុក ហើយលទ្ធផលនឹងមកនៅពេលការិយាល័យបើក។"
        ),
        "en": (
            "✅ បានទទួលការស្កេនរបស់អ្នក។ ការិយាល័យបិទនៅពេលនេះ។ "
            "ម៉ោងស្កេនត្រូវបានរក្សាទុក ហើយលទ្ធផលនឹងមកនៅពេលការិយាល័យបើក។"
        ),
    },
    "staff.form_offline": {
        "km": ("✅ បានទទួល។ ការិយាល័យបិទនៅពេលនេះ។ ទម្រង់របស់អ្នកត្រូវបានរក្សាទុក ហើយលេខនឹងមកនៅពេលការិយាល័យបើក។"),
        "en": ("✅ បានទទួល។ ការិយាល័យបិទនៅពេលនេះ។ ទម្រង់របស់អ្នកត្រូវបានរក្សាទុក ហើយលេខនឹងមកនៅពេលការិយាល័យបើក។"),
    },
    "staff.report_offline_urgent": {
        "km": (
            "🚨 បានទទួលរបាយការណ៍បន្ទាន់។ អ្នកថែរក្សាអគារវេន និងអ្នកគ្រប់គ្រងបានទទួលដំណឹងភ្លាមៗ។ "
            "លេខរបាយការណ៍នឹងមកពេលក្រោយ។ ភ្លើងឆេះ 118 · ប៉ូលិស 117"
        ),
        "en": (
            "🚨 បានទទួលរបាយការណ៍បន្ទាន់។ អ្នកថែរក្សាអគារវេន និងអ្នកគ្រប់គ្រងបានទទួលដំណឹងភ្លាមៗ។ "
            "លេខរបាយការណ៍នឹងមកពេលក្រោយ។ ភ្លើងឆេះ 118 · ប៉ូលិស 117"
        ),
    },
    # Step 4b (DL-175): Report a problem, Close job and the urgent alert.
    "staff.report_saved": {
        "km": ("✅ បានទទួល {number}។ បានរក្សាទុកក្នុង «របាយការណ៍បញ្ហា»។ អ្នកគ្រប់គ្រងនឹងរៀបចំការងារ។"),
        "en": ("✅ បានទទួល {number}។ បានរក្សាទុកក្នុង «របាយការណ៍បញ្ហា»។ អ្នកគ្រប់គ្រងនឹងរៀបចំការងារ។"),
    },
    "staff.report_urgent": {
        "km": (
            "🚨 បានទទួល {number} (បន្ទាន់)។ អ្នកថែរក្សាអគារវេន"
            " និងអ្នកគ្រប់គ្រងបានទទួលដំណឹងភ្លាមៗ។ ភ្លើងឆេះ 118 · ប៉ូលិស"
            " 117"
        ),
        "en": (
            "🚨 បានទទួល {number} (បន្ទាន់)។ អ្នកថែរក្សាអគារវេន"
            " និងអ្នកគ្រប់គ្រងបានទទួលដំណឹងភ្លាមៗ។ ភ្លើងឆេះ 118 · ប៉ូលិស"
            " 117"
        ),
    },
    "staff.report_joined": {
        "km": "✅ {number} បានភ្ជាប់ទៅ {main} (បញ្ហាដូចគ្នា)។ សូមអរគុណ។",
        "en": "✅ {number} បានភ្ជាប់ទៅ {main} (បញ្ហាដូចគ្នា)។ សូមអរគុណ។",
    },
    "staff.report_invalid": {
        "km": (
            "❌ របាយការណ៍មិនទាន់គ្រប់គ្រាន់។ សូមជ្រើសប្រភេទ បន្ទប់"
            " ឬកន្លែង បញ្ហា ថតរូប ១ សន្លឹក ហើយសរសេរ ឬថតសារជាសំឡេង។"
        ),
        "en": (
            "❌ របាយការណ៍មិនទាន់គ្រប់គ្រាន់។ សូមជ្រើសប្រភេទ បន្ទប់"
            " ឬកន្លែង បញ្ហា ថតរូប ១ សន្លឹក ហើយសរសេរ ឬថតសារជាសំឡេង។"
        ),
    },
    "staff.close_done": {
        "km": "✅ {number} រួចរាល់ · គ្មានថ្លៃ។",
        "en": "✅ {number} រួចរាល់ · គ្មានថ្លៃ។",
    },
    "staff.close_done_cost": {
        "km": ("✅ {number} រួចរាល់ · ${amount} + វិក្កយបត្រ។ អ្នកគ្រប់គ្រងនឹងពិនិត្យថ្លៃ។"),
        "en": ("✅ {number} រួចរាល់ · ${amount} + វិក្កយបត្រ។ អ្នកគ្រប់គ្រងនឹងពិនិត្យថ្លៃ។"),
    },
    "staff.close_not_open": {
        "km": "❌ {number} មិនមែនជាការងារដែលរង់ចាំជួសជុលទៀតទេ។",
        "en": "❌ {number} មិនមែនជាការងារដែលរង់ចាំជួសជុលទៀតទេ។",
    },
    "staff.close_cost_checked": {
        "km": ("❌ ថ្លៃរបស់ {number} ត្រូវបានពិនិត្យរួចហើយ។ សូមទាក់ទងអ្នកគ្រប់គ្រង។"),
        "en": ("❌ ថ្លៃរបស់ {number} ត្រូវបានពិនិត្យរួចហើយ។ សូមទាក់ទងអ្នកគ្រប់គ្រង។"),
    },
    "staff.close_not_technician": {
        "km": "❌ មានតែអ្នកបច្ចេកទេសទេ ដែលអាចបិទការងារបាន។",
        "en": "❌ មានតែអ្នកបច្ចេកទេសទេ ដែលអាចបិទការងារបាន។",
    },
    "staff.close_invalid": {
        "km": ("❌ សូមថតរូបក្រោយជួសជុល ហើយជ្រើសថ្លៃ (មានថ្លៃ ត្រូវមានចំនួន និងរូបថតវិក្កយបត្រ)។"),
        "en": ("❌ សូមថតរូបក្រោយជួសជុល ហើយជ្រើសថ្លៃ (មានថ្លៃ ត្រូវមានចំនួន និងរូបថតវិក្កយបត្រ)។"),
    },
    "staff.meter_sent": {
        "km": "✅ បានទទួលអំណានមីទ័រ {count}។ អ្នកគ្រប់គ្រងនឹងពិនិត្យ និងបញ្ជាក់ មុនចេញវិក្កយបត្រទឹកភ្លើង។",
        "en": "✅ បានទទួលអំណានមីទ័រ {count}។ អ្នកគ្រប់គ្រងនឹងពិនិត្យ និងបញ្ជាក់ មុនចេញវិក្កយបត្រទឹកភ្លើង។",
    },
    "staff.meter_sent_flagged": {
        "km": "✅ បានទទួលអំណានមីទ័រ {count} · {flagged} ត្រូវពិនិត្យ។ អ្នកគ្រប់គ្រងនឹងពិនិត្យ និងបញ្ជាក់។",
        "en": "✅ បានទទួលអំណានមីទ័រ {count} · {flagged} ត្រូវពិនិត្យ។ អ្នកគ្រប់គ្រងនឹងពិនិត្យ និងបញ្ជាក់។",
    },
    "staff.meter_not_reader": {
        "km": "❌ ទម្រង់អំណានមីទ័រ សម្រាប់អ្នកអានមីទ័រប៉ុណ្ណោះ។",
        "en": "❌ ទម្រង់អំណានមីទ័រ សម្រាប់អ្នកអានមីទ័រប៉ុណ្ណោះ។",
    },
    "staff.meter_invalid": {
        "km": "❌ អំណានមិនត្រឹមត្រូវ។ សូមពិនិត្យលេខ ហើយផ្ញើម្តងទៀត។",
        "en": "❌ អំណានមិនត្រឹមត្រូវ។ សូមពិនិត្យលេខ ហើយផ្ញើម្តងទៀត។",
    },
    "staff.meter_again": {
        "km": "🔁 សូមកត់អំណាន {units} ម្តងទៀត ហើយផ្ញើក្នុងទម្រង់អំណានមីទ័រ។",
        "en": "🔁 សូមកត់អំណាន {units} ម្តងទៀត ហើយផ្ញើក្នុងទម្រង់អំណានមីទ័រ។",
    },
    "staff.meter_check_saved": {
        "km": "✅ បានផ្ញើសំណើពិនិត្យមីទ័រ {number} ទៅក្រុមបច្ចេកទេស។",
        "en": "✅ បានផ្ញើសំណើពិនិត្យមីទ័រ {number} ទៅក្រុមបច្ចេកទេស។",
    },
    "staff.meter_check_invalid": {
        "km": "❌ សូមជ្រើសមីទ័រ និងបញ្ហា (ផ្សេងៗ ត្រូវសរសេរកំណត់សម្គាល់)។",
        "en": "❌ សូមជ្រើសមីទ័រ និងបញ្ហា (ផ្សេងៗ ត្រូវសរសេរកំណត់សម្គាល់)។",
    },
    "staff.checklist_sent": {
        "km": "✅ បានទទួលបញ្ជីប្រចាំថ្ងៃ៖ ធ្វើរួច {done}/{total}។ អរគុណ!",
        "en": "✅ បានទទួលបញ្ជីប្រចាំថ្ងៃ៖ ធ្វើរួច {done}/{total}។ អរគុណ!",
    },
    "staff.checklist_sent_problems": {
        "km": (
            "✅ បានទទួលបញ្ជីប្រចាំថ្ងៃ៖ ធ្វើរួច {done}/{total} · មិនបានធ្វើ ឬមានបញ្ហា {problems}។ "
            "បើមានអ្វីខូច សូមរាយការណ៍បញ្ហាផងដែរ។"
        ),
        "en": (
            "✅ បានទទួលបញ្ជីប្រចាំថ្ងៃ៖ ធ្វើរួច {done}/{total} · មិនបានធ្វើ ឬមានបញ្ហា {problems}។ "
            "បើមានអ្វីខូច សូមរាយការណ៍បញ្ហាផងដែរ។"
        ),
    },
    "staff.checklist_not_cleaner": {
        "km": "❌ បញ្ជីសម្អាត សម្រាប់តែអ្នកសម្អាតប៉ុណ្ណោះ។",
        "en": "❌ បញ្ជីសម្អាត សម្រាប់តែអ្នកសម្អាតប៉ុណ្ណោះ។",
    },
    "staff.checklist_not_caretaker": {
        "km": "❌ បញ្ជីវេន និងការល្បាត សម្រាប់តែអ្នកថែរក្សាអគារប៉ុណ្ណោះ។",
        "en": "❌ បញ្ជីវេន និងការល្បាត សម្រាប់តែអ្នកថែរក្សាអគារប៉ុណ្ណោះ។",
    },
    "staff.checklist_not_technician": {
        "km": "❌ បញ្ជីបច្ចេកទេស សម្រាប់តែអ្នកបច្ចេកទេសប៉ុណ្ណោះ។",
        "en": "❌ បញ្ជីបច្ចេកទេស សម្រាប់តែអ្នកបច្ចេកទេសប៉ុណ្ណោះ។",
    },
    "staff.checklist_no_shift": {
        "km": "❌ ឥឡូវនេះ អ្នកមិនមានវេនក្នុងបញ្ជីបុគ្គលិកទេ។ សូមសួរអ្នកគ្រប់គ្រង។",
        "en": "❌ ឥឡូវនេះ អ្នកមិនមានវេនក្នុងបញ្ជីបុគ្គលិកទេ។ សូមសួរអ្នកគ្រប់គ្រង។",
    },
    "staff.checklist_nothing_due": {
        "km": "📌 ថ្ងៃនេះគ្មានការងារក្នុងបញ្ជីនេះទេ។",
        "en": "📌 ថ្ងៃនេះគ្មានការងារក្នុងបញ្ជីនេះទេ។",
    },
    "staff.checklist_invalid": {
        "km": "❌ មិនអាចរក្សាទុកបញ្ជីបានទេ។ សូមឆ្លើយគ្រប់ការងារ ហើយផ្ញើម្តងទៀត។",
        "en": "❌ មិនអាចរក្សាទុកបញ្ជីបានទេ។ សូមឆ្លើយគ្រប់ការងារ ហើយផ្ញើម្តងទៀត។",
    },
    "staff.patrol_sent": {
        "km": "✅ បានទទួលការល្បាត {round} នៅម៉ោង {at}។",
        "en": "✅ បានទទួលការល្បាត {round} នៅម៉ោង {at}។",
    },
    "staff.patrol_done_before": {
        "km": "📌 ការល្បាត {round} បានផ្ញើរួចហើយ នៅម៉ោង {at}។",
        "en": "📌 ការល្បាត {round} បានផ្ញើរួចហើយ នៅម៉ោង {at}។",
    },
    "staff.patrol_too_early": {
        "km": "❌ មិនទាន់ដល់ម៉ោងល្បាត {round} នៅឡើយទេ។ អាចផ្ញើបាន 30 នាទីមុនម៉ោង។",
        "en": "❌ មិនទាន់ដល់ម៉ោងល្បាត {round} នៅឡើយទេ។ អាចផ្ញើបាន 30 នាទីមុនម៉ោង។",
    },
    "staff.patrol_invalid": {
        "km": "❌ សូមជ្រើសកន្លែងដែលបានល្បាត ហើយផ្ញើម្តងទៀត។",
        "en": "❌ សូមជ្រើសកន្លែងដែលបានល្បាត ហើយផ្ញើម្តងទៀត។",
    },
    "staff.unit_check_good": {
        "km": "✅ បានទទួលការត្រួតពិនិត្យបន្ទប់។ ល្អទាំងអស់។ អរគុណ!",
        "en": "✅ បានទទួលការត្រួតពិនិត្យបន្ទប់។ ល្អទាំងអស់។ អរគុណ!",
    },
    "staff.unit_check_findings": {
        "km": (
            "✅ បានទទួលការត្រួតពិនិត្យបន្ទប់ · រកឃើញ {count}៖ {numbers}។"
            " បានរក្សាទុកក្នុង «របាយការណ៍បញ្ហា»។ អ្នកគ្រប់គ្រងនឹងរៀបចំការងារ។"
        ),
        "en": (
            "✅ បានទទួលការត្រួតពិនិត្យបន្ទប់ · រកឃើញ {count}៖ {numbers}។"
            " បានរក្សាទុកក្នុង «របាយការណ៍បញ្ហា»។ អ្នកគ្រប់គ្រងនឹងរៀបចំការងារ។"
        ),
    },
    "staff.unit_check_invalid": {
        "km": ("❌ សូមជ្រើសបន្ទប់ ប្រភេទ និងតំបន់។ តំបន់ខូច ឬបាត់ ត្រូវសរសេរ និងថតរូប (សរុបរហូតដល់ 5)។"),
        "en": ("❌ សូមជ្រើសបន្ទប់ ប្រភេទ និងតំបន់។ តំបន់ខូច ឬបាត់ ត្រូវសរសេរ និងថតរូប (សរុបរហូតដល់ 5)។"),
    },
    "staff.tech_only": {
        "km": "❌ ទម្រង់នេះ សម្រាប់តែអ្នកបច្ចេកទេស និងអ្នកអនុម័តប៉ុណ្ណោះ។",
        "en": "❌ ទម្រង់នេះ សម្រាប់តែអ្នកបច្ចេកទេស និងអ្នកអនុម័តប៉ុណ្ណោះ។",
    },
    "staff.maint_checked": {
        "km": "✅ {number} បានពិនិត្យរួច។ អ្នកគ្រប់គ្រងនឹងសម្រេចថាអ្នកណាបង់ ក្នុងកម្មវិធី។",
        "en": "✅ {number} បានពិនិត្យរួច។ អ្នកគ្រប់គ្រងនឹងសម្រេចថាអ្នកណាបង់ ក្នុងកម្មវិធី។",
    },
    "staff.maint_fixed": {
        "km": ("✅ {number} បានពិនិត្យ និងជួសជុលរួច។ អ្នកគ្រប់គ្រងនឹងសម្រេចថាអ្នកណាបង់ ក្នុងកម្មវិធី។"),
        "en": ("✅ {number} បានពិនិត្យ និងជួសជុលរួច។ អ្នកគ្រប់គ្រងនឹងសម្រេចថាអ្នកណាបង់ ក្នុងកម្មវិធី។"),
    },
    "staff.maint_not_planned": {
        "km": "❌ {number} មិនមែនជាការមកពិនិត្យដែលបានរៀបចំទៀតទេ។",
        "en": "❌ {number} មិនមែនជាការមកពិនិត្យដែលបានរៀបចំទៀតទេ។",
    },
    "staff.maint_invalid": {
        "km": (
            "❌ សូមជ្រើសការងារ របៀបចូលបន្ទប់ មូលហេតុ ហើយថតរូប 1 ដល់ 5 សន្លឹក។ ជួសជុលភ្លាមៗ បានតែការងារបន្ទាន់ប៉ុណ្ណោះ។"
        ),
        "en": (
            "❌ សូមជ្រើសការងារ របៀបចូលបន្ទប់ មូលហេតុ ហើយថតរូប 1 ដល់ 5 សន្លឹក។ ជួសជុលភ្លាមៗ បានតែការងារបន្ទាន់ប៉ុណ្ណោះ។"
        ),
    },
    "staff.daily_summary": {
        "km": "📋 សង្ខេបប្រចាំថ្ងៃ {date}\n\n{list}",
        "en": "📋 សង្ខេបប្រចាំថ្ងៃ {date}\n\n{list}",
    },
    "staff.urgent": {
        "km": "🚨 បន្ទាន់ {number}៖ {type} · {where}។ សូមទៅមើលភ្លាមៗ។",
        "en": "🚨 បន្ទាន់ {number}៖ {type} · {where}។ សូមទៅមើលភ្លាមៗ។",
    },
    # DL-210: the same alert sent by the relay while the office app is closed (no number yet).
    "staff.urgent_offline": {
        "km": "🚨 បន្ទាន់៖ {type} · {where}។ សូមទៅមើលភ្លាមៗ។ លេខរបាយការណ៍នឹងមកពេលក្រោយ។",
        "en": "🚨 បន្ទាន់៖ {type} · {where}។ សូមទៅមើលភ្លាមៗ។ លេខរបាយការណ៍នឹងមកពេលក្រោយ។",
    },
    # Report states as the tenant sees them (the app's words, Building > Problem reports).
    "status.RECEIVED": {"km": "បានទទួល", "en": "Received"},
    "status.PLANNED": {"km": "បានរៀបចំការមកពិនិត្យ", "en": "Visit planned"},
    "status.CHECKED": {"km": "បានពិនិត្យ", "en": "Checked"},
    "status.WAITING_TENANT": {"km": "រង់ចាំចម្លើយរបស់លោកអ្នក", "en": "Waiting for your answer"},
    "status.REPAIR_PLANNED": {"km": "បានរៀបចំការជួសជុល", "en": "Repair planned"},
    "status.WAITING_PARTS": {"km": "រង់ចាំគ្រឿងបន្លាស់", "en": "Waiting for parts"},
    "status.DONE": {"km": "រួចរាល់ សូមពិនិត្យ", "en": "Done, please check"},
    "status.CLOSED": {"km": "បានបិទ", "en": "Closed"},
    "status.NOT_ACCEPTED": {"km": "មិនមែនជាការជួសជុល", "en": "Not a repair"},
    "status.JOINED": {"km": "បានភ្ជាប់", "en": "Joined"},
    # Button labels (no fields). The bot reads a tap as the label's text in either language.
    "button.link": {"km": "ភ្ជាប់កិច្ចសន្យាជួល", "en": "Link my Lease"},
    "button.share_phone": {"km": "ចែករំលែកលេខទូរស័ព្ទ", "en": "Share my phone number"},
    "button.problem": {"km": "រាយការណ៍បញ្ហា", "en": "Problem report"},
    "button.my_requests": {"km": "សំណើរបស់ខ្ញុំ", "en": "My requests"},
    "button.faq": {"km": "សំណួរញឹកញាប់", "en": "FAQ"},
    "button.contact": {"km": "ទាក់ទងការិយាល័យ", "en": "Contact office"},
    "button.unit_problem": {"km": "បញ្ហាក្នុងបន្ទប់", "en": "Unit Problem"},
    "button.building_problem": {"km": "បញ្ហាអគារ", "en": "Building problem"},
    "button.back_menu": {"km": "ត្រឡប់ទៅម៉ឺនុយ", "en": "Back to menu"},
    "button.fixed": {"km": "ជួសជុលរួច", "en": "Fixed"},
    "button.not_fixed": {"km": "មិនទាន់រួច", "en": "Not fixed"},
    "button.khmer": {"km": "ភាសាខ្មែរ", "en": "ភាសាខ្មែរ"},
    "button.english": {"km": "English", "en": "English"},
    # Customer bot buttons (step 3a, CRM mock-up).
    "button.inquiry": {"km": "ផ្ញើការសាកសួរ", "en": "Send an inquiry"},
    "button.by_telegram": {"km": "Telegram", "en": "Telegram"},
    "button.by_email": {"km": "អ៊ីមែល", "en": "Email"},
    "button.by_phone": {"km": "ទូរស័ព្ទ ឬ SMS", "en": "Phone call or SMS"},
    "button.by_whatsapp": {"km": "WhatsApp", "en": "WhatsApp"},
    "button.morning": {"km": "ពេលព្រឹក", "en": "Morning"},
    "button.afternoon": {"km": "ពេលរសៀល", "en": "Afternoon"},
    "button.later": {"km": "ក្រោយ", "en": "Later"},
    "button.skip": {"km": "រំលង", "en": "Skip"},
    # Staff bot (step 4a): the button that opens the Staff forms; Khmer only.
    "button.reports": {"km": "របាយការណ៍", "en": "របាយការណ៍"},
}

# The keyboards a message can show under the chat. Each button is a label code above; a
# button that asks for the person's own phone number is marked.
KEYBOARDS: Final[dict[str, list[list[str]]]] = {
    "tenant.language": [["button.khmer", "button.english"]],
    "tenant.start": [["button.link"]],
    "tenant.share_phone": [["button.share_phone"]],
    "tenant.menu": [["button.problem", "button.my_requests"], ["button.faq", "button.contact"]],
    "tenant.reject": [["button.link", "button.contact"]],
    "tenant.check": [["button.fixed", "button.not_fixed"], ["button.my_requests"]],
    "tenant.back": [["button.back_menu"]],
    # Step 3a: the Customer bot.
    "customer.menu": [["button.inquiry"], ["button.faq", "button.contact"]],
    "customer.how": [
        ["button.by_telegram", "button.by_email"],
        ["button.by_phone", "button.by_whatsapp"],
        ["button.back_menu"],
    ],
    "customer.share_phone": [["button.share_phone"], ["button.back_menu"]],
    "customer.part": [["button.morning", "button.afternoon"], ["button.back_menu"]],
    "customer.skip": [["button.skip"], ["button.back_menu"]],
    "customer.send": [["button.inquiry"], ["button.back_menu"]],
    # Step 4a: the Staff bot.
    "staff.share_phone": [["button.share_phone"]],
}
# Keyboards whose first buttons the bot builds (details[field], one button a row), followed by
# fixed rows.
CHOICE_KEYBOARDS: Final[dict[str, tuple[str, list[list[str]]]]] = {
    "tenant.faq": ("choices", [["button.back_menu"]]),
    "customer.faq": ("choices", [["button.back_menu"]]),
    "customer.types": ("choices", [["button.back_menu"]]),
    "customer.days": ("choices", [["button.skip"], ["button.back_menu"]]),
    "customer.months": ("choices", [["button.later"], ["button.back_menu"]]),
}
CONTACT_BUTTONS: Final = frozenset({"button.share_phone"})
# Buttons on the message itself that open a Mini App form on the relay
# (https://<relay>/app/<bot>?form=<form>&lang=<language>). Telegram signs who opens it.
APP_KEYBOARDS: Final[dict[str, tuple[str, list[list[tuple[str, str]]]]]] = {
    "tenant.report_kind": (
        "tenant",
        [[("button.unit_problem", "unit")], [("button.building_problem", "building")]],
    ),
    "staff.open": ("staff", [[("button.reports", "home")]]),
}
REMOVE_KEYBOARD: Final = "remove"


class TextError(KeyError):
    """The text code is unknown, or a field it needs is missing."""


def text_fields(code: str) -> set[str]:
    template = TEXTS[code]["en"]
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def render(code: str, language: str, details: Mapping[str, object]) -> str:
    """The message text for one outbox row."""
    texts = TEXTS.get(code)
    if texts is None:
        raise TextError(code)
    template = texts.get(language) or texts["km"]
    values: dict[str, str] = {}
    for name in text_fields(code):
        value = details.get(name)
        if value is None or isinstance(value, dict | list):
            raise TextError(f"{code}.{name}")
        values[name] = str(value)[: LONG_FIELDS.get(name, MAX_FIELD_CHARACTERS)]
    return template.format_map(values)[:MAX_MESSAGE_CHARACTERS]


def keyboard_markup(
    code: str | None,
    language: str,
    app_host: str | None = None,
    details: Mapping[str, object] | None = None,
) -> dict[str, object] | None:
    """Telegram's reply_markup for a keyboard code, or None when the message has none."""
    if code is None:
        return None
    if code == REMOVE_KEYBOARD:
        return {"remove_keyboard": True}
    if code in CHOICE_KEYBOARDS:
        field, fixed_rows = CHOICE_KEYBOARDS[code]
        choices = (details or {}).get(field)
        if not isinstance(choices, list) or not all(isinstance(item, str) for item in choices):
            raise TextError(f"keyboard.{code}.{field}")
        built: list[list[dict[str, object]]] = [
            [{"text": choice[:MAX_CHOICE_CHARACTERS]}]
            for choice in choices[:MAX_CHOICES]
            if choice.strip()
        ]
        built += [[{"text": render(label, language, {})} for label in row] for row in fixed_rows]
        return {"keyboard": built, "resize_keyboard": True}
    if code in APP_KEYBOARDS:
        if not app_host:
            raise TextError(f"keyboard.{code}.no_app_host")
        page, app_rows = APP_KEYBOARDS[code]
        return {
            "inline_keyboard": [
                [
                    {
                        "text": render(label, language, {}),
                        "web_app": {
                            "url": f"https://{app_host}/app/{page}?form={form}&lang={language}"
                        },
                    }
                    for label, form in row
                ]
                for row in app_rows
            ]
        }
    rows = KEYBOARDS.get(code)
    if rows is None:
        raise TextError(f"keyboard.{code}")
    keyboard = [
        [
            {"text": render(label, language, {}), "request_contact": True}
            if label in CONTACT_BUTTONS
            else {"text": render(label, language, {})}
            for label in row
        ]
        for row in rows
    ]
    return {"keyboard": keyboard, "resize_keyboard": True}


def button_tapped(text: str) -> str | None:
    """The label code a typed text is, in either language, or None."""
    typed = text.strip()
    for code, texts in TEXTS.items():
        if code.startswith("button.") and typed in texts.values():
            return code
    return None
