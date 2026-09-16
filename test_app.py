import csv
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from friend_graph import SocialGraph
from social_api import FacebookClient, LinkedInClient, SocialAccount, SocialAPIError, request_json
from social_sync import sync_snapshot, IdentityResolver


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.g = SocialGraph()
        for a, b in [('a', 'b'), ('a', 'c'), ('b', 'd'), ('c', 'd'), ('c', 'e')]:
            self.g.add_friendship(a, b)

    def test_statistics(self):
        self.assertEqual((self.g.user_count, self.g.edge_count), (5, 5))

    def test_scores(self):
        result = self.g.recommend('a')[0]
        self.assertEqual(result.user, 'd')
        self.assertEqual(result.mutual_friends_count, 2)
        self.assertEqual(result.jaccard, 1)
        self.assertAlmostEqual(result.adamic_adar, 1 / math.log(2) + 1 / math.log(3))

    def test_exclusions(self):
        self.assertEqual({r.user for r in self.g.recommend('a')}, {'d', 'e'})

    def test_duplicates(self):
        self.g.add_friendship('b', 'a')
        self.g.add_friendship('a', 'a')
        self.assertEqual(self.g.edge_count, 5)

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.g.recommend('a', limit=0)
        with self.assertRaises(KeyError):
            self.g.recommend('missing')
        with self.assertRaises(ValueError):
            self.g.recommend('a', metric='unknown')

    def test_example(self):
        graph = SocialGraph.from_csv(Path(__file__).with_name('example_edges.csv'))
        self.assertEqual([r.user for r in graph.recommend('alice')], ['george', 'diana', 'elena'])


class APITests(unittest.TestCase):
    def test_untrusted_host(self):
        with self.assertRaises(SocialAPIError):
            request_json('https://evil.example/me', 'secret')

    def test_linkedin_disabled(self):
        with self.assertRaises(SocialAPIError):
            LinkedInClient()

    @patch('social_api.request_json')
    def test_facebook_cursor_uses_fixed_host(self, request):
        request.side_effect = [
            {'data': [{'id': '1'}], 'paging': {'next': 'https://evil.example', 'cursors': {'after': 'cursor'}}},
            {'data': [{'id': '2'}]}]
        friends = list(FacebookClient('secret', 'v22.0').iter_friends())
        self.assertEqual([f.external_id for f in friends], ['1', '2'])
        self.assertEqual(request.call_args.args[0], 'https://graph.facebook.com/v22.0/me/friends')
        self.assertEqual(request.call_args.kwargs['params']['after'], 'cursor')

    @patch('social_api.request_json')
    def test_repeated_cursor(self, request):
        request.return_value = {'data': [], 'paging': {'next': 'ignored', 'cursors': {'after': 'x'}}}
        with self.assertRaises(SocialAPIError):
            list(FacebookClient('secret', 'v22.0').iter_friends())


class SyncTests(unittest.TestCase):
    def test_identity(self):
        resolver = IdentityResolver({('vk', '1'): 'alice'})
        self.assertEqual(resolver.resolve(SocialAccount('vk', '1')), 'person:alice')
        self.assertEqual(resolver.resolve(SocialAccount('vk', '2')), 'vk:2')

    def test_failure_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'graph.csv'
            path.write_text('original', encoding='utf-8')
            client = Mock()
            client.get_me.return_value = SocialAccount('vk', '1')
            client.iter_friends.side_effect = SocialAPIError('failure')
            with self.assertRaises(SocialAPIError):
                sync_snapshot(client, path)
            self.assertEqual(path.read_text(encoding='utf-8'), 'original')

    def test_refresh_replaces_owner_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'graph.csv'
            client = Mock()
            client.get_me.return_value = SocialAccount('vk', '1')
            client.iter_friends.return_value = [SocialAccount('vk', '2')]
            sync_snapshot(client, path)
            client.get_me.return_value = SocialAccount('vk', '3')
            client.iter_friends.return_value = [SocialAccount('vk', '4')]
            sync_snapshot(client, path, append=True)
            client.get_me.return_value = SocialAccount('vk', '1')
            client.iter_friends.return_value = []
            sync_snapshot(client, path, append=True)
            with path.open(newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['source'], 'vk:3')


if __name__ == '__main__':
    unittest.main()
