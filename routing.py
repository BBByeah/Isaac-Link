"""Small deterministic routing optimizer. Times are RTT/barrier proxies, not one-way latency."""
import itertools
import math

ROUTES = ('ipv6', 'ipv4', 'relay', 'steam')
LABELS = dict(zip(ROUTES, ('IPv6 直连', 'IPv4 打洞', '服务器中转', 'Steam 原生')))

def edge(a, b):
    return ':'.join(sorted((str(a), str(b)), key=int))

def percentile(values, p=.95):
    if not values:return None
    values=sorted(values)
    return values[min(len(values)-1, math.ceil(len(values)*p)-1)]

def candidates(members, reports, count=3, fixed=None):
    choices=[]; edges=[]
    for a,b in itertools.combinations(members,2):
        options=[]
        for route in ROUTES:
            if fixed and edge(a,b) in fixed and route!=fixed[edge(a,b)]:continue
            left=reports.get(a,{}).get('links',{}).get(b,{}).get(route,{})
            right=reports.get(b,{}).get('links',{}).get(a,{}).get(route,{})
            if min(left.get('received',0),right.get('received',0))<8:continue
            loss=max(left.get('loss',1),right.get('loss',1))
            if loss>.25:continue
            score=max(left['p95'],right['p95'])+1000*loss
            options.append((route,score))
        if not options:return []
        edges.append(edge(a,b));choices.append(options)
    ranked=[]
    for combination in itertools.product(*choices):
        scores=[x[1] for x in combination]
        ranked.append((max(scores),sum(scores),dict(zip(edges,[x[0] for x in combination]))))
    ranked.sort(key=lambda x:(x[0],x[1]))
    return [x[2] for x in ranked[:count]]

def choose(plans, members, reports):
    ranked=[]
    for i,plan in enumerate(plans):
        results=[reports.get(p,{}).get('rounds',{}).get(str(i),{}) for p in members]
        if not results or any(r.get('count',0)<15 for r in results):continue
        if any(r.get('loss',1)>.10 for r in results):continue
        ranked.append((max(r['p95'] for r in results),max(r['loss'] for r in results),i))
    if not ranked:return None
    return plans[min(ranked)[2]]
