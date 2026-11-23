"""Project metadata drives filtering; standalone files keep local compatibility."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'niri/shell'))
import wallpaper as w
import wallpaper_options as options
import wallpaper_playlist as playlist


class ProjectRatingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='selandia-ratings-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, XDG_STATE_HOME=str(self.root / 'state'),
                         XDG_CACHE_HOME=str(self.root / 'cache'), XDG_RUNTIME_DIR=str(self.root))
        env.start(); self.addCleanup(env.stop)
        options._project_contentrating.cache_clear()
        self.addCleanup(options._project_contentrating.cache_clear)
        self.rotation_events = []
        stack_log = patch.object(w, 'log_rotation', side_effect=lambda event, **values: self.rotation_events.append((event, values)))
        stack_log.start(); self.addCleanup(stack_log.stop)

    def project(self, name, rating=None):
        folder = self.root / name
        folder.mkdir(exist_ok=True)
        (folder / 'image.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="50"><rect width="80" height="50" fill="blue"/></svg>')
        metadata = {'type': 'image', 'file': 'image.svg', 'preview': 'image.svg', 'title': name}
        if rating is not None:
            metadata['contentrating'] = rating
        (folder / 'project.json').write_text(json.dumps(metadata))
        return folder

    def test_project_rating_aliases_and_missing_values(self):
        for expected, values in {'everyone': ['Everyone', ' General ', 'g'],
                                 'questionable': ['PG13', 'pg-13', 'PG 13', 'Questionable'],
                                 'mature': ['Mature', 'adult', 'AdultOnly', '18+', 'R18'],
                                 'unrated': [None, '', 'unknown', 18, [], {}]}.items():
            for value in values:
                with self.subTest(value=value):
                    self.assertEqual(options.project_rating(value), expected)

    def test_discovery_and_direct_project_description_keep_original_rating(self):
        folder = self.project('workshop', 'PG13')
        item = w.describe(folder / 'project.json')
        self.assertEqual(item['contentrating'], 'PG13')
        self.assertEqual(item['rating_source'], 'project')
        result = w.discover({'roots': [str(folder)], 'assets': ''}, libraries=[])
        self.assertEqual(result['items'], [item])

    def test_project_metadata_takes_priority_over_old_local_labels(self):
        folder = self.project('workshop', 'Mature')
        settings = {'ratings': {str(folder): 'everyone'}}
        self.assertFalse(options.allowed(settings, str(folder)))
        self.assertFalse(options.allowed(settings, str(folder), item=w.describe(folder)))
        self.assertEqual(options.rating_info(settings, folder)['source'], 'project')

    def test_unrated_projects_are_distinct_from_personal_files(self):
        folder = self.project('unrated')
        self.assertFalse(options.allowed({}, folder))
        self.assertTrue(options.allowed({'rating_filter': options.filter_value('unrated')}, folder))
        file = folder / 'image.svg'
        self.assertTrue(options.allowed({}, file, item=w.describe(file)))
        self.assertEqual(options.rating_info({'ratings': {str(file): 'mature'}}, file)['rating'], 'mature')

    def test_every_category_and_all_filter_have_exact_semantics(self):
        items = {'everyone': self.project('everyone', 'Everyone'),
                 'pg13': self.project('teen', 'PG13'),
                 'mature': self.project('adult', 'Mature'),
                 'unrated': self.project('unknown')}
        for choice in (*items, 'all'):
            value = options.filter_value(choice)
            self.assertEqual(options.filter_choice(value), choice)
            matches = [key for key, path in items.items() if options.allowed({'rating_filter': value}, path)]
            self.assertEqual(matches, list(items) if choice == 'all' else [choice])

    def test_saved_mixed_filter_is_preserved_without_broadening(self):
        value = options.rating_filter({'questionable': True, 'mature': False})
        self.assertEqual(options.filter_choice(value), 'custom')
        self.assertTrue(value['everyone']); self.assertTrue(value['questionable'])
        self.assertFalse(value['mature']); self.assertFalse(value['unrated'])
        self.assertEqual(w.normalize_settings({'rating_filter': value})['rating_filter'], value)

    def test_item_filter_and_summary_never_read_disk(self):
        folder = self.project('workshop', 'PG13')
        item = w.describe(folder)
        with patch.object(Path, 'stat', side_effect=AssertionError('UI disk read')), \
             patch.object(Path, 'open', side_effect=AssertionError('UI disk read')):
            self.assertEqual(options.rating_info({}, folder, item=item)['rating'], 'questionable')
            self.assertTrue(options.allowed({'rating_filter': options.filter_value('pg13')}, folder, item=item))

    def test_resident_cache_reuses_reads_and_notices_replaced_metadata(self):
        folder = self.project('workshop', 'Mature')
        self.assertEqual(options.rating_info({}, folder)['rating'], 'mature')
        with patch.object(Path, 'open', side_effect=AssertionError('Repeated metadata read')):
            self.assertEqual(options.rating_info({}, folder)['rating'], 'mature')
        metadata = folder / 'project.json'
        old = metadata.stat()
        replacement = folder / 'replacement.json'
        replacement.write_text(metadata.read_text().replace('Mature', 'abcdef'))
        os.utime(replacement, ns=(old.st_atime_ns, old.st_mtime_ns))
        replacement.replace(metadata)
        self.assertEqual(options.rating_info({}, folder)['rating'], 'unrated')

    def test_invalid_or_oversize_metadata_is_unrated(self):
        folder = self.project('workshop', 'Everyone')
        for data in ('[]', '{bad', '{"contentrating":' + ' ' * 2_000_000 + '"Everyone"}'):
            (folder / 'project.json').write_text(data)
            self.assertEqual(options.rating_info({}, folder)['rating'], 'unrated')

    def test_hidden_project_cannot_apply_and_failed_filter_keeps_selection(self):
        folder = self.project('adult', 'Mature')
        settings = w.load_settings()
        settings['ratings'][str(folder)] = 'everyone'
        w.save_settings(settings)
        before = (w.state_dir() / 'wallpaper.json').read_bytes()
        handoff = Mock()
        with self.assertRaises(ValueError):
            w.activate(folder, handoff=handoff)
        handoff.assert_not_called()
        self.assertEqual((w.state_dir() / 'wallpaper.json').read_bytes(), before)
        with self.assertRaises(ValueError):
            w.configure_rating_filter(options.filter_value('all'), handoff=handoff)
        self.assertEqual((w.state_dir() / 'wallpaper.json').read_bytes(), before)

    def test_rotation_and_legacy_projection_use_project_metadata_without_writes(self):
        adult = self.project('adult', 'Mature')
        teen = self.project('teen', 'PG13')
        data = {path: (path / 'project.json').read_bytes() for path in (adult, teen)}
        value = w.load_settings()
        value['rating_filter'] = options.filter_value('pg13')
        value['playlist'] = playlist.validate({'enabled': True, 'items': [
            {'path': str(adult), 'mode': 'preview'}, {'path': str(teen), 'mode': 'preview'}]}, w.clean_path)
        w.save_settings(value)
        raw = json.loads((w.state_dir() / 'wallpaper.json').read_text())
        self.assertEqual([item['path'] for item in raw['playlist']['items']], [str(teen)])
        with patch.object(w, 'activate', return_value={'item': w.describe(teen), 'warnings': []}) as activate:
            result = w.playlist_step(handoff=Mock())
            self.assertEqual(result['item']['path'], str(teen))
            self.assertEqual(activate.call_args.args[0], str(teen))
        self.assertEqual({path: (path / 'project.json').read_bytes() for path in data}, data)


if __name__ == '__main__':
    unittest.main()
