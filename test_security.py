"""Regression tests for security and privacy behavior (no real media or API calls)."""

import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

from media_cleanup import cli as movie_cleanup
from media_cleanup import tmdb as metadata
import movie_cleanup_V1
from filesystem_safety import FilesystemGuard, UnsafePathError, occupied


class FilesystemSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name).resolve()
        self.root = self.parent / "library"
        self.root.mkdir()
        self.guard = FilesystemGuard(self.root)

    def test_rename_and_mkdir_inside_root(self):
        self.guard.mkdir(self.root / "movies")
        source = self.root / "original.mkv"
        source.write_bytes(b"synthetic")
        target = self.root / "movies" / "Renamed.mkv"
        self.guard.rename(source, target)
        self.assertEqual(target.read_bytes(), b"synthetic")
        self.assertFalse(source.exists())

    def test_reject_outside_root(self):
        source = self.root / "original.mkv"
        source.touch()
        with self.assertRaises(UnsafePathError):
            self.guard.rename(source, self.parent / "outside.mkv")
        with self.assertRaises(UnsafePathError):
            self.guard.mkdir(self.parent / "outside")
        self.assertTrue(source.exists())

    def test_do_not_overwrite(self):
        source = self.root / "original.mkv"
        target = self.root / "existing.mkv"
        source.write_bytes(b"source")
        target.write_bytes(b"target")
        with self.assertRaises(FileExistsError):
            self.guard.rename(source, target)
        self.assertEqual(source.read_bytes(), b"source")
        self.assertEqual(target.read_bytes(), b"target")

    def test_single_folder_rename_updates_boundary(self):
        guard = FilesystemGuard(self.root, allow_root_rename=True)
        target = self.parent / "renamed"
        guard.rename(self.root, target)
        guard.mkdir(target / "Season 01")
        with self.assertRaises(UnsafePathError):
            guard.mkdir(self.root / "unexpected")
        self.assertTrue((target / "Season 01").is_dir())

    def test_library_root_cannot_be_renamed(self):
        with self.assertRaises(UnsafePathError):
            self.guard.rename(self.root, self.parent / "renamed")

    def test_links_are_not_traversed(self):
        outside = self.parent / "outside"
        outside.mkdir()
        (outside / "movie.mkv").touch()
        link = self.root / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks is not permitted on this system.")
        self.assertNotIn(link, self.guard.children(self.root))
        self.assertEqual(list(self.guard.walk(self.root)), [])
        with self.assertRaises(UnsafePathError):
            self.guard.mkdir(link / "unexpected")
        with self.assertRaises(UnsafePathError):
            FilesystemGuard(link)
        self.assertFalse((outside / "unexpected").exists())

    def test_dangling_link_is_occupied(self):
        link = self.root / "dangling"
        try:
            link.symlink_to(self.parent / "missing")
        except OSError:
            self.skipTest("Creating symlinks is not permitted on this system.")
        self.assertTrue(occupied(link))

    def test_reparse_point_is_rejected(self):
        # Exercise Windows junction detection without needing symlink privileges.
        from types import SimpleNamespace
        from filesystem_safety import _linklike

        fake = SimpleNamespace(st_mode=0, st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=fake):
            self.assertTrue(_linklike(self.root))

    def test_single_folder_apply_preserves_episodes(self):
        show = self.root / "Example Show"
        show.mkdir()
        (show / "Example.Show.S01E01.mkv").write_bytes(b"synthetic-one")
        (show / "Example.Show.S01E02.mkv").write_bytes(b"synthetic-two")
        with patch.object(metadata, "TMDB_API_KEY", ""), contextlib.redirect_stdout(io.StringIO()):
            with patch("sys.argv", ["movie_cleanup.py", str(show), "--single", "--apply"]):
                movie_cleanup.main()
        videos = list(self.root.rglob("*.mkv"))
        self.assertEqual(len(videos), 2)
        self.assertTrue(all(v.parent.name == "Season 01" for v in videos))
        self.assertEqual({v.read_bytes() for v in videos}, {b"synthetic-one", b"synthetic-two"})

    def test_legacy_single_folder_apply(self):
        movie = self.root / "Example Movie (2020)"
        movie.mkdir()
        (movie / "Example.Movie.2020.mkv").write_bytes(b"synthetic")
        with patch.object(movie_cleanup_V1, "TMDB_API_KEY", ""), contextlib.redirect_stdout(io.StringIO()):
            with patch("sys.argv", ["movie_cleanup_V1.py", str(movie), "--apply"]):
                movie_cleanup_V1.main()
        videos = list(self.root.rglob("*.mkv"))
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0].read_bytes(), b"synthetic")

    def test_dry_run_preserves_files_and_apply_routes_movie(self):
        movie = self.root / "Example Movie (2020)"
        movie.mkdir()
        (movie / "Example.Movie.2020.mkv").write_bytes(b"synthetic")
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        with patch.object(metadata, "TMDB_API_KEY", ""), contextlib.redirect_stdout(io.StringIO()):
            with patch("sys.argv", ["movie_cleanup.py", str(self.root)]):
                movie_cleanup.main()
            after = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
            self.assertEqual(before, after)
            with patch("sys.argv", ["movie_cleanup.py", str(self.root), "--apply"]):
                movie_cleanup.main()
        self.assertFalse(movie.exists())
        videos = list((self.root / "0_Movies").rglob("*.mkv"))
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0].read_bytes(), b"synthetic")


class PrivacyTests(unittest.TestCase):
    def test_api_error_does_not_print_credentials(self):
        dummy = "synthetic-test-credential"
        calls = [
            ("search_tmdb_movie", "Example"),
            ("get_tmdb_localized_titles", 1),
            ("search_tmdb_tv", "Example"),
            ("get_tmdb_tv_localized_titles", 1),
        ]
        for module in (metadata, movie_cleanup_V1):
            for name, argument in calls:
                with self.subTest(module=module.__name__, function=name):
                    output = io.StringIO()
                    with patch.object(module, "TMDB_API_KEY", dummy), patch.object(
                        module.requests, "get",
                        side_effect=requests.HTTPError("Sensitive URL: api_key=" + dummy),
                    ), contextlib.redirect_stdout(output):
                        getattr(module, name)(argument)
                    self.assertNotIn(dummy, output.getvalue())
                    self.assertIn("HTTPError", output.getvalue())


if __name__ == "__main__":
    unittest.main()
