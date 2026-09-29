"""Upload a complete draft, then publish it as latest. Credentials never printed."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from isaac_link.version import __version__
from isaac_link.updates import verified_manifest,verify_package

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--publish',action='store_true');parser.add_argument('--stage-packages',action='store_true');parser.add_argument('--direct-upload',action='store_true');parser.add_argument('--repair-missing',action='store_true');parser.add_argument('--version',default=__version__);parser.add_argument('--folder',type=Path,default=ROOT/'release');parser.add_argument('--test-release',action='store_true');parser.add_argument('--revision',default='');args=parser.parse_args()
    version=args.version;repo='BBByeah/Isaac-Link';tag='v'+version;folder=args.folder.resolve()
    suffix='-'+args.revision if args.revision else ''
    names=[f'Isaac-Link-client-{tag}{suffix}.zip',f'Isaac-Link-server-{tag}.zip','update.json']
    if args.revision:names.append('start-isaac-link.cmd')
    if args.stage_packages:names.remove('update.json')
    manifest=verified_manifest((folder/'update.json').read_bytes());verify_package(folder/names[0],manifest)
    if manifest['version']!=version:raise SystemExit('Manifest version mismatch')
    for name in names:
        if not (folder/name).is_file():raise SystemExit('Missing asset: '+name)
    notes=(ROOT/'docs/releases'/(version+'.md')).read_text(encoding='utf-8')
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
        if isinstance(data,Path):
            # Stream large assets with curl instead of a single SSL sendall buffer.
            config='\n'.join(['header = "Authorization: Bearer '+token+'"','header = "Content-Type: '+content_type+'"','header = "User-Agent: Isaac-Link-release"'])+'\n'
            command=['curl.exe','--config','-','--silent','--show-error','--fail-with-body','--connect-timeout','20','--max-time','600','--request',method,'--data-binary','@'+str(data),url]
            if args.direct_upload:command[1:1]=['--noproxy','*']
            result=subprocess.run(command,input=config,text=True,capture_output=True)
            if result.returncode:raise RuntimeError('Upload failed (curl '+str(result.returncode)+'): '+result.stderr[-400:].replace(token,'[redacted]'))
            return json.loads(result.stdout)
        body=json.dumps(data).encode('utf-8') if isinstance(data,dict) else data
        req=urllib.request.Request(url,data=body,method=method,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                 'X-GitHub-Api-Version':'2022-11-28','User-Agent':'Isaac-Link-release','Content-Type':content_type})
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({})).open if args.direct_upload and urllib.parse.urlsplit(url).hostname=='uploads.github.com' else urllib.request.urlopen
            with opener(req,timeout=300) as response:return None if response.status==204 else json.load(response)
        except urllib.error.HTTPError as e:
            # Never dump request headers or authentication material.
            raise RuntimeError(f'GitHub API HTTP {e.code} for {method} {urllib.parse.urlsplit(url).path}') from None
    api='https://api.github.com/repos/'+repo
    releases=request(api+'/releases?per_page=100')
    release=next((r for r in releases if r['tag_name']==tag),None)
    if release and not release['draft']:
        if not args.repair_missing:raise SystemExit('Release already published; refusing to replace its assets')
        release=request(api+f"/releases/{release['id']}",'PATCH',dict(draft=True))
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    if not release:
        release=request(api+'/releases','POST',dict(tag_name=tag,target_commitish=commit,name='Isaac-Link '+version+(' 更新测试' if args.test_release else ''),body=notes,draft=True,prerelease=False))
    upload=release['upload_url'].split('{',1)[0]
    existing={a['name']:a for a in request(api+f"/releases/{release['id']}/assets")}
    for name in names:
        path=folder/name
        if name in existing:
            if existing[name]['state']!='uploaded' or (args.revision and name=='update.json'):
                request(api+f"/releases/assets/{existing[name]['id']}",'DELETE')
            else:
                if existing[name]['size']!=path.stat().st_size:raise SystemExit('Draft contains mismatched asset: '+name)
                print('Already uploaded: '+name);continue
        print('Uploading: '+name,flush=True)
        request(upload+'?name='+urllib.parse.quote(name),'POST',path,'application/json' if name.endswith('.json') else 'application/zip')
        print('Uploaded: '+name,flush=True)
    complete={a['name']:a for a in request(api+f"/releases/{release['id']}/assets")}
    if any(name not in complete or complete[name]['state']!='uploaded' or complete[name]['size']!=(folder/name).stat().st_size for name in names):
        raise SystemExit('Assets are not fully uploaded; draft was not published')
    if args.stage_packages:
        print('Package assets staged in GitHub draft; signed manifest not published.');return
    if args.revision and f'Isaac-Link-client-{tag}.zip' in complete:
        request(api+f"/releases/assets/{complete[f'Isaac-Link-client-{tag}.zip']['id']}",'DELETE')
    result=request(api+f"/releases/{release['id']}",'PATCH',dict(body=notes,draft=False,prerelease=False,make_latest='true'))
    print('Published: '+result['html_url'])

if __name__=='__main__':main()
