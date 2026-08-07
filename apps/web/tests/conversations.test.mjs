// The conversation surface, with the DOM and the network taken out from under it.
//
// What a reader recognises a conversation by is their own first question and when they
// last touched it. Both are easy to lose in a refactor and neither fails loudly: a list
// that renders "Без назви" for everything still renders, and a timestamp that says
// "щойно" for a week-old conversation still says something.
//
// The escaping test is the one that would be a vulnerability rather than an annoyance. A
// conversation title is a question somebody typed, and it goes into markup.

import test from "node:test";
import assert from "node:assert/strict";

import {conversationListMarkup, relativeTime, titleFrom} from "../public/conversations.js";

const AT = Date.parse("2026-08-07T12:00:00Z");

test("a title is the first question, shortened where it has to be", () => {
  assert.equal(titleFrom("  як   накласти турнікет  "), "як накласти турнікет");
  const long = "я".repeat(200);
  const title = titleFrom(long);
  assert.equal(title.length, 58);
  assert.ok(title.endsWith("…"), "a cut title does not say it was cut");
  assert.equal(titleFrom("   "), null);
  assert.equal(titleFrom(undefined), null);
});

test("how long ago, in words a reader can act on", () => {
  assert.equal(relativeTime("2026-08-07T11:59:40Z", AT), "щойно");
  assert.equal(relativeTime("2026-08-07T11:20:00Z", AT), "40 хв тому");
  assert.equal(relativeTime("2026-08-07T06:00:00Z", AT), "6 год тому");
  assert.equal(relativeTime("2026-08-06T09:00:00Z", AT), "учора");
  assert.equal(relativeTime("2026-08-01T09:00:00Z", AT), "6 дн тому");
});

test("an unparseable timestamp renders as nothing, not as now", () => {
  // "щойно" against a broken timestamp is a false statement about a conversation nobody
  // has touched in a month.
  assert.equal(relativeTime("not a date", AT), "");
  assert.equal(relativeTime(undefined, AT), "");
});

test("a clock ahead of the stored time does not produce a negative age", () => {
  assert.equal(relativeTime("2026-08-07T12:05:00Z", AT), "щойно");
});

test("an empty list says so rather than rendering nothing", () => {
  const markup = conversationListMarkup([]);
  assert.match(markup, /Розмов ще немає/);
  assert.doesNotMatch(markup, /<ul/);
});

test("each row carries its title, its age and both actions", () => {
  const markup = conversationListMarkup(
    [{id: "c1", title: "накладання турнікету", updated_at: "2026-08-07T11:30:00Z"}],
    {now: AT},
  );
  assert.match(markup, /data-conversation="c1"/);
  assert.match(markup, /накладання турнікету/);
  assert.match(markup, /30 хв тому/);
  assert.match(markup, /data-archive="c1"/);
  // The archive control is reachable by a screen reader without the surrounding row.
  assert.match(markup, /aria-label="Архівувати: накладання турнікету"/);
});

test("the open conversation is marked for assistive technology, not only in colour", () => {
  const items = [
    {id: "c1", title: "перша", updated_at: "2026-08-07T11:00:00Z"},
    {id: "c2", title: "друга", updated_at: "2026-08-07T11:30:00Z"},
  ];
  const markup = conversationListMarkup(items, {activeId: "c2", now: AT});
  assert.match(markup, /data-conversation="c2"[^>]*aria-current="true"/);
  assert.doesNotMatch(markup, /data-conversation="c1"[^>]*aria-current/);
  assert.equal((markup.match(/class="current"/g) ?? []).length, 1);
});

test("a conversation with no title reads as untitled rather than as empty", () => {
  const markup = conversationListMarkup(
    [{id: "c1", title: null, updated_at: "2026-08-07T11:30:00Z"}],
    {now: AT},
  );
  assert.match(markup, /Без назви/);
  assert.match(markup, /aria-label="Архівувати: без назви"/);
});

test("a title is escaped everywhere it appears", () => {
  // The title is a question somebody typed. It reaches markup twice — the row and the
  // archive button's label — and an escape applied to one of them is not an escape.
  const hostile = '<img src=x onerror="alert(1)">';
  const markup = conversationListMarkup(
    [{id: "c1", title: hostile, updated_at: "2026-08-07T11:30:00Z"}],
    {now: AT},
  );
  assert.doesNotMatch(markup, /<img/);
  assert.equal((markup.match(/&lt;img/g) ?? []).length, 2);
});

test("an identifier is escaped before it becomes an attribute", () => {
  const markup = conversationListMarkup(
    [{id: 'c1" onclick="alert(1)', title: "t", updated_at: "2026-08-07T11:30:00Z"}],
    {now: AT},
  );
  assert.doesNotMatch(markup, /onclick="alert/);
});

test("the list module names no account", async () => {
  // Ownership is the server's decision. A client that could name an account is a client
  // choosing whose history to read.
  const {readFile} = await import("node:fs/promises");
  const source = await readFile(
    new URL("../public/conversations.js", import.meta.url), "utf8",
  );
  assert.doesNotMatch(source, /account_id/);
  assert.doesNotMatch(source, /\bfetch\s*\(/);
});
