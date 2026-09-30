"""Convert PortaLite CSV exports to SNIRF.

    portalite2snirf recording.csv [more.csv ...] [-o output_folder]

Started without files (e.g. by double-clicking the program) it opens a file picker instead,
and dropping CSV files onto the program converts them directly. The packaged program has no
console, so it reports results in a window.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .reader import read_portalite_csv
from .snirf import write_snirf


def convert(csv_path: Path, output_dir: Path | None = None) -> Path:
    recording = read_portalite_csv(csv_path)
    target = (output_dir or csv_path.parent) / csv_path.with_suffix(".snirf").name
    return write_snirf(recording, target)


def convert_all(paths: list[Path], output_dir: Path | None) -> tuple[list[str], bool]:
    messages, ok = [], True
    for path in paths:
        try:
            out = convert(path, output_dir)
            messages.append(f"OK    {path.name} -> {out}")
        except Exception as exc:  # report every file, keep going
            ok = False
            messages.append(f"ERROR {path.name}: {exc}")
    return messages, ok


def _gui() -> int:
    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    root.withdraw()
    chosen = filedialog.askopenfilenames(
        title="Choose PortaLite CSV recordings to convert to SNIRF",
        filetypes=[("PortaLite CSV export", "*.csv"), ("All files", "*.*")],
    )
    root.destroy()
    if not chosen:
        return 0
    messages, ok = convert_all([Path(p) for p in chosen], None)
    _show_results(messages, ok)
    return 0 if ok else 1


def _show_results(messages: list[str], ok: bool) -> None:
    import tkinter
    from tkinter import messagebox

    root = tkinter.Tk()
    root.withdraw()
    (messagebox.showinfo if ok else messagebox.showerror)("PortaLite to SNIRF", "\n\n".join(messages))
    root.destroy()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="portalite2snirf", description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path, help="PortaLite .csv exports")
    parser.add_argument("-o", "--output-dir", type=Path, help="folder for the .snirf files (default: next to each CSV)")
    parser.add_argument("--no-window", action="store_true", help="print results instead of showing them in a window")
    args = parser.parse_args(argv)

    if not args.files:
        try:
            return _gui()
        except ImportError:
            parser.print_help()
            return 2

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
    messages, ok = convert_all(args.files, args.output_dir)
    if getattr(sys, "frozen", False) and not args.no_window:
        _show_results(messages, ok)
    else:
        print("\n".join(messages))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
