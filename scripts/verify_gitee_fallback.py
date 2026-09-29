"""Block GitHub requests locally; verify actual anonymous Gitee downloads."""
import json
from pathlib import Path
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from isaac_link.updates import UpdateManager,GITEE_SOURCE


def main():
    original=urllib.request.urlopen
    blocked=[]
    def open_url(request,*args,**kwargs):
        url=request.full_url if hasattr(request,'full_url') else request
        host=urllib.parse.urlsplit(url).hostname or ''
        if any(host==d or host.endswith('.'+d) for d in ('github.com','githubusercontent.com')):
            blocked.append(host);raise urllib.error.URLError('GitHub deliberately blocked for fallback test')
        return original(request,*args,**kwargs)
    output=ROOT/'ui-validation';output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='gitee-update-',dir=output) as folder:
        manager=UpdateManager(folder)
        with patch('urllib.request.urlopen',side_effect=open_url):
            manager.check();assert manager.manifest_source==GITEE_SOURCE
            print('PASS: signed manifest fetched from public Gitee.',flush=True)
            manager.download();assert manager.status=='ready'
        assert urllib.parse.urlsplit(manager.download_source).hostname=='gitee.com'
        assert len(blocked)>=2
        result=dict(result='PASS',version=manager.manifest['version'],manifest_source=manager.manifest_source,
                    download_source=manager.download_source,github_requests_blocked=len(blocked),
                    signature_verified=True,package_bytes=manager.archive.stat().st_size,
                    method='Production UpdateManager with GitHub requests blocked; real public Gitee responses')
        (output/'gitee-fallback-result.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result))


if __name__=='__main__':main()
