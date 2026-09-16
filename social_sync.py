"""Atomic per-owner snapshot sync; single writer only."""
import argparse
import csv
import os
import tempfile
from pathlib import Path
from social_api import VKClient, FacebookClient, LinkedInClient, SocialAPIError

COLUMNS = ['source', 'target', 'provider', 'owner_id']


class IdentityResolver:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    @classmethod
    def from_csv(cls, path):
        mapping = {}
        if path:
            with open(path, encoding='utf-8-sig', newline='') as stream:
                reader = csv.DictReader(stream)
                if not {'provider', 'external_id', 'canonical_id'} <= set(reader.fieldnames or []):
                    raise ValueError('Invalid identity map header')
                for row in reader:
                    provider, external, canonical = [(row.get(k) or '').strip() for k in ('provider', 'external_id', 'canonical_id')]
                    if not all((provider, external, canonical)):
                        raise ValueError('Empty identity mapping')
                    key = provider, external
                    if key in mapping and mapping[key] != canonical:
                        raise ValueError('Conflicting identity mapping')
                    mapping[key] = canonical
        return cls(mapping)

    def resolve(self, account):
        canonical = self.mapping.get((account.provider, account.external_id))
        return 'person:' + canonical if canonical else account.node_id


def sync_snapshot(client, output, resolver=None, append=False):
    resolver = resolver or IdentityResolver()
    owner = client.get_me()
    friends = list(client.iter_friends())  # No file mutation until API completes.
    rows = []
    path = Path(output)
    if append and path.exists():
        with path.open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != COLUMNS:
                raise ValueError('Snapshot schema mismatch')
            for row in reader:
                if None in row or any(not row.get(k) for k in COLUMNS):
                    raise ValueError('Invalid existing snapshot')
                if (row['provider'], row['owner_id']) != (owner.provider, owner.external_id):
                    rows.append(row)
    source = resolver.resolve(owner)
    targets = set()
    for friend in friends:
        if friend.provider != owner.provider:
            raise ValueError('Provider mismatch')
        target = resolver.resolve(friend)
        if target != source and target not in targets:
            targets.add(target)
            rows.append(dict(source=source, target=target, provider=owner.provider, owner_id=owner.external_id))
    fd, temporary = tempfile.mkstemp(prefix='.sync-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return len(targets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', required=True, choices=['vk', 'facebook', 'linkedin'])
    parser.add_argument('--token-env', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--append', action='store_true')
    parser.add_argument('--identity-map')
    parser.add_argument('--vk-version', default='5.199')
    parser.add_argument('--facebook-version', default=os.environ.get('FACEBOOK_API_VERSION', ''))
    args = parser.parse_args()
    try:
        token = os.environ.get(args.token_env, '').strip()
        if not token:
            raise ValueError('Missing token environment variable')
        if args.provider == 'vk':
            client = VKClient(token, args.vk_version)
        elif args.provider == 'facebook':
            client = FacebookClient(token, args.facebook_version)
        else:
            client = LinkedInClient()
        count = sync_snapshot(client, args.output, IdentityResolver.from_csv(args.identity_map), args.append)
    except (SocialAPIError, ValueError, KeyError, TypeError, IndexError, OSError):
        parser.exit(1, 'Import failed; check permissions, configuration and response schema.\n')
    print(f'Imported connections: {count}')


if __name__ == '__main__':
    main()
