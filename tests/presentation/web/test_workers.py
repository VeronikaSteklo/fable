from contextlib import redirect_stdout
from io import StringIO
import os
import unittest
from unittest.mock import patch

from tests.application.test_bootstrap import settings
from fable.presentation.web.app import main


class WorkerTests(unittest.TestCase):
    def test_multiple_workers_require_both_services(self):
        output = StringIO()
        with patch('fable.presentation.web.app.load_settings', return_value=settings()), \
                patch.dict(os.environ, {'FABLE_WORKERS': '2'}), \
                patch('fable.presentation.web.app.uvicorn.run') as run, redirect_stdout(output):
            main()
        run.assert_not_called()
        self.assertIn('DATABASE_URL и REDIS_URL', output.getvalue())

    def test_multiple_workers_use_import_factory_without_parent_connections(self):
        config = settings(database_url='postgresql://unused', redis_url='redis://unused')
        with patch('fable.presentation.web.app.load_settings', return_value=config), \
                patch.dict(os.environ, {'FABLE_WORKERS': '2', 'FABLE_PORT': '8123'}), \
                patch('fable.presentation.web.app.create_app') as create, \
                patch('fable.presentation.web.app.uvicorn.run') as run:
            main()
        create.assert_not_called()
        self.assertEqual(run.call_args.args[0], 'fable.presentation.web.app:create_app')
        self.assertTrue(run.call_args.kwargs['factory'])
        self.assertEqual(run.call_args.kwargs['workers'], 2)
