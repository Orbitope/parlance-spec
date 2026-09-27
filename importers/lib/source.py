"""
source.py — reading a source file, with a message instead of a traceback.

Every parser opens exactly one kind of input, and every one of them used to do
it with a bare `open(path, encoding="utf-8-sig").read()`. That is right for the
file it expects and wrong for the file it gets: a Latin-1 export, a Word
document renamed `.ink`, a UTF-16 save from an editor that defaults to it. Each
of those ended in a `UnicodeDecodeError` traceback with no file named in the
last line — and the person running an importer is a writer following a skill,
not someone who reads Python stack traces.

So the parsers read through here. A file that is not UTF-8, or an Arcweave
export that is not a JSON object, stops the parser with one line naming the
file and what was wrong with it. Nothing is guessed: decoding with a fallback
codec would silently change the author's characters, which is exactly the
rewrite these importers exist not to make.
"""
import json
import sys


def read_text(path):
    """The file's text, BOM stripped. Exits with one line on a non-UTF-8 file."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            return f.read()
    except UnicodeDecodeError as e:
        sys.exit(f"{path}: not UTF-8 text ({e.reason} at byte {e.start}). Save the "
                 "file as UTF-8 and re-run; nothing is decoded with a fallback codec, "
                 "because that would change the author's characters.")
    except OSError as e:
        sys.exit(f"{path}: cannot read file: {e.strerror or e}")


def read_json_object(path):
    """A JSON file whose top level is an object. Exits with one line otherwise."""
    text = read_text(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"{path}: not valid JSON ({e.msg} at line {e.lineno}, column {e.colno})")
    if not isinstance(data, dict):
        sys.exit(f"{path}: expected a JSON object at the top level, got "
                 f"{type(data).__name__} — an Arcweave 'Export → JSON' project file "
                 "is one object holding boards, elements, connections and the rest")
    return data
