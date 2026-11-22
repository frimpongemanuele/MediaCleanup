"""Command-line interface: plan, preview, apply, and roll back."""

from __future__ import annotations

import argparse
from pathlib import Path

from filesystem_safety import UnsafePathError, _absolute
from . import tmdb
from .execution import apply_plan, read_plan, rollback, write_plan
from .filesystem import Plan, planning
from .movies import process_movie_folder, split_multi_movie_folder
from .organizer import get_media_subfolders, process_entry_with_library_routing
from .shows import detect_flat_show_folder, detect_show_root, process_flat_show_folder, process_show_folder


def build_plan(root: Path, *, single: bool = False, batch_start: int = 0, batch_size: int = 20) -> Plan:
    if batch_start < 0 or batch_size <= 0:
        raise ValueError("Batch start must be non-negative and batch size positive.")
    # The organizer always executes against the virtual filesystem. A preview and
    # apply therefore use the same paths and collision decisions.
    with planning(root, single=single) as planner:
        root = planner.root
        if single:
            if detect_show_root(root):
                process_show_folder(root)
            elif detect_flat_show_folder(root):
                process_flat_show_folder(root)
            elif not split_multi_movie_folder(root):
                process_movie_folder(root)
        else:
            entries = get_media_subfolders(root)
            end = min(batch_start + batch_size, len(entries))
            if not entries or batch_start >= len(entries):
                print("No media folders in this batch.")
            else:
                print(f"Batch: items {batch_start} to {end - 1} of {len(entries)}")
                for idx, entry in enumerate(entries[batch_start:end], start=batch_start):
                    print(f"\n##### [{idx}] {entry.name} #####")
                    process_entry_with_library_routing(entry, media_root=root)
        return planner.plan()


def show_plan(plan: Plan) -> None:
    print(f"\nOperation plan ({len(plan.operations)} changes):")
    for index, op in enumerate(plan.operations, start=1):
        if op.kind == "mkdir":
            print(f"  {index}. MKDIR  {op.target}")
        else:
            print(f"  {index}. RENAME {op.source} -> {op.target}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan and safely organize movie and TV libraries for Jellyfin."
    )
    parser.add_argument("root", type=Path, help="Media root OR single title folder; original root for rollback")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Build and apply the displayed plan")
    mode.add_argument("--apply-plan", type=Path, metavar="FILE", help="Apply a previously saved preview without fresh metadata lookups")
    mode.add_argument("--rollback", type=Path, metavar="JOURNAL", help="Reverse confirmed operations from a journal")
    parser.add_argument("--plan-out", type=Path, metavar="FILE", help="Save the exact plan for later application")
    parser.add_argument("--journal", type=Path, metavar="FILE", help="Write apply journal here (default: next to the media root)")
    parser.add_argument("--batch-size", type=int, default=20, help="Number of top-level titles per batch")
    parser.add_argument("--batch-start", type=int, default=0, help="Zero-based batch start")
    parser.add_argument("--single", action="store_true", help="Treat root as a single title folder")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    root = _absolute(args.root.expanduser())
    if args.plan_out and (args.apply_plan or args.rollback):
        parser.error("--plan-out is only available when building a plan")
    if args.journal and not (args.apply or args.apply_plan):
        parser.error("--journal requires --apply or --apply-plan")
    if (args.apply_plan or args.rollback) and (args.batch_start != 0 or args.batch_size != 20):
        parser.error("Batch options are only available when building a plan")

    try:
        if args.rollback:
            count = rollback(args.rollback, root, single=args.single)
            print(f"Rollback complete: {count} operations reversed.")
            return

        print(f"Scanning: {root}")
        print("Mode:", "APPLY" if args.apply or args.apply_plan else "DRY RUN")
        if args.apply_plan:
            plan = read_plan(args.apply_plan)
            if plan.root != root or plan.single != args.single:
                raise UnsafePathError("Plan root or single-folder mode does not match the command.")
        else:
            print("TMDb key loaded:", "YES" if tmdb.TMDB_API_KEY else "NO")
            plan = build_plan(root, single=args.single, batch_start=args.batch_start, batch_size=args.batch_size)

        show_plan(plan)
        if args.plan_out:
            print(f"Saved plan: {write_plan(plan, args.plan_out)}")
        if args.apply or args.apply_plan:
            if plan.operations:
                apply_plan(plan, args.journal)
            print("Apply complete.")
        else:
            print("Preview only: no media files changed.")
    except (UnsafePathError, OSError, ValueError) as error:
        raise SystemExit(f"Stopped safely: {error}") from None
