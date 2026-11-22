"""Test the exact-plan and journal workflow using disposable synthetic media."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from filesystem_safety import UnsafePathError
from media_cleanup import cli, tmdb
from media_cleanup.execution import apply_plan, read_plan, rollback, write_plan
from media_cleanup.filesystem import Operation, Plan, Planner, identity


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name).resolve()
        self.root = self.parent / "library"
        self.root.mkdir()
        self.journal = self.parent / "media-cleanup-journal-test.jsonl"
        self.plan_file = self.parent / "media-cleanup-plan-test.json"
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        self.key_patch = patch.object(tmdb, "TMDB_API_KEY", "")
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)

    def snapshot(self, root: Path) -> dict[str, bytes | None]:
        return {
            str(path.relative_to(root)): None if path.is_dir() else path.read_bytes()
            for path in root.rglob("*")
        }

    def test_saved_preview_is_exact_and_rollback_restores_library(self):
        movie = self.root / "Example Movie (2020)"
        movie.mkdir()
        (movie / "Example.Movie.2020.mkv").write_bytes(b"movie")
        (movie / "Example.Movie.2020.eng.srt").write_bytes(b"subtitle")
        show = self.root / "Example Show"
        show.mkdir()
        (show / "Example.Show.S01E01.mkv").write_bytes(b"episode1")
        (show / "Example.Show.S01E02.mkv").write_bytes(b"episode2")
        before = self.snapshot(self.root)

        cli.main([str(self.root), "--plan-out", str(self.plan_file)])
        self.assertEqual(before, self.snapshot(self.root))
        plan = read_plan(self.plan_file)
        self.assertGreater(len(plan.operations), 2)

        with patch.object(cli, "build_plan", side_effect=AssertionError("Must not replan")):
            cli.main([str(self.root), "--apply-plan", str(self.plan_file), "--journal", str(self.journal)])
        self.assertTrue((self.root / "0_Movies").is_dir())
        self.assertTrue((self.root / "0_Shows").is_dir())
        self.assertEqual({p.read_bytes() for p in self.root.rglob("*.mkv")}, {b"movie", b"episode1", b"episode2"})

        cli.main([str(self.root), "--rollback", str(self.journal)])
        self.assertEqual(before, self.snapshot(self.root))
        self.assertEqual(rollback(self.journal, self.root), 0)

    def test_single_folder_root_rename_can_be_reversed(self):
        original = self.root / "example_movie_2020"
        original.mkdir()
        (original / "Example.Movie.2020.mkv").write_bytes(b"movie")
        before = self.snapshot(self.root)
        plan = cli.build_plan(original, single=True)
        self.assertTrue(any(op.source == original for op in plan.operations))
        apply_plan(plan, self.journal)
        self.assertFalse(original.exists())
        rollback(self.journal, original, single=True)
        self.assertEqual(before, self.snapshot(self.root))

    def test_multi_movie_metadata_and_language_matching(self):
        folder = self.root / "Mixed Films"
        folder.mkdir()
        (folder / "Example.Movie.2020.ITA.mkv").write_bytes(b"italian")
        (folder / "Example.Movie.2020.ENG.mkv").write_bytes(b"english")
        (folder / "Unknown.Movie.2021.mkv").write_bytes(b"unknown")
        before = self.snapshot(self.root)

        def fake_match(candidates, fallback_year=None):
            if fallback_year == "2020":
                return ("Example Movie", "2020", 123, 0.95)
            return (None, None, None, 0.0)

        with patch.object(tmdb, "TMDB_API_KEY", "synthetic-test-credential"), patch.object(
            tmdb, "resolve_tmdb_match", side_effect=fake_match
        ), patch.object(tmdb, "get_tmdb_localized_titles", return_value={
            "en": "Example Movie", "it": "Film Esempio", "original": "Example Movie",
        }):
            plan = cli.build_plan(self.root)
        self.assertEqual(before, self.snapshot(self.root))
        apply_plan(plan, self.journal)
        videos = {p.read_bytes(): p for p in self.root.rglob("*.mkv")}
        self.assertIn("Italian", videos[b"italian"].name)
        self.assertIn("English", videos[b"english"].name)
        self.assertEqual(videos[b"unknown"].parent.name, "_Needs_Review")
        rollback(self.journal, self.root)
        self.assertEqual(before, self.snapshot(self.root))

    def test_virtual_scan_skips_linklike_entries(self):
        from media_cleanup import filesystem

        linked = self.root / "linked"
        linked.mkdir()
        (linked / "ignored.mkv").write_bytes(b"ignored")
        real = filesystem._linklike
        with patch.object(filesystem, "_linklike", side_effect=lambda path: path == linked or real(path)):
            planner = Planner(self.root)
        self.assertTrue(planner.occupied(linked))
        self.assertEqual(planner.children(self.root), [])
        self.assertNotIn(linked / "ignored.mkv", planner.entries)
        with self.assertRaises(UnsafePathError):
            planner.mkdir(linked / "outside")

    def test_root_rename_before_episode_moves_rolls_back(self):
        original = self.root / "example_show"
        original.mkdir()
        (original / "Example.Show.S01E01.mkv").write_bytes(b"one")
        (original / "Example.Show.S01E02.mkv").write_bytes(b"two")
        before = self.snapshot(self.root)
        plan = cli.build_plan(original, single=True)
        self.assertEqual(plan.operations[0].source, original)
        apply_plan(plan, self.journal)
        self.assertFalse(original.exists())
        rollback(self.journal, original, single=True)
        self.assertEqual(before, self.snapshot(self.root))

    def test_collisions_use_virtual_state_and_existing_files(self):
        first = self.root / "one.mkv"
        second = self.root / "two.mkv"
        first.write_bytes(b"one")
        second.write_bytes(b"two")
        planner = Planner(self.root)
        target = self.root / "destination.mkv"
        planner.rename(first, target)
        self.assertTrue(planner.occupied(target))
        self.assertFalse(planner.occupied(first))
        with self.assertRaises(FileExistsError):
            planner.rename(second, target)
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())

    def test_apply_refuses_changed_source(self):
        source = self.root / "one.mkv"
        source.write_bytes(b"original")
        planner = Planner(self.root)
        target = self.root / "new.mkv"
        planner.rename(source, target)
        source.rename(self.root / "original.mkv")
        source.write_bytes(b"replacement")
        with self.assertRaises(UnsafePathError):
            apply_plan(planner.plan(), self.journal)
        self.assertEqual(source.read_bytes(), b"replacement")
        self.assertFalse(target.exists())
        self.assertEqual(rollback(self.journal, self.root), 0)

    def test_partial_apply_can_rollback_completed_changes(self):
        first = self.root / "one.mkv"
        second = self.root / "two.mkv"
        first.write_bytes(b"one")
        second.write_bytes(b"two")
        planner = Planner(self.root)
        first_target = self.root / "first-target.mkv"
        second_target = self.root / "second-target.mkv"
        planner.rename(first, first_target)
        planner.rename(second, second_target)
        second_target.write_bytes(b"unexpected")
        with self.assertRaises(FileExistsError):
            apply_plan(planner.plan(), self.journal)
        self.assertFalse(first.exists())
        self.assertTrue(first_target.exists())
        self.assertEqual(rollback(self.journal, self.root), 1)
        self.assertEqual(first.read_bytes(), b"one")
        self.assertEqual(second.read_bytes(), b"two")
        self.assertEqual(second_target.read_bytes(), b"unexpected")

    def test_rollback_never_removes_nonempty_created_directory(self):
        planner = Planner(self.root)
        folder = self.root / "new-folder"
        planner.mkdir(folder)
        apply_plan(planner.plan(), self.journal)
        (folder / "keep.txt").write_bytes(b"keep")
        with self.assertRaises(UnsafePathError):
            rollback(self.journal, self.root)
        self.assertEqual((folder / "keep.txt").read_bytes(), b"keep")

    def test_rollback_will_not_overwrite_recreated_source(self):
        source, target = self.root / "one.mkv", self.root / "new.mkv"
        source.write_bytes(b"original")
        planner = Planner(self.root)
        planner.rename(source, target)
        apply_plan(planner.plan(), self.journal)
        source.write_bytes(b"new")
        with self.assertRaises(FileExistsError):
            rollback(self.journal, self.root)
        self.assertEqual(source.read_bytes(), b"new")
        self.assertEqual(target.read_bytes(), b"original")

    def test_interrupted_journal_refuses_to_guess(self):
        planner = Planner(self.root)
        planner.mkdir(self.root / "new-dir")
        plan = planner.plan()
        self.journal.write_text(
            json.dumps({"event": "header", "plan": plan.to_dict()}) + "\n" +
            json.dumps({"event": "pending", "index": 0}) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(UnsafePathError):
            rollback(self.journal, self.root)

    def test_apply_rejects_plan_outside_selected_root(self):
        source = self.root / "one.mkv"
        source.write_bytes(b"original")
        plan = Plan(self.root, False, (
            Operation("rename", self.parent / "outside.mkv", source, identity(source)),
        ))
        with self.assertRaises(UnsafePathError):
            apply_plan(plan, self.journal)
        self.assertTrue(source.exists())
        self.assertFalse((self.parent / "outside.mkv").exists())

    def test_plan_output_is_exclusive_and_outside_media(self):
        plan = Plan(self.root, False, ())
        write_plan(plan, self.plan_file)
        with self.assertRaises(FileExistsError):
            write_plan(plan, self.plan_file)
        with self.assertRaises(UnsafePathError):
            write_plan(plan, self.root / "plan.json")

    def test_replay_requires_same_root_and_mode(self):
        plan = Plan(self.root, False, ())
        write_plan(plan, self.plan_file)
        with self.assertRaises(SystemExit):
            cli.main([str(self.parent / "different"), "--apply-plan", str(self.plan_file)])
        with self.assertRaises(SystemExit):
            cli.main([str(self.root), "--single", "--apply-plan", str(self.plan_file)])


if __name__ == "__main__":
    unittest.main()
