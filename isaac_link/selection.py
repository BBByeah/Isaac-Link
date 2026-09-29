"""Pure, clock-driven per-edge routing policy (scores are RTT proxies)."""
from dataclasses import dataclass, field
import math

PERIOD = 30.0
WINDOW = 5.0
DEAD_AFTER = 3.0
COOLDOWN = 60.0
MIN_GAIN = 10.0
REL_GAIN = .20
ORDER = ('lan', 'ipv6', 'ipv4', 'steam', 'relay')

def quality(left, right):
    if not left or not right:return math.inf
    if min(left.get('received', 0), right.get('received', 0)) < 3:return math.inf
    loss = max(left.get('loss', 1), right.get('loss', 1))
    values = [left.get('p95'), right.get('p95')]
    if loss > .25 or any(v is None or not math.isfinite(v) or v < 0 for v in values):return math.inf
    return max(values) + 1000 * loss

@dataclass
class Selector:
    current: str | None = None
    fixed: str = 'auto'
    switched: float = -1e9
    contender: str | None = None
    wins: int = 0
    last_round: int = -1

    def choose(self, scores, available, now, round_id=None):
        if self.fixed != 'auto':return self.fixed if self.fixed in available else None
        valid = [r for r in ORDER if r in available and math.isfinite(scores.get(r, math.inf))]
        if not valid:return None
        best = min(valid, key=lambda r:(scores[r], r != self.current, ORDER.index(r)))
        if self.current not in available:return best
        if round_id is None or round_id == self.last_round:return self.current
        self.last_round = round_id
        old = scores.get(self.current, math.inf)
        gain = old - scores[best]
        if best == self.current or gain < MIN_GAIN or gain < old * REL_GAIN or now-self.switched < COOLDOWN:
            self.contender=None;self.wins=0;return self.current
        self.wins = self.wins+1 if self.contender == best else 1
        self.contender = best
        return best if self.wins >= 2 else self.current

    def commit(self, route, now):
        self.current=route;self.switched=now;self.contender=None;self.wins=0

@dataclass
class ControlSelector:
    current: str | None = None
    fixed: str = 'auto'
    since: dict = field(default_factory=dict)

    def choose(self, available, scores, now):
        for r in list(self.since):
            if r not in available:del self.since[r]
        for r in available:self.since.setdefault(r, now)
        if self.fixed != 'auto':
            self.current=self.fixed if self.fixed in available else None
            return self.current
        rank={'relay':0,'lan':1,'ipv6':2,'ipv4':2,'steam':3}
        choices=sorted(available, key=lambda r:(rank[r], scores.get(r, math.inf), r != self.current))
        if not choices:self.current=None;return None
        best=choices[0]
        if self.current not in available:self.current=best
        elif best != self.current and now-self.since[best]>=5:
            old=scores.get(self.current, math.inf);new=scores.get(best, math.inf)
            if rank[best]<rank[self.current] or (rank[best]==rank[self.current] and old-new>=max(10,old*.2)):
                self.current=best
        return self.current
