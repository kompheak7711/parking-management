// The Tenant bot's Problem report form (bots plan step 2b, DL-127; owner rules of 3 Nov 2026,
// tenant mock-up v15). A Telegram Mini App page served by the relay at /app/tenant. It holds no
// data: it asks /form/tenant/start with the person's Telegram sign-in for the problem types,
// the shared places, the open Building problems and the places in the person's Unit, then sends
// the form to /form/tenant. The office saves the report and the bot answers in the chat.
//
// Unit Problem: the type (pictures first), the place in the Unit, what is wrong (text, a voice
// note up to 1 minute, or both), up to 5 photos, urgent, may staff enter when you are out, and
// the best time. Building problem: where (and the floor), the type, then the open reports there
// with "Same problem" or "Something else". Safety, flooding and a risk of electric shock are
// always urgent and show the safety steps first. The Khmer waits for the native-speaker check.

const PAGE = String.raw`<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CHETANA Residence support</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root { --bg: #ffffff; --fg: #1d2330; --muted: #5f6b7a; --line: #d8dee6; --accent: #2a6fdb;
    --accent-fg: #ffffff; --soft: #f2f5f9; --warn: #b42318; --warn-soft: #fdecea; }
  body { margin: 0; font: 16px/1.45 -apple-system, "Segoe UI", Roboto, "Noto Sans Khmer", sans-serif;
    background: var(--tg-theme-bg-color, var(--bg)); color: var(--tg-theme-text-color, var(--fg)); }
  main { padding: 16px; max-width: 560px; margin: 0 auto; }
  h1 { font-size: 20px; margin: 0 0 12px; }
  h2 { font-size: 16px; margin: 20px 0 8px; }
  p.hint { color: var(--tg-theme-hint-color, var(--muted)); font-size: 14px; margin: 4px 0 8px; }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .tile, .choice { border: 1px solid var(--line); border-radius: 10px; background: var(--soft);
    color: inherit; font: inherit; padding: 10px 6px; text-align: center; cursor: pointer; }
  .tile .icon { display: block; font-size: 26px; }
  .tile.on, .choice.on { border-color: var(--accent); outline: 2px solid var(--accent); }
  .row { display: flex; gap: 8px; flex-wrap: wrap; }
  .row .choice { flex: 1 1 30%; }
  textarea, input[type=text], select { width: 100%; box-sizing: border-box; font: inherit;
    border: 1px solid var(--line); border-radius: 10px; padding: 10px; background: inherit;
    color: inherit; }
  textarea { min-height: 96px; }
  .safety { border: 2px solid var(--warn); background: var(--warn-soft); color: #5a1209;
    border-radius: 12px; padding: 12px; margin: 12px 0; }
  .safety ol { margin: 6px 0 6px 20px; padding: 0; }
  .open { border: 1px solid var(--line); border-radius: 10px; padding: 10px; margin: 6px 0;
    display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .thumbs { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
  .thumbs figure { margin: 0; position: relative; }
  .thumbs img { width: 72px; height: 72px; object-fit: cover; border-radius: 8px; }
  .thumbs button { position: absolute; top: -6px; right: -6px; border-radius: 50%; border: 0;
    width: 24px; height: 24px; background: var(--warn); color: #fff; cursor: pointer; }
  button.main { width: 100%; margin-top: 20px; padding: 14px; border: 0; border-radius: 12px;
    background: var(--tg-theme-button-color, var(--accent));
    color: var(--tg-theme-button-text-color, var(--accent-fg)); font: inherit; font-weight: 600; }
  button.small { padding: 8px 12px; border-radius: 8px; border: 1px solid var(--line);
    background: var(--soft); color: inherit; font: inherit; cursor: pointer; }
  .error { color: var(--warn); font-weight: 600; margin-top: 12px; }
  .done { text-align: center; padding: 40px 0; font-size: 18px; }
  [hidden] { display: none !important; }
</style>
</head>
<body>
<main id="app"><p class="hint" id="loading">…</p></main>
<script>
"use strict";
(function () {
  var T = {
    en: {
      unit: "Unit Problem", building: "Building problem", loading: "Loading…",
      not_linked: "Please link your Lease first in the chat.",
      failed: "The form could not open. Please close it and try again.",
      what_type: "What is the problem? Tap a picture.",
      danger_WATER: "Is water flooding the floor?",
      danger_ELECTRICITY: "Is there a risk of electric shock? For example sparks, a wet socket or a burning smell.",
      yes: "Yes", no: "No",
      safety: "Safety first: do this now",
      steps_WATER: ["Turn off the water valve only if you can do it safely.", "Keep away from sockets and wires near the water.", "Move your things off the floor."],
      steps_ELECTRICITY: ["Do not touch the socket, the wires or anything wet near them.", "Turn off the main switch only if it is dry and safe.", "Keep children away."],
      steps_SAFETY: ["Leave the room and close the door.", "Do not use the lift.", "If you smell gas, do not switch lights on or off."],
      call: "Fire 118 · Police 117",
      always_urgent: "This report is always urgent. When you send it, the caretaker on shift and the Manager get an alert at once.",
      where_unit: "Where in your Unit?", other_place: "Other or not sure",
      where_building: "Where in the building?", floor: "Floor (if you know it)",
      open_here: "Open reports here. Is it the same problem?", same: "Same problem",
      something_else: "Something else", joined_note: "Thank you. You can add a short note, or just send.",
      what_wrong: "What is wrong?", what_wrong_hint: "Write what is wrong, or send a voice note, or both.",
      record: "🎤 Record a voice note (up to 1 minute)", stop: "■ Stop", recording: "Recording… ",
      voice: "🎤 Voice note ", remove: "Delete", no_mic: "The microphone cannot be used here. Please write instead.",
      photos: "Photos (up to 5)", add_photo: "+ Add a photo",
      urgent: "Is it urgent?",
      urgent_hint: "Urgent means: water leaking, no power, no water, door cannot lock, gas or burning smell. Fire or danger: call 118 (fire) or 117 (police) first.",
      enter: "May staff enter when you are out?", enter_hint: "If yes, two staff come and take photos before and after.",
      best: "Best time to come", AM: "Morning", PM: "Afternoon", ANY: "Any time",
      send: "Send report", sending: "Sending…",
      need_type: "Please tap the problem type.", need_danger: "Please answer the safety question.",
      need_where: "Please choose where in the building.",
      need_text: "Please write what is wrong, or send a voice note.",
      need_urgent: "Please answer: is it urgent?", need_enter: "Please answer: may staff enter when you are out?",
      too_many: "Too many tries. Please wait a minute.",
      sent: "Sent. We will answer you in the chat."
    },
    km: {
      unit: "បញ្ហាក្នុងបន្ទប់", building: "បញ្ហាអគារ", loading: "កំពុងផ្ទុក…",
      not_linked: "សូមភ្ជាប់កិច្ចសន្យាជួលរបស់លោកអ្នកក្នុងការជជែកជាមុនសិន។",
      failed: "មិនអាចបើកទម្រង់បានទេ។ សូមបិទ ហើយព្យាយាមម្ដងទៀត។",
      what_type: "តើមានបញ្ហាអ្វី? សូមចុចលើរូបភាព។",
      danger_WATER: "តើទឹកកំពុងលិចកម្រាលឥដ្ឋឬទេ?",
      danger_ELECTRICITY: "តើមានគ្រោះថ្នាក់ឆក់ខ្សែភ្លើងឬទេ? ឧទាហរណ៍ ផ្កាភ្លើង ព្រីសើម ឬក្លិនឆេះ។",
      yes: "បាទ/ចាស", no: "ទេ",
      safety: "សុវត្ថិភាពជាមុន៖ សូមធ្វើដូចនេះឥឡូវនេះ",
      steps_WATER: ["បិទសន្ទះទឹក លុះត្រាតែលោកអ្នកអាចធ្វើបានដោយសុវត្ថិភាព។", "នៅឆ្ងាយពីព្រីភ្លើង និងខ្សែភ្លើងដែលនៅជិតទឹក។", "លើករបស់របររបស់លោកអ្នកចេញពីកម្រាល។"],
      steps_ELECTRICITY: ["កុំប៉ះព្រីភ្លើង ខ្សែភ្លើង ឬអ្វីដែលសើមនៅជិតវា។", "បិទកុងតាក់មេ លុះត្រាតែវាស្ងួត និងមានសុវត្ថិភាព។", "ឲ្យកុមារនៅឆ្ងាយ។"],
      steps_SAFETY: ["ចេញពីបន្ទប់ ហើយបិទទ្វារ។", "កុំប្រើជណ្ដើរយន្ត។", "បើធុំក្លិនហ្គាស កុំបើក ឬបិទភ្លើង។"],
      call: "អគ្គិភ័យ 118 · ប៉ូលិស 117",
      always_urgent: "របាយការណ៍នេះតែងតែបន្ទាន់។ ពេលលោកអ្នកផ្ញើ អ្នកថែទាំប្រចាំការ និងអ្នកគ្រប់គ្រងនឹងទទួលបានការជូនដំណឹងភ្លាមៗ។",
      where_unit: "នៅកន្លែងណាក្នុងបន្ទប់របស់លោកអ្នក?", other_place: "ផ្សេងទៀត ឬមិនច្បាស់",
      where_building: "នៅកន្លែងណាក្នុងអគារ?", floor: "ជាន់ (បើលោកអ្នកដឹង)",
      open_here: "របាយការណ៍ដែលកំពុងបើកនៅទីនេះ។ តើជាបញ្ហាដូចគ្នាឬទេ?", same: "បញ្ហាដូចគ្នា",
      something_else: "បញ្ហាផ្សេង", joined_note: "សូមអរគុណ។ លោកអ្នកអាចបន្ថែមកំណត់ចំណាំខ្លី ឬផ្ញើតែម្ដង។",
      what_wrong: "តើមានអ្វីខុសប្រក្រតី?", what_wrong_hint: "សូមសរសេរ ឬផ្ញើសារជាសំឡេង ឬទាំងពីរ។",
      record: "🎤 ថតសារជាសំឡេង (រហូតដល់ 1 នាទី)", stop: "■ ឈប់", recording: "កំពុងថត… ",
      voice: "🎤 សារជាសំឡេង ", remove: "លុប", no_mic: "មិនអាចប្រើមីក្រូហ្វូននៅទីនេះបានទេ។ សូមសរសេរជំនួសវិញ។",
      photos: "រូបថត (រហូតដល់ 5)", add_photo: "+ បន្ថែមរូបថត",
      urgent: "តើបន្ទាន់ឬទេ?",
      urgent_hint: "បន្ទាន់មានន័យថា៖ ទឹកលេច គ្មានភ្លើង គ្មានទឹក ទ្វារចាក់សោមិនបាន ក្លិនហ្គាស ឬក្លិនឆេះ។ ភ្លើងឆេះ ឬគ្រោះថ្នាក់៖ សូមទូរស័ព្ទ 118 ឬ 117 ជាមុនសិន។",
      enter: "តើបុគ្គលិកអាចចូលពេលលោកអ្នកមិននៅបានទេ?", enter_hint: "បើបាន បុគ្គលិកពីរនាក់នឹងមក ហើយថតរូបមុន និងក្រោយ។",
      best: "ពេលល្អបំផុតដើម្បីមក", AM: "ពេលព្រឹក", PM: "ពេលរសៀល", ANY: "ពេលណាក៏បាន",
      send: "ផ្ញើរបាយការណ៍", sending: "កំពុងផ្ញើ…",
      need_type: "សូមចុចលើប្រភេទបញ្ហា។", need_danger: "សូមឆ្លើយសំណួរសុវត្ថិភាព។",
      need_where: "សូមជ្រើសរើសកន្លែងក្នុងអគារ។",
      need_text: "សូមសរសេរអ្វីដែលខុសប្រក្រតី ឬផ្ញើសារជាសំឡេង។",
      need_urgent: "សូមឆ្លើយ៖ តើបន្ទាន់ឬទេ?", need_enter: "សូមឆ្លើយ៖ តើបុគ្គលិកអាចចូលពេលលោកអ្នកមិននៅបានទេ?",
      too_many: "ព្យាយាមច្រើនពេក។ សូមរង់ចាំមួយនាទី។",
      sent: "បានផ្ញើហើយ។ យើងនឹងឆ្លើយលោកអ្នកក្នុងការជជែក។"
    }
  };
  var ICONS = { drop: "💧", zap: "⚡", snow: "❄️", lock: "🚪", window: "🪟", sofa: "🛋️",
    wifi: "📶", bug: "🐜", broom: "🧹", volume: "🔊", flame: "🔥", dots: "❓" };
  var DANGER_TYPES = { WATER: true, ELECTRICITY: true };
  var MAX_PHOTOS = 5, MAX_VOICE_SECONDS = 60, PHOTO_SIDE = 1600;

  var params = new URLSearchParams(location.search);
  var lang = params.get("lang") === "en" ? "en" : "km";
  var kind = params.get("form") === "building" ? "BUILDING" : "UNIT";
  var t = T[lang];
  var tg = window.Telegram && window.Telegram.WebApp;
  var app = document.getElementById("app");
  var data = { choices: null, mine: null };
  var f = { type: null, danger: null, place: "", where: null, floor: "", same: null, decided: false,
    text: "", urgent: null, enter: null, best: "ANY", photos: [], voice: null };
  var recorder = null, recordTimer = null, recordStart = 0;
  var error = "";
  var busy = false;

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function name(row) { return lang === "km" ? (row.name_kh || row.name_en) : row.name_en; }
  function typeOf(id) {
    var list = (data.choices && data.choices.types) || [];
    for (var i = 0; i < list.length; i += 1) { if (list[i].id === id) { return list[i]; } }
    return null;
  }
  function safety() {
    var type = typeOf(f.type);
    return !!type && (type.always_urgent || f.danger === true);
  }
  function choice(group, value, label, on) {
    return '<button type="button" class="choice' + (on ? " on" : "") + '" data-group="' + group +
      '" data-value="' + esc(value) + '">' + esc(label) + "</button>";
  }
  function yesNo(group, current) {
    return '<div class="row">' + choice(group, "yes", t.yes, current === true) +
      choice(group, "no", t.no, current === false) + "</div>";
  }

  function render() {
    if (!data.choices) { return; }
    var type = typeOf(f.type);
    var html = "<h1>" + esc(kind === "UNIT" ? t.unit : t.building) + "</h1>";
    if (kind === "BUILDING") {
      html += "<h2>" + esc(t.where_building) + '</h2><div class="row">';
      (data.choices.places || []).forEach(function (place) {
        html += choice("where", place.id, name(place), f.where === place.id);
      });
      html += '</div><p class="hint">' + esc(t.floor) + '</p><input type="text" id="floor" maxlength="20" value="' + esc(f.floor) + '">';
    }
    html += "<h2>" + esc(t.what_type) + '</h2><div class="grid">';
    (data.choices.types || []).forEach(function (row) {
      html += '<button type="button" class="tile' + (f.type === row.id ? " on" : "") +
        '" data-group="type" data-value="' + esc(row.id) + '"><span class="icon">' +
        (ICONS[row.icon] || "❓") + "</span>" + esc(name(row)) + "</button>";
    });
    html += "</div>";
    if (type && DANGER_TYPES[type.code]) {
      html += "<h2>" + esc(t["danger_" + type.code]) + "</h2>" + yesNo("danger", f.danger);
    }
    if (type && safety()) {
      var steps = t["steps_" + (DANGER_TYPES[type.code] ? type.code : "SAFETY")];
      html += '<div class="safety"><strong>⚠ ' + esc(t.safety) + "</strong><ol>" +
        steps.map(function (step) { return "<li>" + esc(step) + "</li>"; }).join("") +
        "</ol><strong>" + esc(t.call) + "</strong><p>" + esc(t.always_urgent) + "</p></div>";
    }
    var open = [];
    if (kind === "BUILDING" && f.where) {
      open = (data.choices.open_building || []).filter(function (row) {
        return row.problem_place_id === f.where;
      });
    }
    if (open.length) {
      html += "<h2>" + esc(t.open_here) + "</h2>";
      open.forEach(function (row) {
        var openType = typeOf(row.problem_type_id);
        html += '<div class="open"><span>' + (openType ? (ICONS[openType.icon] || "") + " " + esc(name(openType)) : "") +
          "<br><small>" + esc(row.report_number) + (row.floor ? " · " + esc(row.floor) : "") + "</small></span>" +
          choice("same", row.report_id, t.same, f.same === row.report_id) + "</div>";
      });
      html += '<div class="row">' + choice("same", "", t.something_else, f.decided && !f.same) + "</div>";
    }
    if (kind === "UNIT") {
      var places = (data.mine && data.mine.places) || [];
      if (places.length) {
        html += "<h2>" + esc(t.where_unit) + '</h2><select id="place"><option value="">' + esc(t.other_place) + "</option>";
        places.forEach(function (row) {
          var value = row.item_id + "|" + row.number;
          html += '<option value="' + esc(value) + '"' + (f.place === value ? " selected" : "") + ">" +
            esc(name(row) + (row.count > 1 ? " " + row.number : "")) + "</option>";
        });
        html += "</select>";
      }
    }
    html += "<h2>" + esc(t.what_wrong) + '</h2><p class="hint">' + esc(f.same ? t.joined_note : t.what_wrong_hint) +
      '</p><textarea id="text" maxlength="1000">' + esc(f.text) + "</textarea>";
    if (f.voice) {
      html += '<p>' + esc(t.voice) + "0:" + String(f.voice.seconds).padStart(2, "0") +
        ' <button type="button" class="small" data-action="voice-remove">' + esc(t.remove) + "</button></p>";
    } else if (recorder) {
      html += '<p><span id="recording">' + esc(t.recording) + '</span> <button type="button" class="small" data-action="voice-stop">' + esc(t.stop) + "</button></p>";
    } else {
      html += '<p><button type="button" class="small" data-action="voice-start">' + esc(t.record) + "</button></p>";
    }
    html += "<h2>" + esc(t.photos) + '</h2><div class="thumbs">';
    f.photos.forEach(function (photo, index) {
      html += '<figure><img alt="" src="' + photo.url + '"><button type="button" data-action="photo-remove" data-value="' + index + '">×</button></figure>';
    });
    html += "</div>";
    if (f.photos.length < MAX_PHOTOS) {
      html += '<p><label class="small" style="display:inline-block;padding:8px 12px;border:1px solid var(--line);border-radius:8px">' +
        esc(t.add_photo) + '<input type="file" id="photo" accept="image/*" multiple hidden></label></p>';
    }
    if (kind === "UNIT") {
      if (!safety()) {
        html += "<h2>" + esc(t.urgent) + "</h2>" + yesNo("urgent", f.urgent) + '<p class="hint">' + esc(t.urgent_hint) + "</p>";
      }
      html += "<h2>" + esc(t.enter) + "</h2>" + yesNo("enter", f.enter) + '<p class="hint">' + esc(t.enter_hint) + "</p>";
      html += "<h2>" + esc(t.best) + '</h2><div class="row">' + ["AM", "PM", "ANY"].map(function (value) {
        return choice("best", value, t[value], f.best === value);
      }).join("") + "</div>";
    }
    if (error) { html += '<p class="error">' + esc(error) + "</p>"; }
    html += '<button type="button" class="main" data-action="send"' + (busy ? " disabled" : "") + ">" + esc(busy ? t.sending : t.send) + "</button>";
    app.innerHTML = html;
  }

  function keepTyping() {
    var text = document.getElementById("text");
    var floor = document.getElementById("floor");
    var place = document.getElementById("place");
    if (text) { f.text = text.value; }
    if (floor) { f.floor = floor.value; }
    if (place) { f.place = place.value; }
  }

  app.addEventListener("click", function (event) {
    var target = event.target.closest("[data-group],[data-action]");
    if (!target) { return; }
    keepTyping();
    var group = target.getAttribute("data-group");
    var value = target.getAttribute("data-value");
    var action = target.getAttribute("data-action");
    if (group === "type") { if (f.type !== value) { f.danger = null; } f.type = value; }
    if (group === "danger") { f.danger = value === "yes"; }
    if (group === "where") { f.where = value; f.same = null; f.decided = false; }
    if (group === "same") { f.same = value || null; f.decided = true; }
    if (group === "urgent") { f.urgent = value === "yes"; }
    if (group === "enter") { f.enter = value === "yes"; }
    if (group === "best") { f.best = value; }
    if (action === "voice-start") { startVoice(); return; }
    if (action === "voice-stop") { stopVoice(); return; }
    if (action === "voice-remove") { f.voice = null; }
    if (action === "photo-remove") { f.photos.splice(Number(value), 1); }
    if (action === "send") { send(); return; }
    error = "";
    render();
  });
  app.addEventListener("change", function (event) {
    if (event.target.id !== "photo") { return; }
    keepTyping();
    var files = Array.prototype.slice.call(event.target.files || [], 0, MAX_PHOTOS - f.photos.length);
    Promise.all(files.map(shrink)).then(function (photos) {
      photos.forEach(function (photo) { if (photo) { f.photos.push(photo); } });
      render();
    });
  });

  // A photo is sent at most 1600 px on its longest side, as JPEG (bots plan limits).
  function shrink(file) {
    return new Promise(function (resolve) {
      var url = URL.createObjectURL(file);
      var image = new Image();
      image.onload = function () {
        var scale = Math.min(1, PHOTO_SIDE / Math.max(image.width, image.height));
        var canvas = document.createElement("canvas");
        canvas.width = Math.round(image.width * scale);
        canvas.height = Math.round(image.height * scale);
        canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(url);
        canvas.toBlob(function (blob) {
          resolve(blob ? { blob: blob, url: URL.createObjectURL(blob), type: "image/jpeg" } : null);
        }, "image/jpeg", 0.85);
      };
      image.onerror = function () { URL.revokeObjectURL(url); resolve(null); };
      image.src = url;
    });
  }

  function voiceType() {
    var kinds = ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/mp4", "audio/webm"];
    if (!window.MediaRecorder) { return null; }
    for (var i = 0; i < kinds.length; i += 1) {
      if (MediaRecorder.isTypeSupported(kinds[i])) { return kinds[i]; }
    }
    return "";
  }
  function startVoice() {
    var type = voiceType();
    if (type === null || !navigator.mediaDevices) { error = t.no_mic; render(); return; }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      var chunks = [];
      recorder = type ? new MediaRecorder(stream, { mimeType: type }) : new MediaRecorder(stream);
      recorder.ondataavailable = function (event) { if (event.data.size) { chunks.push(event.data); } };
      recorder.onstop = function () {
        stream.getTracks().forEach(function (track) { track.stop(); });
        clearInterval(recordTimer);
        var mime = (recorder.mimeType || type || "audio/webm").split(";")[0];
        var seconds = Math.min(MAX_VOICE_SECONDS, Math.max(1, Math.round((Date.now() - recordStart) / 1000)));
        f.voice = { blob: new Blob(chunks, { type: mime }), type: mime, seconds: seconds };
        recorder = null;
        render();
      };
      recordStart = Date.now();
      recorder.start();
      recordTimer = setInterval(function () {
        var seconds = Math.round((Date.now() - recordStart) / 1000);
        var label = document.getElementById("recording");
        if (label) { label.textContent = t.recording + "0:" + String(seconds).padStart(2, "0"); }
        if (seconds >= MAX_VOICE_SECONDS) { stopVoice(); }
      }, 250);
      render();
    }).catch(function () { error = t.no_mic; render(); });
  }
  function stopVoice() { if (recorder && recorder.state !== "inactive") { recorder.stop(); } }

  function base64(blob) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(String(reader.result).split(",")[1] || ""); };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  function problem() {
    var type = typeOf(f.type);
    if (kind === "BUILDING" && !f.where) { return t.need_where; }
    if (!type) { return t.need_type; }
    if (DANGER_TYPES[type.code] && f.danger === null) { return t.need_danger; }
    if (!f.text.trim() && !f.voice && !(kind === "BUILDING" && f.same)) { return t.need_text; }
    if (kind === "UNIT" && !safety() && f.urgent === null) { return t.need_urgent; }
    if (kind === "UNIT" && f.enter === null) { return t.need_enter; }
    return "";
  }

  function send() {
    error = problem();
    if (error || busy) { render(); return; }
    busy = true;
    render();
    var form = { kind: kind, problem_type_id: f.type, description: f.text.trim() || null,
      danger: f.danger === true };
    if (kind === "UNIT") {
      form.urgent = safety() ? true : f.urgent;
      form.may_enter = f.enter;
      form.best_time = f.best;
      if (f.place) {
        var parts = f.place.split("|");
        form.place_item_id = parts[0];
        form.place_number = Number(parts[1]);
      }
    } else {
      form.problem_place_id = f.where;
      form.floor = f.floor.trim() || null;
      if (f.same) { form.same_as = f.same; }
    }
    var files = f.photos.map(function (photo) { return { blob: photo.blob, type: photo.type }; });
    if (f.voice) { files.push({ blob: f.voice.blob, type: f.voice.type, seconds: f.voice.seconds }); }
    Promise.all(files.map(function (file) {
      return base64(file.blob).then(function (encoded) {
        var entry = { content_type: file.type, data: encoded };
        if (file.seconds) { entry.duration = file.seconds; }
        return entry;
      });
    })).then(function (photos) {
      return fetch("/form/tenant", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ init_data: tg ? tg.initData : "", form: form, photos: photos })
      });
    }).then(function (answer) {
      busy = false;
      if (answer.ok) {
        app.innerHTML = '<p class="done">✅ ' + esc(t.sent) + "</p>";
        if (tg) { setTimeout(function () { tg.close(); }, 1500); }
        return;
      }
      error = answer.status === 403 ? t.not_linked : answer.status === 429 ? t.too_many : t.failed;
      render();
    }).catch(function () { busy = false; error = t.failed; render(); });
  }

  if (tg) { tg.ready(); tg.expand(); }
  document.getElementById("loading").textContent = t.loading;
  fetch("/form/tenant/start", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ init_data: tg ? tg.initData : "" })
  }).then(function (answer) {
    if (answer.status === 403) { throw new Error("not_linked"); }
    if (!answer.ok) { throw new Error("failed"); }
    return answer.json();
  }).then(function (body) {
    if (!body.choices) { throw new Error("failed"); }
    data = body;
    render();
  }).catch(function (problem) {
    app.innerHTML = '<p class="error">' + esc(problem.message === "not_linked" ? t.not_linked : t.failed) + "</p>";
  });
})();
</script>
</body>
</html>
`;

export function tenantAppPage(): string {
  return PAGE;
}
