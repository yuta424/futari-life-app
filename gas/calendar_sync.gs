/**
 * ふたり暮らしアプリの予定を Google カレンダーに書き込む（アプリ → カレンダーの一方向）。
 *
 * 使い方:
 *  1. https://script.google.com で新しいプロジェクトを作り、このファイルの中身を貼り付ける
 *  2. 下の FEED_URL を、アプリの「設定 → Googleカレンダーに予定を表示する」の URL の
 *     末尾 .ics を .json に変えたものに書き換える
 *  3. 「プロジェクトの設定」でタイムゾーンを「(GMT+09:00) 日本標準時」にする
 *  4. syncCalendar を一度実行して、カレンダーへのアクセスを許可する
 *  5. 「トリガー」で syncCalendar を「時間主導型 → 分ベース → 15分おき」に設定する
 *
 * 専用のカレンダー（CALENDAR_NAME）を自動で作り、その中だけを書き換えます。
 * このカレンダーに手で入れた予定は次の同期で消えるので、予定の追加・変更はアプリで行ってください。
 */
const FEED_URL = 'https://あなたのアプリ.vercel.app/cal/ここにトークン.json';
const CALENDAR_NAME = 'ふたり暮らし';
const SKIP_KINDS = []; // 例: ゴミの日を入れたくなければ ['garbage']

function syncCalendar() {
  const res = UrlFetchApp.fetch(FEED_URL, { muteHttpExceptions: true });
  if (res.getResponseCode() !== 200) {
    throw new Error('アプリから予定を取得できませんでした（' + res.getResponseCode() + '）。FEED_URL を確認してください。');
  }
  const text = res.getContentText();

  // 前回と内容が同じなら何もしない（カレンダーの書き込み回数を節約する）
  const props = PropertiesService.getScriptProperties();
  const digest = Utilities.base64Encode(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text, Utilities.Charset.UTF_8));
  if (props.getProperty('lastDigest') === digest) return;

  const feed = JSON.parse(text);
  const calendar = CalendarApp.getCalendarsByName(CALENDAR_NAME)[0] || CalendarApp.createCalendar(CALENDAR_NAME);
  const rangeStart = new Date(feed.from_date + 'T00:00:00+09:00');
  const rangeEnd = new Date(rangeStart.getTime() + feed.days * 24 * 60 * 60 * 1000);

  calendar.getEvents(rangeStart, rangeEnd).forEach(function (event) { event.deleteEvent(); });

  feed.events.forEach(function (ev) {
    if (SKIP_KINDS.indexOf(ev.kind) !== -1) return;
    const options = { description: (ev.memo ? ev.memo + '\n\n' : '') + 'ふたり暮らしアプリの予定です。変更はアプリで行ってください。' };
    if (ev.start) {
      const start = new Date(ev.date + 'T' + ev.start + ':00+09:00');
      const end = ev.end && ev.end > ev.start
        ? new Date(ev.date + 'T' + ev.end + ':00+09:00')
        : new Date(start.getTime() + 60 * 60 * 1000);
      calendar.createEvent(ev.title, start, end, options);
    } else {
      calendar.createAllDayEvent(ev.title, new Date(ev.date + 'T00:00:00+09:00'), options);
    }
  });

  props.setProperty('lastDigest', digest);
}
