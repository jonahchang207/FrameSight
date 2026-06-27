"""
FrameSight dev automation.

  python dev.py            — interactive menu
  python dev.py commit     — quick commit & push
  python dev.py issue      — create GitHub issue
  python dev.py feature    — new feature (issue + branch)
  python dev.py release    — bump version, merge stable, tag, publish
  python dev.py status     — git status + open issues
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Enable ANSI colours in Windows terminals
if os.name == "nt":
    os.system("")

G  = "\033[92m"   # green
B  = "\033[94m"   # blue
Y  = "\033[93m"   # yellow
R  = "\033[91m"   # red
D  = "\033[2m"    # dim
BD = "\033[1m"    # bold
X  = "\033[0m"    # reset

ROOT = Path(__file__).parent


# ── helpers ────────────────────────────────────────────────────────────────────

def _run(cmd: str, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, text=True,
                          capture_output=capture)

def _live(cmd: str) -> int:
    return subprocess.run(cmd, shell=True).returncode

def _git(cmd: str) -> str:
    return _run(f"git {cmd}").stdout.strip()

def _gh(cmd: str) -> subprocess.CompletedProcess:
    return _run(f"gh {cmd}")

def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  {prompt}{suffix}: ").strip()
    return val or default

def _confirm(prompt: str) -> bool:
    return _ask(prompt + " [y/N]").lower() == "y"

def _multiline(prompt: str) -> str:
    """Collect lines until blank line. Returns newline-joined string."""
    print(f"  {prompt} (blank line to finish):")
    lines = []
    while True:
        line = input("  | ")
        if not line:
            break
        lines.append(line)
    return "\n".join(lines)

def _sep():
    print(f"  {D}{'─' * 48}{X}")

def _header():
    branch  = _git("branch --show-current") or "detached"
    tag     = _latest_tag() or "—"
    changes = _run("git status --porcelain").stdout.strip().splitlines()
    dirty   = f"{Y}● {len(changes)} unsaved{X}" if changes else f"{G}✓ clean{X}"
    print()
    print(f"  {G}{BD}⬡ FRAMESIGHT DEV{X}   "
          f"{D}branch:{X} {B}{branch}{X}  "
          f"{D}tag:{X} {Y}{tag}{X}  {dirty}")
    _sep()


# ── version helpers ────────────────────────────────────────────────────────────

def _latest_tag() -> str:
    tags = [t for t in _git("tag --sort=-version:refname").splitlines()
            if re.match(r"v\d+\.\d+\.\d+", t)]
    return tags[0] if tags else ""

def _bump(ver: str, part: str) -> str:
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", ver or "0.0.0")
    if not m:
        return "v1.0.0"
    ma, mi, pa = int(m[1]), int(m[2]), int(m[3])
    if part == "major": return f"v{ma+1}.0.0"
    if part == "minor": return f"v{ma}.{mi+1}.0"
    return f"v{ma}.{mi}.{pa+1}"


# ── commands ───────────────────────────────────────────────────────────────────

def do_commit():
    _header()
    print(f"  {B}Commit & Push{X}\n")

    status = _run("git status --short").stdout.strip()
    if not status:
        print(f"  {Y}Nothing to commit.{X}")
        return

    lines = status.splitlines()
    for i, l in enumerate(lines, 1):
        flag, path = l[:2], l[3:]
        col = G if "A" in flag else (R if "D" in flag else Y)
        print(f"  {D}{i:>2}.{X} {col}{flag}{X} {path}")
    print()

    choice = _ask("Stage: [A]ll / file numbers (e.g. 1,3) / path", "A")
    if choice.upper() == "A":
        _live("git add -A")
    elif re.match(r"[\d,\s]+$", choice):
        idxs = [int(x.strip()) - 1 for x in choice.split(",") if x.strip().isdigit()]
        paths = " ".join(f'"{lines[i][3:]}"' for i in idxs if 0 <= i < len(lines))
        if paths:
            _live(f"git add {paths}")
    else:
        _live(f"git add {choice}")

    staged = _run("git diff --cached --name-only").stdout.strip()
    if not staged:
        print(f"  {R}Nothing staged — aborted.{X}")
        return

    msg = _ask("Commit message")
    if not msg:
        print(f"  {R}Aborted — no message.{X}")
        return

    rc = _live(f'git commit -m "{msg}"')
    if rc != 0:
        print(f"  {R}Commit failed.{X}")
        return
    print(f"  {G}✓ Committed{X}")

    branch = _git("branch --show-current")
    if _confirm(f"Push to origin/{branch}?"):
        rc2 = _live(f"git push origin {branch}")
        if rc2 == 0:
            print(f"  {G}✓ Pushed → origin/{branch}{X}")
        else:
            print(f"  {R}Push failed.{X}")


def do_issue():
    _header()
    print(f"  {B}Create GitHub Issue{X}\n")

    title = _ask("Title")
    if not title:
        print(f"  {R}Aborted.{X}")
        return

    print(f"  Label:")
    print(f"    {G}[1]{X} bug")
    print(f"    {G}[2]{X} enhancement")
    print(f"    {G}[3]{X} question")
    print(f"    {G}[4]{X} none")
    lc = _ask("→", "4")
    label = {"1": "bug", "2": "enhancement", "3": "question"}.get(lc, "")

    body = _multiline("Body")

    cmd = f'gh issue create --title "{title}"'
    if label:
        cmd += f' --label "{label}"'
    if body:
        # Write body to a temp file to avoid shell quoting issues
        tmp = Path(tempfile.mktemp(suffix=".md"))
        tmp.write_text(body, encoding="utf-8")
        cmd += f' --body-file "{tmp}"'

    result = _gh(cmd.replace("gh ", ""))
    if result.returncode == 0:
        print(f"\n  {G}✓ Issue created:{X} {result.stdout.strip()}")
    else:
        print(f"\n  {R}Error: {result.stderr.strip()}{X}")

    if "tmp" in dir() and tmp.exists():
        tmp.unlink(missing_ok=True)


def do_feature():
    _header()
    print(f"  {B}New Feature{X}\n")

    title  = _ask("Issue title")
    desc   = _multiline("Description")
    branch = _ask("Branch name (will be prefixed feat/)")

    if not title:
        print(f"  {R}Aborted.{X}")
        return

    # Create issue
    cmd = 'gh issue create --label "enhancement"'
    cmd += f' --title "{title}"'
    if desc:
        tmp = Path(tempfile.mktemp(suffix=".md"))
        tmp.write_text(desc, encoding="utf-8")
        cmd += f' --body-file "{tmp}"'

    result = _run(f"gh {cmd}")
    if result.returncode == 0:
        url = result.stdout.strip()
        print(f"  {G}✓ Issue:{X} {url}")
    else:
        print(f"  {R}Issue creation failed: {result.stderr.strip()}{X}")

    if branch and _confirm(f"Create + push branch feat/{branch}?"):
        current = _git("branch --show-current")
        _live(f"git checkout -b feat/{branch}")
        rc = _live(f"git push -u origin feat/{branch}")
        if rc == 0:
            print(f"  {G}✓ Branch feat/{branch} ready{X}")
        else:
            # Branch might already exist remotely; try to switch back
            _live(f"git checkout {current}")

    if "tmp" in dir() and Path(tmp).exists():
        tmp.unlink(missing_ok=True)


def do_release():
    _header()
    print(f"  {B}Release Wizard{X}\n")

    current = _latest_tag() or "v0.0.0"
    print(f"  Current tag: {Y}{current}{X}")
    print(f"    {G}[1]{X} patch → {_bump(current, 'patch')}")
    print(f"    {G}[2]{X} minor → {_bump(current, 'minor')}")
    print(f"    {G}[3]{X} major → {_bump(current, 'major')}")
    print(f"    {G}[4]{X} custom")

    choice = _ask("→", "1")
    if   choice == "1": new_ver = _bump(current, "patch")
    elif choice == "2": new_ver = _bump(current, "minor")
    elif choice == "3": new_ver = _bump(current, "major")
    elif choice == "4": new_ver = _ask("Version (vX.Y.Z)")
    else:
        print(f"  {R}Aborted.{X}")
        return

    if not re.match(r"v\d+\.\d+\.\d+", new_ver):
        print(f"  {R}Invalid version format.{X}")
        return

    notes = _multiline(f"Release notes for {new_ver}")

    # Close resolved issues?
    open_issues = _run("gh issue list --state open --json number,title --limit 20").stdout
    close_nums: list[str] = []
    try:
        import json
        issues = json.loads(open_issues)
        if issues:
            print(f"\n  {B}Open issues:{X}")
            for iss in issues:
                print(f"    #{iss['number']}  {iss['title']}")
            raw = _ask("Close issue numbers with this release (comma-sep, blank=none)", "")
            close_nums = [x.strip() for x in raw.split(",") if x.strip().isdigit()]
    except Exception:
        pass

    _sep()
    print(f"  {Y}About to:{X}")
    print(f"    1. Merge main → stable")
    print(f"    2. Tag {G}{new_ver}{X} on stable")
    print(f"    3. Push stable + tag")
    print(f"    4. Create GitHub Release {G}{new_ver}{X}")
    if close_nums:
        print(f"    5. Close issues: {', '.join('#'+n for n in close_nums)}")
    print()

    if not _confirm(f"Proceed with {new_ver}?"):
        print(f"  {R}Aborted.{X}")
        return

    origin = _git("branch --show-current")

    # Merge main → stable
    print(f"\n  {D}Checking out stable…{X}")
    if _live("git checkout stable") != 0:
        print(f"  {R}Could not switch to stable.{X}")
        return

    print(f"  {D}Merging main…{X}")
    if _live(f'git merge --no-ff main -m "Merge main into stable for {new_ver}"') != 0:
        print(f"  {R}Merge failed — resolve conflicts then run release again.{X}")
        _live(f"git checkout {origin}")
        return

    _live("git push origin stable")
    print(f"  {G}✓ stable updated{X}")

    # Tag
    _live(f"git tag {new_ver}")
    _live(f"git push origin {new_ver}")
    print(f"  {G}✓ Tag {new_ver} pushed{X}")

    # GitHub Release
    body_flag = ""
    if notes:
        tmp = Path(tempfile.mktemp(suffix=".md"))
        tmp.write_text(notes, encoding="utf-8")
        body_flag = f'--notes-file "{tmp}"'
    else:
        body_flag = f'--notes "FrameSight {new_ver}"'

    result = _run(
        f'gh release create {new_ver} --target stable '
        f'--title "FrameSight {new_ver}" {body_flag}'
    )
    if result.returncode == 0:
        print(f"  {G}✓ Release:{X} {result.stdout.strip()}")
    else:
        print(f"  {R}Release failed: {result.stderr.strip()}{X}")

    # Close issues
    for num in close_nums:
        r = _run(f"gh issue close {num} --comment \"Resolved in {new_ver}\"")
        if r.returncode == 0:
            print(f"  {G}✓ Closed #{num}{X}")
        else:
            print(f"  {Y}Could not close #{num}{X}")

    # Return to original branch
    _live(f"git checkout {origin}")
    print(f"  {G}✓ Back on {origin}{X}")

    if "tmp" in dir() and Path(tmp).exists():
        tmp.unlink(missing_ok=True)


def do_status():
    _header()
    print(f"  {B}Changed files:{X}")
    rc = _live("git status --short")
    if rc != 0 or not _run("git status --porcelain").stdout.strip():
        print(f"  {D}(clean){X}")

    print(f"\n  {B}Recent commits:{X}")
    _live("git log --oneline --graph --decorate -10")

    print(f"\n  {B}Open issues:{X}")
    rc2 = _live("gh issue list --state open --limit 15")
    if rc2 != 0:
        print(f"  {D}(gh not available or no issues){X}")

    print(f"\n  {B}Branches:{X}")
    _live("git branch -a --sort=-committerdate | head -10")


# ── menu ───────────────────────────────────────────────────────────────────────

def menu():
    while True:
        _header()
        print(f"  {G}[1]{X}  Commit & push")
        print(f"  {G}[2]{X}  Create issue")
        print(f"  {G}[3]{X}  New feature  (issue + branch)")
        print(f"  {G}[4]{X}  Release      (merge stable · tag · publish)")
        print(f"  {G}[5]{X}  Status       (git + open issues)")
        print(f"  {D}[q]{X}  Quit")
        print()

        choice = input("  → ").strip().lower()
        print()

        if   choice in ("1", "commit"):  do_commit()
        elif choice in ("2", "issue"):   do_issue()
        elif choice in ("3", "feature"): do_feature()
        elif choice in ("4", "release"): do_release()
        elif choice in ("5", "status"):  do_status()
        elif choice in ("q", "quit", "exit"): break
        else:
            print(f"  {Y}Unknown option '{choice}'{X}")

        print()
        input(f"  {D}Press Enter to continue…{X}")


# ── entry point ────────────────────────────────────────────────────────────────

_COMMANDS = {
    "commit":  do_commit,
    "issue":   do_issue,
    "feature": do_feature,
    "release": do_release,
    "status":  do_status,
}

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        try:
            menu()
        except KeyboardInterrupt:
            print(f"\n  {D}Bye.{X}\n")
    elif args[0] in _COMMANDS:
        try:
            _COMMANDS[args[0]]()
        except KeyboardInterrupt:
            print(f"\n  {D}Cancelled.{X}\n")
    else:
        print(f"  Usage: python dev.py [{'|'.join(_COMMANDS)}]")
        sys.exit(1)
