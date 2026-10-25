import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from social_api import VKClient, FacebookClient, SocialAPIError
from social_sync import sync_snapshot


class ResponseValidationTests(unittest.TestCase):
    @patch('social_api.request_json')
    def test_vk_count_larger_than_snapshot_fails_atomically(self, request):
        request.side_effect = [{'response': [{'id': 1}]},
            {'response': {'count': 1, 'items': [2, 3]}}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.csv'
            path.write_text('preserve me')
            with self.assertRaises(SocialAPIError):
                sync_snapshot(VKClient('test'), path)
            self.assertEqual(path.read_text(), 'preserve me')

    @patch('social_api.request_json')
    def test_vk_count_must_be_nonnegative_integer(self, request):
        for count in (-1, '2', True):
            with self.subTest(count=count):
                request.return_value = {'response': {'count': count, 'items': []}}
                with self.assertRaises(SocialAPIError):
                    list(VKClient('test').iter_friends())

    @patch('social_api.request_json')
    def test_facebook_repeated_ids_fail(self, request):
        request.side_effect = [
            {'data': [{'id': '1'}], 'paging': {'next': 'unused', 'cursors': {'after': 'x'}}},
            {'data': [{'id': '1'}]}]
        with self.assertRaises(SocialAPIError):
            list(FacebookClient('test', 'v22.0').iter_friends())

    @patch('social_api.request_json')
    def test_invalid_friend_id_fails(self, request):
        request.return_value = {'response': {'count': 1, 'items': [None]}}
        with self.assertRaises(SocialAPIError):
            list(VKClient('test').iter_friends())
