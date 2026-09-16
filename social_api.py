"""Experimental adapters. No OAuth server; no scraping or automatic invitations."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


class SocialAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class SocialAccount:
    provider: str
    external_id: str

    @property
    def node_id(self):
        return f'{self.provider}:{self.external_id}'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url, token, *, form=None, params=None):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in {'api.vk.com', 'graph.facebook.com'}
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.query or parsed.fragment):
        raise SocialAPIError('Untrusted API address')
    headers = {'Accept': 'application/json'}
    data = None
    if form is not None:
        data = urllib.parse.urlencode({**form, 'access_token': token}).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    else:
        headers['Authorization'] = f'Bearer {token}'
    if params:
        url += '?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            body = response.read(8 * 1024 * 1024 + 1)
        if len(body) > 8 * 1024 * 1024:
            raise SocialAPIError('Response too large')
        result = json.loads(body)
    except urllib.error.HTTPError as error:
        raise SocialAPIError(f'API HTTP status {error.code}') from None
    except (urllib.error.URLError, OSError, ValueError):
        raise SocialAPIError('API transport or JSON error') from None
    if not isinstance(result, dict) or 'error' in result:
        raise SocialAPIError('API rejected request or returned invalid data')
    return result


class VKClient:
    def __init__(self, token, version='5.199'):
        if not token or not re.fullmatch(r'\d+\.\d+', version):
            raise ValueError('Token and valid VK API version required')
        self.token, self.version = token, version

    def call(self, method, **params):
        data = request_json(f'https://api.vk.com/method/{method}', self.token,
                            form={**params, 'v': self.version})
        if 'response' not in data:
            raise SocialAPIError('Missing VK response')
        return data['response']

    def get_me(self):
        return SocialAccount('vk', str(self.call('users.get')[0]['id']))

    def iter_friends(self):
        offset = 0
        seen = set()
        for _ in range(10000):
            response = self.call('friends.get', offset=offset, count=1000)
            items = response['items']
            if not isinstance(items, list):
                raise SocialAPIError('Invalid VK page')
            if not items:
                if offset < response['count']:
                    raise SocialAPIError('Incomplete VK snapshot')
                return
            ids = [str(item['id'] if isinstance(item, dict) else item) for item in items]
            if any(value in seen for value in ids) or len(set(ids)) != len(ids):
                raise SocialAPIError('Unstable VK pagination; retry snapshot')
            seen.update(ids)
            for value in ids:
                yield SocialAccount('vk', value)
            offset += len(items)
            if offset >= response['count']:
                return
        raise SocialAPIError('Pagination limit exceeded')


class FacebookClient:
    def __init__(self, token, version):
        if not token or not re.fullmatch(r'v\d+\.\d+', version):
            raise ValueError('Token and explicit Facebook API version required')
        self.token = token
        self.base = f'https://graph.facebook.com/{version}'

    def get_me(self):
        return SocialAccount('facebook', str(request_json(self.base + '/me', self.token, params={'fields': 'id'})['id']))

    def iter_friends(self):
        params = {'fields': 'id', 'limit': 100}
        cursors = set()
        for _ in range(10000):
            response = request_json(self.base + '/me/friends', self.token, params=params)
            if not isinstance(response.get('data'), list):
                raise SocialAPIError('Invalid Facebook page')
            for item in response['data']:
                yield SocialAccount('facebook', str(item['id']))
            paging = response.get('paging', {})
            if not paging.get('next'):
                return
            cursor = paging.get('cursors', {}).get('after')
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise SocialAPIError('Invalid Facebook pagination')
            cursors.add(cursor)
            params = {**params, 'after': cursor}
        raise SocialAPIError('Pagination limit exceeded')


class LinkedInClient:
    """Disabled until an approved product and its documented schema are supplied."""
    def __init__(self, *args, **kwargs):
        raise SocialAPIError('LinkedIn adapter is not implemented: approved API contract required')
