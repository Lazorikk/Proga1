import unittest
from unittest.mock import MagicMock, patch

from app import Handler, ROOT


class PageEncodingTests(unittest.TestCase):
    def test_home_page_uses_explicit_utf8(self):
        handler = Handler.__new__(Handler)
        handler.path = '/'
        handler.send = MagicMock()
        original = type(ROOT).read_text

        def windows_read_text(path, encoding=None, **kwargs):
            # Reproduce a Windows machine whose default encoding is CP1251.
            return original(path, encoding=encoding or 'cp1251', **kwargs)

        with patch('app.connect') as db, patch.object(
            type(ROOT), 'read_text', windows_read_text
        ):
            db.return_value.__enter__.return_value = MagicMock()
            handler.do_GET()

        page = handler.send.call_args.args[0]
        self.assertIn('КП-Мастер', page)
        self.assertIn('Новое предложение', page)
        self.assertEqual(handler.send.call_args.kwargs['mime'],
                         'text/html; charset=utf-8')
