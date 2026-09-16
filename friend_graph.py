"""Graph recommendations, Python 3.10+, no external dependencies."""
import argparse
import csv
import heapq
import json
import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Recommendation:
    user: str
    score: float
    mutual_friends_count: int
    jaccard: float
    adamic_adar: float
    mutual_friends: tuple[str, ...]


class SocialGraph:
    def __init__(self):
        self.adjacency = {}

    def add_user(self, user):
        user = user.strip()
        if not user:
            raise ValueError('Empty user ID')
        self.adjacency.setdefault(user, set())
        return user

    def add_friendship(self, first, second):
        first, second = first.strip(), second.strip()
        if not first or not second:
            raise ValueError('Empty user ID')
        self.add_user(first)
        self.add_user(second)
        if first != second:
            self.adjacency[first].add(second)
            self.adjacency[second].add(first)

    @property
    def user_count(self):
        return len(self.adjacency)

    @property
    def edge_count(self):
        return sum(map(len, self.adjacency.values())) // 2

    def friends_of(self, user):
        return set(self.adjacency[user.strip()])

    def recommend(self, user, limit=10, metric='combined'):
        if limit < 1:
            raise ValueError('Limit must be positive')
        if metric not in ('combined', 'mutual', 'jaccard', 'adamic-adar'):
            raise ValueError('Unknown metric')
        user = user.strip()
        friends = self.adjacency[user]
        mutuals = {}
        for friend in sorted(friends):
            for candidate in self.adjacency[friend]:
                if candidate != user and candidate not in friends:
                    mutuals.setdefault(candidate, []).append(friend)
        def results():
            for candidate, common in mutuals.items():
                count = len(common)
                jaccard = count / (len(friends) + len(self.adjacency[candidate]) - count)
                aa = sum(1 / math.log(len(self.adjacency[f])) for f in common)
                scores = {'mutual': float(count), 'jaccard': jaccard,
                          'adamic-adar': aa, 'combined': 3 * count + 2 * jaccard + aa}
                yield Recommendation(candidate, scores[metric], count, jaccard, aa, tuple(common))
        return heapq.nsmallest(limit, results(), key=lambda r: (-r.score, -r.mutual_friends_count, r.user))

    @classmethod
    def from_csv(cls, path):
        graph = cls()
        with open(path, encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            if not {'source', 'target'} <= set(reader.fieldnames or []):
                raise ValueError('CSV requires source,target')
            for row in reader:
                graph.add_friendship(row.get('source') or '', row.get('target') or '')
        return graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv_file')
    parser.add_argument('user')
    parser.add_argument('--limit', '-n', type=int, default=10)
    parser.add_argument('--metric', choices=['combined', 'mutual', 'jaccard', 'adamic-adar'], default='combined')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--stats', action='store_true')
    args = parser.parse_args()
    try:
        graph = SocialGraph.from_csv(args.csv_file)
        recommendations = graph.recommend(args.user, args.limit, args.metric)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'Error: {error}\n')
    if args.stats:
        import sys
        print(f'Users: {graph.user_count}; edges: {graph.edge_count}', file=sys.stderr)
    if args.json:
        print(json.dumps([asdict(r) for r in recommendations], ensure_ascii=False, indent=2))
    else:
        for r in recommendations:
            print(f'{r.user}: {r.score:.6f}; mutual: {", ".join(r.mutual_friends)}')
        if not recommendations:
            print('No candidates found')


if __name__ == '__main__':
    main()
