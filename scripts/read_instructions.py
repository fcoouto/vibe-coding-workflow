#!/usr/bin/env python3
"""Prepare exact instruction sections at authoring time; read bounded pages locally."""

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
MAP = Path("clients/instruction-map.json")
SOURCE_BYTES = 8000
OUTPUT_BYTES = 9500
BOOTSTRAP = ["clients/codex.md", "policies/00-index.md"]


def instruction_name(name):
    path = Path(name)
    return (not path.is_absolute() and ".." not in path.parts and path.as_posix() == name
            and path.suffix == ".md" and len(path.parts) >= 2
            and (path.parts[0] == "skills" or (len(path.parts) == 2 and path.parts[0] in {"clients", "policies"})))


def source_path(root, name):
    path = (root / name).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Instruction source must stay inside the package")
    if name != str(MAP) and not instruction_name(path.relative_to(root.resolve()).as_posix()):
        raise ValueError("Resolved source must be a packaged instruction file")
    return path


def build_manifest(root):
    files = {}
    paths = sorted([*(root / "clients").glob("*.md"), *(root / "policies").glob("*.md"),
                    *(root / "skills").rglob("*.md")])
    for path in paths:
        name = path.relative_to(root).as_posix()
        raw = source_path(root, name).read_bytes()
        lines = raw.decode("utf-8").splitlines(keepends=True)
        ranges, start, size = [], 1, 0
        for number, line in enumerate(lines, 1):
            length = len(line.encode("utf-8"))
            if length > SOURCE_BYTES:
                raise ValueError(f"Split the oversized instruction line in {name}")
            if size + length > SOURCE_BYTES:
                ranges.append([start, number - 1])
                start, size = number, 0
            size += length
        if lines:
            ranges.append([start, len(lines)])
        files[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "ranges": ranges}
    return {"version": 1, "files": files}


def load_page(root, paths, page=1, revision=None):
    manifest = json.loads(source_path(root, str(MAP)).read_bytes())
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or not isinstance(manifest.get("files"), dict):
        raise ValueError("Invalid prepared instruction map")
    if not paths or type(page) is not int or page < 1 or (page > 1 and not revision):
        raise ValueError("Select sources and bind continuation pages to their revision")
    selected = list(dict.fromkeys(paths))
    identity, sections = [], []
    for name in selected:
        if name not in manifest["files"] or not instruction_name(name):
            raise ValueError("Select a packaged instruction path from the policy/client references")
        entry = manifest["files"][name]
        raw = source_path(root, name).read_bytes()
        if not isinstance(entry, dict) or hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
            raise ValueError(f"Prepared source changed: {name}; use bounded native reads or update the package")
        lines = raw.decode("utf-8").splitlines(keepends=True)
        ranges = entry.get("ranges")
        if not isinstance(ranges, list):
            raise ValueError("Invalid prepared source ranges")
        expected = 1
        for span in ranges:
            if (not isinstance(span, list) or len(span) != 2 or any(type(n) is not int for n in span)
                    or span[0] != expected or not span[0] <= span[1] <= len(lines)):
                raise ValueError("Prepared ranges must cover each source exactly once")
            start, end = span
            text = "".join(lines[start - 1:end])
            if len(text.encode("utf-8")) > SOURCE_BYTES:
                raise ValueError("Prepared instruction section exceeds the delivery budget")
            sections.append(dict(path=name, start_line=start, end_line=end, text=text,
                                 complete=end == len(lines)))
            expected = end + 1
        if expected != len(lines) + 1:
            raise ValueError("Prepared ranges omit instruction text")
        identity.append([name, entry])
    current = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    if revision is not None and revision != current:
        raise ValueError("Instruction selection changed; restart with the current source revision")
    pages, group, size = [], [], 0
    for section in sections:
        length = len(section["text"].encode("utf-8"))
        if group and size + length > SOURCE_BYTES:
            pages.append(group)
            group, size = [], 0
        group.append(section)
        size += length
    if group or not pages:
        pages.append(group)
    if page > len(pages):
        raise ValueError("Instruction page is outside the selected source range")
    return dict(revision=current, page=page, pages=len(pages), sections=pages[page - 1])


def render_page(result):
    output = [f"Vibe instructions: page {result['page']}/{result['pages']}; revision {result['revision']}\n"]
    for section in result["sections"]:
        output.append(f"\n--- {section['path']} lines {section['start_line']}-{section['end_line']} ---\n")
        output.append(section["text"])
        output.append("\n--- source complete ---\n" if section["complete"] else "\n--- source continues ---\n")
    if result["page"] < result["pages"]:
        output.append(f"\nContinue the same selection with --page {result['page'] + 1} --revision {result['revision']}.\n")
    else:
        output.append("\nSelection complete.\n")
    text = "".join(output)
    if len(text.encode("utf-8")) > OUTPUT_BYTES:
        raise ValueError("Selection metadata exceeds the output budget; select fewer sources")
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--revision")
    parser.add_argument("--prepare", action="store_true", help="authoring only: rebuild the package map")
    args = parser.parse_args()
    try:
        if args.prepare:
            if args.paths or args.page != 1 or args.revision:
                raise ValueError("Preparation cannot be combined with a read")
            (ROOT / MAP).write_text(json.dumps(build_manifest(ROOT), indent=2) + "\n", encoding="utf-8")
            return 0
        paths = BOOTSTRAP if args.paths == ["bootstrap"] else args.paths
        print(render_page(load_page(ROOT, paths, args.page, args.revision)), end="")
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Prepared instruction read unavailable: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
