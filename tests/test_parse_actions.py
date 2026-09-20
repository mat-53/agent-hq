"""Item: parsing the Director's JSON action block (valid, malformed, missing)."""
import json

import pytest

import server

parse = server.parse_actions


def block(obj_or_text):
    body = obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text)
    return f"```json\n{body}\n```"


def test_valid_block_returns_actions_and_cleaned_text():
    acts = {"actions": [{"type": "assign", "agent": "Alice", "task": "do it"}]}
    text, actions, bad = parse("I'll ask Alice.\n" + block(acts))
    assert text == "I'll ask Alice."
    assert actions == acts["actions"]
    assert bad is False


def test_text_before_and_after_block_is_kept():
    text, actions, bad = parse("before\n" + block({"actions": []}) + "\nafter")
    assert "before" in text and "after" in text and "```" not in text
    assert actions == [] and bad is False


def test_no_block_means_plain_reply():
    text, actions, bad = parse("  Nothing to do right now.  ")
    assert (text, actions, bad) == ("Nothing to do right now.", [], False)


def test_empty_reply():
    assert parse("") == ("", [], False)


def test_empty_actions_list_is_valid_not_bad():
    _, actions, bad = parse(block({"actions": []}))
    assert actions == [] and bad is False


@pytest.mark.parametrize("broken", [
    '{"actions":[{"type":"assign","agent":"A","task":"x"},]}',   # trailing comma
    "{'actions': []}",                                          # single quotes
    '{"actions":[{"type":"assign"',                             # truncated
    '{"actions": [} }',
])
def test_malformed_json_is_flagged_bad_and_block_removed(broken):
    text, actions, bad = parse("Here you go\n" + block(broken))
    assert actions == []
    assert bad is True
    assert text == "Here you go"      # the broken block is not shown to the owner


@pytest.mark.parametrize("payload", [
    {"actions": "assign"}, {"actions": {"type": "assign"}}, {"actions": None}, {"foo": 1}, {"actions": 5},
])
def test_actions_key_wrong_type_or_missing_is_bad(payload):
    _, actions, bad = parse(block(payload))
    assert actions == [] and bad is True


def test_last_block_wins_when_several():
    first = block({"actions": [{"type": "assign", "agent": "A", "task": "first"}]})
    second = block({"actions": [{"type": "assign", "agent": "B", "task": "second"}]})
    text, actions, bad = parse(f"one\n{first}\ntwo\n{second}")
    assert [a["agent"] for a in actions] == ["B"]
    assert bad is False
    assert "first" in text        # the earlier block stays in the visible text (only the last one is stripped)


def test_braces_and_quotes_inside_strings_do_not_break_parsing():
    acts = {"actions": [{"type": "assign", "agent": "A", "task": 'use {x} and "quotes" and }'}]}
    _, actions, bad = parse(block(acts))
    assert actions == acts["actions"] and bad is False


def test_unicode_and_multiline_json():
    acts = {"actions": [{"type": "assign", "agent": "Ünï", "task": "Schreibe Übung\nzweite Zeile"}]}
    pretty = json.dumps(acts, indent=2, ensure_ascii=False)
    _, actions, bad = parse(block(pretty))
    assert actions == acts["actions"] and bad is False


def test_crlf_line_endings():
    txt = "hi\r\n```json\r\n" + json.dumps({"actions": []}) + "\r\n```\r\n"
    text, actions, bad = parse(txt)
    assert actions == [] and bad is False and text == "hi"


def test_fence_without_json_language_is_ignored():
    txt = "```\n" + json.dumps({"actions": [{"type": "assign", "agent": "A", "task": "t"}]}) + "\n```"
    text, actions, bad = parse(txt)
    assert actions == [] and bad is False


def test_non_dict_entries_are_returned_as_is_and_skipped_by_run_action(hq):
    _, actions, _ = parse(block({"actions": ["assign", 5, None, {"type": "assign"}]}))
    assert len(actions) == 4
    for a in actions[:3]:
        assert hq.act(a) == "Skipped an unknown action."


@pytest.mark.parametrize("text,expected_start", [
    ("did it\nSUMMARY:\nline one\nline two", "line one"),
    ("SUMMARY: first\nmore\nsummary: second", "second"),     # last occurrence, case-insensitive
])
def test_extract_summary_uses_last_summary_marker(text, expected_start):
    assert server.extract_summary(text).startswith(expected_start)


def test_extract_summary_limits():
    # inputs must exceed the limits (6000 with marker / 3000 without) to actually exercise truncation
    assert len(server.extract_summary("SUMMARY:\n" + "x" * 8000)) == 6000
    assert len(server.extract_summary("y" * 8000)) == 3000         # no marker -> first 3000 chars
    # below the limits nothing is cut
    assert len(server.extract_summary("SUMMARY:\n" + "x" * 5000)) == 5000
    assert len(server.extract_summary("y" * 2500)) == 2500
