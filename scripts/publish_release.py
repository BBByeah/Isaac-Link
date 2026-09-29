"""Upload a complete draft, then publish it as latest. Credentials never printed."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from isaac_link.version import __version__
from isaac_link.updates import verified_manifest,verify_package

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--publish',action='store_true');args=parser.parse_args()
    repo='BBByeah/Isaac-Link';tag='v'+__version__;folder=ROOT/'release'
    names=[f'Isaac-Link-client-{tag}.zip',f'Isaac-Link-server-{tag}.zip','update.json']
    manifest=verified_manifest((folder/'update.json').read_bytes());verify_package(folder/names[0],manifest)
    if manifest['version']!=__version__:raise SystemExit('Manifest version mismatch')
    for name in names:
        if not (folder/name).is_file():raise SystemExit('Missing asset: '+name)
    notes=(ROOT/'docs/releases'/(__version__+'.md')).read_text(encoding='utf-8')
    if not args.publish:print('Validated assets for '+tag+'. Use --publish to upload and publish.');return
    origin=subprocess.check_output(['git','remote','get-url','origin'],cwd=ROOT,text=True).strip()
    if origin!='https://github.com/'+repo+'.git':raise SystemExit('Unexpected origin; refusing to publish')
    credentials=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\npath='+repo+'.git\n\n',
                               cwd=ROOT,text=True,capture_output=True,check=False)
    if credentials.returncode:raise SystemExit('Git credential lookup failed; credential output was not printed')
    values=dict(line.split('=',1) for line in credentials.stdout.splitlines() if '=' in line)
    token=values.get('password')
    if not token:raise SystemExit('No GitHub credential available')
    def request(url,method='GET',data=None,content_type='application/json'):
        body=json.dumps(data).encode('utf-8') if isinstance(data,dict) else data
        req=urllib.request.Request(url,data=body,method=method,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                 'X-GitHub-Api-Version':'2022-11-28','User-Agent':'Isaac-Link-release','Content-Type':content_type})
        try:
            with urllib.request.urlopen(req,timeout=180) as response:return json.load(response)
        except urllib.error.HTTPError as e:
            # Never dump request headers or authentication material.
            raise RuntimeError(f'GitHub API HTTP {e.code} for {method} {urllib.parse.urlsplit(url).path}') from None
    api='https://api.github.com/repos/'+repo
    releases=request(api+'/releases?per_page=100')
    release=next((r for r in releases if r['tag_name']==tag),None)
    if release and not release['draft']:raise SystemExit('Release already published; refusing to replace its assets')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    if not release:
        release=request(api+'/releases','POST',dict(tag_name=tag,target_commitish=commit,name='Isaac-Link '+__version__,body=notes,draft=True,prerelease=False))
    upload=release['upload_url'].split('{',1)[0]
    existing={a['name']:a for a in request(api+f"/releases/{release['id']}/assets")}
    for name in names:
        path=folder/name
        if name in existing:
            if existing[name]['size']!=path.stat().st_size:raise SystemExit('Draft contains mismatched asset: '+name)
            print('Already uploaded: '+name);continue
        request(upload+'?name='+urllib.parse.quote(name),'POST',path.read_bytes(),'application/json' if name.endswith('.json') else 'application/zip')
        print('Uploaded: '+name,flush=True)
    result=request(api+f"/releases/{release['id']}",'PATCH',dict(body=notes,draft=False,prerelease=False,make_latest='true'))
    print('Published: '+result['html_url'])

if __name__=='__main__':main()
